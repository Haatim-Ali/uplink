"""Photo -> food details.

The model only does what it's good at: name the food and count the units it can see.
Servings, weight and safe time are computed here in code from a small lookup table, so
the same count always gives the same numbers. If no model is connected the result is a
clearly labeled demo; if the model call fails the result is an empty form with the
reason, never a made-up guess.
"""
import base64
import io

import llm

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


def from_counts(data):
    """Turn the model's counted groups into servings, weight and safe time, in code."""
    groups, servings, lo_lbs, hi_lbs = [], 0.0, 0.0, 0.0
    for g in data.get("groups") or []:
        lo = max(0, int(float(g.get("count_low", g.get("count", 0)) or 0)))
        hi = max(lo, int(float(g.get("count_high", lo) or lo)))
        unit = _unit(g.get("unit"))
        per_serving, per_lb = UNITS[unit]
        servings += (lo + hi) / 2 * per_serving
        lo_lbs += lo * per_lb
        hi_lbs += hi * per_lb
        groups.append({"name": str(g.get("name") or unit), "unit": unit, "count_low": lo, "count_high": hi,
                       "how_counted": str(g.get("how_counted") or "")})
    category = data.get("category") if data.get("category") in CATEGORIES else "hot prepared"
    counts = "; ".join(f"{g['name']}: {g['count_low']}" + (f"-{g['count_high']}" if g["count_high"] != g["count_low"] else "")
                       + f" {g['unit']}" + (f" ({g['how_counted']})" if g["how_counted"] else "") for g in groups)
    notes = " ".join(x for x in [f"Counted {counts}." if counts else "", str(data.get("notes") or "")] if x)
    return {
        "items": [g["name"] for g in groups] or ["food"],
        "servings": max(1, round(servings)),
        "weight_lbs": [round(max(lo_lbs, 0.5), 1), round(max(hi_lbs, lo_lbs, 0.5), 1)],
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


def prepare(image_bytes, media_type):
    """Fix rotation, shrink to MAX_EDGE and re-encode as JPEG. Returns (bytes, media_type)."""
    if Image is None:
        return image_bytes, media_type
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert("RGB")
    except Exception:  # noqa: BLE001 - unreadable here; let the type check below decide
        return image_bytes, media_type
    img.thumbnail((MAX_EDGE, MAX_EDGE))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=90)
    return out.getvalue(), "image/jpeg"


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
    image_bytes, media_type = prepare(image_bytes, media_type)
    if media_type not in SUPPORTED_TYPES:
        return failed(f"{media_type} photos aren't supported; use JPEG or PNG")
    try:
        b64 = base64.b64encode(image_bytes).decode()
        data = llm.chat_json("You are a careful food-donation intake assistant. You count, you don't guess.",
                             PROMPT + (menu_hint or ""), image_b64=b64, media_type=media_type, max_tokens=4000, effort="high")
    except Exception as e:  # noqa: BLE001 - any failure becomes a clear message, never fake food
        return failed(f"the vision model call failed: {type(e).__name__}")
    if data.get("is_food") is False:
        return failed(f"it doesn't look like food: {data.get('notes') or 'no food found'}")
    food = from_counts(data)
    if not food["groups"]:
        return failed("the model didn't find anything to count")
    return normalize(food), llm.provider()
