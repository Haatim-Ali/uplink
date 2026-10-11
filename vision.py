"""Photo -> food details.

The model only does what it's good at: name the food and count the units it can see.
Servings, weight and safe time are computed here in code from a small lookup table, so
the same count always gives the same numbers. If no model is connected the result is a
clearly labeled demo; if the model call fails the result is an empty form with the
reason, never a made-up guess.
"""
import base64
import io
import math
from concurrent.futures import ThreadPoolExecutor

import llm
from config import VISION_READS, VISION_SPLIT_MIN

try:  # optional: shrink photos and convert HEIC/odd formats to JPEG before sending
    from PIL import Image, ImageOps
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:
        pass
except ImportError:
    Image = None

CATEGORIES = ["hot prepared", "cold prepared", "packaged", "produce"]
SUPPORTED_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_EDGE = 1568  # long edge in px: plenty for counting, and keeps open models within their input limit
SAFE_MINUTES = {"hot prepared": 120, "cold prepared": 90, "packaged": 1440, "produce": 720}

# unit -> (servings per unit, lbs per unit). Rough, conservative values; the business confirms.
UNITS = {
    "bagel": (1, 0.25), "donut": (1, 0.15), "muffin": (1, 0.25), "croissant": (1, 0.15),
    "pastry": (1, 0.2), "cookie": (0.5, 0.06), "roll": (0.5, 0.1), "loaf": (8, 1.0),
    "sandwich": (1, 0.5), "wrap": (1, 0.5), "burrito": (1, 0.6), "slice": (1, 0.3),
    "pizza": (8, 2.4), "tray": (10, 6.0), "half tray": (5, 3.0), "pan": (10, 6.0),
    "box": (8, 3.0), "bag": (4, 1.5), "bowl": (1, 0.75), "container": (1, 0.75),
    "cup": (1, 0.5), "bottle": (1, 1.1), "can": (1, 0.8), "carton": (1, 1.0),
    "piece": (1, 0.3), "item": (1, 0.3), "fruit": (1, 0.4), "salad": (1, 0.6), "meal": (1, 1.0),
    "tub": (0, 0.5), "jar": (0, 1.0), "packet": (0, 0.05),  # spreads and condiments: weight, not meals
}
UNIT_ALIASES = {"slices": "slice", "pies": "pizza", "half-tray": "half tray", "hotel pan": "pan",
                "clamshell": "container", "plate": "meal", "portion": "meal", "serving": "meal"}

PROMPT = """This photo shows surplus food a business wants to donate. Identify and count it carefully.

Work in this order:
1. List each distinct kind of food you can see (e.g. "plain bagels", "sesame bagels", "cheese pizza").
2. For each kind, count the units you can actually see. Choose the unit from this list when one fits:
   bagel, donut, muffin, croissant, pastry, cookie, roll, loaf, sandwich, wrap, burrito, slice, pizza
   (a whole pie), tray, half tray, pan, box, bag, bowl, container, cup, bottle, can, carton, fruit,
   salad, meal, piece, tub, jar, packet. Count rows x columns when food is arranged in a grid. If some units are hidden
   (stacked, in a bag, under others), give a range: count_low = what you can see, count_high = your
   best upper estimate.
3. Say how you counted, in a few words.

Return ONLY a JSON object, no other text:
{"is_food": true,
 "groups": [{"name": "plain bagels", "unit": "bagel", "count_low": 12, "count_high": 12,
             "how_counted": "3 rows of 4"}],
 "category": "hot prepared" | "cold prepared" | "packaged" | "produce",
 "needs_cold": true/false (must it stay refrigerated?),
 "allergens": ["dairy","gluten","eggs","nuts","peanuts","soy","fish","shellfish"] (only likely ones),
 "allergens_uncertain": true/false (true if allergens you can't see may be present, e.g. nuts in baked goods),
 "confidence": "high" | "medium" | "low",
 "notes": "one short sentence about anything uncertain"}
If the photo does not show food, return {"is_food": false, "notes": "what the photo shows"}."""

HALF_NOTE = """

This is the {side} half of a larger photo, cut so you can see it up close. Count only food whose center
is inside this half; skip anything cut off at the edge that is mostly in the other half."""
SYSTEM = "You are a careful food-donation intake assistant. You count, you don't guess."
CONFIDENCE = ["low", "medium", "high"]
OUTLIER = 0.25   # a reading this far from the middle one only lowers confidence; it doesn't stretch the range
VIDEO_NOTE = ("\n\nThis image is a 2x2 grid of four frames from one short video panning across the same food. "
              "The same items appear in more than one frame: count each physical item once, using the frame that "
              "shows it best, and don't add up the frames.")

DEMO = {
    "items": ["pepperoni pizza"],
    "servings": 12,
    "weight_lbs": [3, 5],
    "allergens": ["dairy", "gluten"],
    "category": "hot prepared",
    "needs_cold": False,
    "safe_minutes": 120,
    "confidence": "demo",
    "notes": "DEMO MODE: no AI model is connected, so this is a sample result, not your photo. Edit everything.",
}

BLANK = {"items": [], "servings": 1, "weight_lbs": [1, 2], "allergens": [], "category": "hot prepared",
         "needs_cold": False, "safe_minutes": 120}


SAFE_BY_CATEGORY = SAFE_MINUTES  # name used by camera-side code and tests
NEUTRAL = {"items": ["food"], "servings": 1, "weight_lbs": [1, 2], "allergens": [], "category": "packaged",
           "needs_cold": False, "notes": ""}


def normalize(food, base=None):
    """Make sure the shape matches what the rest of the app expects. Missing fields come from `base`
    (neutral values by default; never the demo pizza, so it can't leak into a real donation).
    A missing safe time comes from the food's category."""
    f = dict(BLANK if base is None else base)
    if "safe_minutes" not in food:
        f["safe_minutes"] = SAFE_BY_CATEGORY.get(food.get("category"), 120)
    f.update({k: v for k, v in food.items() if v is not None})
    f["items"] = [str(i) for i in (f.get("items") or ["food"])]
    f["servings"] = max(1, int(float(f.get("servings", 1))))
    w = f.get("weight_lbs") or [1, 2]
    if not isinstance(w, (list, tuple)):
        w = [float(w), float(w)]
    f["weight_lbs"] = [float(w[0]), float(w[-1])]
    f["allergens"] = [str(a).lower() for a in (f.get("allergens") or [])]
    if f.get("category") not in CATEGORIES:
        f["category"] = "hot prepared"
    f["needs_cold"] = bool(f.get("needs_cold"))
    f["allergens_unverified"] = bool(f.pop("allergens_uncertain", False) or f.get("allergens_unverified"))
    f["safe_minutes"] = max(10, int(float(f.get("safe_minutes", 120))))
    return f


def _unit(name):
    u = str(name or "item").strip().lower()
    u = UNIT_ALIASES.get(u, u)
    if u not in UNITS and u.endswith("s") and u[:-1] in UNITS:
        u = u[:-1]
    return u if u in UNITS else "item"


def _best(g):
    """The best single estimate for a group: the middle reading's count, or the middle of the range."""
    return g.get("count", (g["count_low"] + g["count_high"]) / 2)


def _amounts(groups):
    """Servings (from the best estimate) and weight range (from the count range), using the unit table."""
    servings = sum(_best(g) * UNITS[g["unit"]][0] for g in groups)
    lo_lbs = sum(g["count_low"] * UNITS[g["unit"]][1] for g in groups)
    hi_lbs = sum(g["count_high"] * UNITS[g["unit"]][1] for g in groups)
    return max(1, round(servings)), [round(max(lo_lbs, 0.5), 1), round(max(hi_lbs, lo_lbs, 0.5), 1)]


def _counts_text(groups):
    return "; ".join(f"{g['name']}: {g['count_low']}" + (f"-{g['count_high']}" if g["count_high"] != g["count_low"] else "")
                     + f" {g['unit']}" + (f" ({g['how_counted']})" if g["how_counted"] else "") for g in groups)


def from_counts(data):
    """Turn the model's counted groups into servings, weight and safe time, in code."""
    groups = []
    for g in data.get("groups") or []:
        lo = max(0, int(float(g.get("count_low", g.get("count", 0)) or 0)))
        hi = max(lo, int(float(g.get("count_high", lo) or lo)))
        unit = _unit(g.get("unit"))
        groups.append({"name": str(g.get("name") or unit), "unit": unit, "count_low": lo, "count_high": hi,
                       "how_counted": str(g.get("how_counted") or "")})
    category = data.get("category") if data.get("category") in CATEGORIES else "hot prepared"
    counts = _counts_text(groups)
    notes = " ".join(x for x in [f"Counted {counts}." if counts else "", str(data.get("notes") or "")] if x)
    servings, weight = _amounts(groups)
    return {
        "items": [g["name"] for g in groups] or ["food"],
        "servings": servings,
        "weight_lbs": weight,
        "allergens": data.get("allergens") or [],
        "allergens_uncertain": bool(data.get("allergens_uncertain")),
        "category": category,
        "needs_cold": bool(data.get("needs_cold")),
        "safe_minutes": SAFE_MINUTES[category],
        "confidence": data.get("confidence") if data.get("confidence") in ("high", "medium", "low") else "low",
        "groups": groups,
        "notes": notes,
    }


def failed(reason):
    """An empty form plus the reason. Source "fallback" tells callers (e.g. camera.py) it isn't a real reading."""
    return dict(normalize({}), items=[], confidence="none",
                notes=f"Couldn't read the photo ({reason}). Please fill in the details by hand."), "fallback"


def _open(image_bytes):
    """The photo upright and in RGB, at full size, or None if it can't be opened here."""
    if Image is None:
        return None
    try:
        return ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert("RGB")
    except Exception:  # noqa: BLE001 - unreadable here; let the type check decide
        return None


def _jpeg(img):
    img = img.copy()
    img.thumbnail((MAX_EDGE, MAX_EDGE))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90)
    return out.getvalue()


def prepare(image_bytes, media_type):
    """Fix rotation, shrink to MAX_EDGE and re-encode as JPEG. Returns (bytes, media_type)."""
    img = _open(image_bytes)
    return (_jpeg(img), "image/jpeg") if img is not None else (image_bytes, media_type)


def halves(image_bytes):
    """Cut the full-size photo in two along its long side, so each half is seen at more detail."""
    img = _open(image_bytes)
    if img is None:
        return []
    w, h = img.size
    if w >= h:
        return [("left", _jpeg(img.crop((0, 0, w // 2, h)))), ("right", _jpeg(img.crop((w // 2, 0, w, h))))]
    return [("top", _jpeg(img.crop((0, 0, w, h // 2)))), ("bottom", _jpeg(img.crop((0, h // 2, w, h))))]


def _total(food):
    return sum(_best(g) for g in food["groups"])


def _read_all(jobs):
    """Run (image_bytes, prompt) model calls at the same time. Returns answers, with exceptions in place of failures."""
    def one(job):
        try:
            return llm.chat_json(SYSTEM, job[1], image_b64=base64.b64encode(job[0]).decode(), media_type="image/jpeg",
                                 max_tokens=4000, effort="high")
        except Exception as e:  # noqa: BLE001 - one failed reading shouldn't sink the others
            return e
    with ThreadPoolExecutor(max(1, len(jobs))) as ex:
        return list(ex.map(one, jobs))


def combine(readings, split_total=None):
    """Several readings of the same photo -> one answer.

    The reading with the middle total is the best estimate. If the other readings (or the two halves
    counted up close) disagree, each count's range is widened to cover them and confidence drops, so the
    business is asked to check the number. A reading far off from the rest (an outlier) doesn't stretch
    the range; it only lowers confidence. Allergens and "keep cold" are combined on the safe side: if any
    reading saw them, they count."""
    readings = sorted(readings, key=_total)
    base = dict(readings[len(readings) // 2])
    totals = [_total(r) for r in readings] + ([split_total] if split_total is not None else [])
    mid = _total(base)
    near = [t for t in totals if not mid or abs(t - mid) <= OUTLIER * mid]
    outliers = len(totals) - len(near)
    lo_t, hi_t = min(near), max(near)
    groups = [dict(g, count=_best(g)) for g in base["groups"]]
    if mid and hi_t > lo_t:
        for g in groups:
            g["count_low"] = min(g["count_low"], math.floor(g["count_low"] * lo_t / mid))
            g["count_high"] = max(g["count_high"], math.ceil(g["count_high"] * hi_t / mid))
    base["groups"] = groups
    base["servings"], base["weight_lbs"] = _amounts(groups)
    base["allergens"] = sorted({a for r in readings for a in r["allergens"]})
    base["allergens_uncertain"] = any(r["allergens_uncertain"] for r in readings)
    base["needs_cold"] = any(r["needs_cold"] for r in readings)
    spread = (hi_t - lo_t) / mid if mid else 0
    conf = base["confidence"]
    if spread > 0.1 or outliers:
        conf = "low"
    elif spread > 0:
        conf = min(conf, "medium", key=CONFIDENCE.index)
    base["confidence"] = conf
    checks = []
    if len(readings) > 1:
        checks.append(f"read {len(readings)} times: " + ", ".join(f"{t:g}" for t in totals[:len(readings)]) + " items")
    if split_total is not None:
        checks.append(f"halves counted up close: {split_total:g}")
    if checks:
        agree = "they agree" if hi_t == lo_t and not outliers else "they differ, so please check the count"
        base["notes"] = f"Counted {_counts_text(groups)}. Checked ({'; '.join(checks)}): {agree}."
    return base


MULTI_PROMPT = """This photo shows food left over at a business at closing time, to be donated.
A simple on-device detector glanced at it first and thought it saw: {hint}.
That detector only knows a few foods and is often wrong (it calls snack bags "cake"), so trust your own eyes.

Group what you see into donations, ONE PER FOOD CATEGORY (different categories have different safety rules).
Ignore anything that isn't food (cups, napkins, utensils, empty containers).
Return ONLY a JSON object:
{{"donations": [
  {{"items": ["short names, e.g. 'popcorn (2 bags)'"], "servings": integer estimate,
    "weight_lbs": [low, high],
    "allergens": ["dairy","gluten","eggs","nuts","peanuts","soy","fish","shellfish" - only likely ones; read labels if visible],
    "category": "hot prepared" | "cold prepared" | "packaged" | "produce",
    "needs_cold": true/false,
    "allergens_uncertain": true/false (true if you can't rule out allergens you can't see),
    "safe_minutes": minutes it stays safe (hot ~120, cold ~90 if it must stay cold, sealed packaged ~1440, produce ~720),
    "notes": "one short sentence about anything uncertain"}}
]}}
If there is no food at all, return {{"donations": []}}. Be conservative with servings and safety."""


def analyze_many(image_bytes, media_type="image/jpeg", hint="nothing"):
    """Closing-time snapshot -> a list of donations, one per food category. Returns (foods, source).
    source is "demo"/"fallback" when no model answered, so the caller can use its own detector instead."""
    if not llm.available():
        return [], "demo"
    image_bytes, media_type = prepare(image_bytes, media_type)
    try:
        b64 = base64.b64encode(image_bytes).decode()
        data = llm.chat_json("You are a careful food-donation intake assistant.", MULTI_PROMPT.format(hint=hint or "nothing"),
                             image_b64=b64, media_type=media_type, max_tokens=4000, effort="high")
        foods = [normalize(f, base=NEUTRAL) for f in (data.get("donations") or []) if f]
        for f in foods:
            f["notes"] = (f.get("notes") or "").strip() or "Identified by the vision model from the closing-time snapshot."
        return foods, llm.provider()
    except Exception:  # noqa: BLE001
        return [], "fallback"


def analyze(image_bytes, media_type="image/jpeg", menu_hint=""):
    if not llm.available():
        return normalize(DEMO), "demo"
    original = image_bytes
    image_bytes, media_type = prepare(image_bytes, media_type)
    if media_type not in SUPPORTED_TYPES:
        return failed(f"{media_type} photos aren't supported; use JPEG or PNG")
    prompt = PROMPT + (menu_hint or "")
    # One reading first. Only if it's unsure (or a big spread, or it failed) is the photo read again,
    # so most photos cost a single model call and the extra calls go where they can change the answer.
    answers = _read_all([(image_bytes, prompt)])
    first = answers[0]
    big = isinstance(first, dict) and _total(from_counts(first)) >= VISION_SPLIT_MIN
    sure = isinstance(first, dict) and (first.get("is_food") is False or (first.get("confidence") == "high" and not big))
    extra = [(image_bytes, prompt)] * (VISION_READS - 1) if not sure and VISION_READS > 1 else []
    # halves only for a single photo: a video arrives as a grid of frames of the same food, and cutting it would double count
    parts = halves(original) if big and VIDEO_NOTE not in (menu_hint or "") else []
    got = _read_all(extra + [(img, prompt + HALF_NOTE.format(side=side)) for side, img in parts]) if extra or parts else []
    answers += got[:len(extra)]
    half_answers = got[len(extra):]   # re-reads and the halves run at the same time
    ok = [a for a in answers if isinstance(a, dict)]
    if not ok:  # any failure becomes a clear message, never fake food
        return failed(f"the vision model call failed: {type(answers[0]).__name__}")
    not_food = [a for a in ok if a.get("is_food") is False]
    if len(not_food) * 2 > len(ok):
        return failed(f"it doesn't look like food: {not_food[0].get('notes') or 'no food found'}")
    readings = [f for f in (from_counts(a) for a in ok if a.get("is_food") is not False) if f["groups"]]
    if not readings:
        return failed("the model didn't find anything to count")
    split_total = None
    if half_answers and all(isinstance(a, dict) for a in half_answers):  # a big spread, counted up close
        split_total = sum(_total(from_counts(a)) for a in half_answers)
    return normalize(combine(readings, split_total)), llm.provider()
