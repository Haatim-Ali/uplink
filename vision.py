"""Photo -> food details. Uses the cloud model when a key is set, otherwise a demo result."""
import base64

import llm

CATEGORIES = ["hot prepared", "cold prepared", "packaged", "produce"]

PROMPT = """Look at this photo of surplus food a business wants to donate.
Return ONLY a JSON object with these keys:
{"items": ["short names"], "servings": integer estimate,
 "weight_lbs": [low, high], "allergens": ["dairy","gluten","eggs","nuts","peanuts","soy","fish","shellfish" - only likely ones],
 "category": one of "hot prepared" | "cold prepared" | "packaged" | "produce",
 "needs_cold": true/false (must it stay refrigerated?),
 "allergens_uncertain": true/false (true if you can't rule out allergens you can't see, e.g. nuts in baked goods),
 "safe_minutes": minutes it stays safe from now (hot prepared ~120, cold prepared ~90 if needs_cold, packaged ~1440, produce ~720),
 "notes": "one short sentence about anything uncertain"}
Be conservative: if unsure, give a wider weight range and say so in notes."""

DEMO = {
    "items": ["pepperoni pizza"],
    "servings": 12,
    "weight_lbs": [3, 5],
    "allergens": ["dairy", "gluten"],
    "category": "hot prepared",
    "needs_cold": False,
    "safe_minutes": 120,
    "notes": "Demo result (no API key set). Edit anything that looks wrong.",
}


SAFE_BY_CATEGORY = {"hot prepared": 120, "cold prepared": 90, "packaged": 1440, "produce": 720}
NEUTRAL = {"items": ["food"], "servings": 1, "weight_lbs": [1, 2], "allergens": [], "category": "packaged",
           "needs_cold": False, "notes": ""}


def normalize(food, base=None):
    """Make sure the shape matches what the rest of the app expects. Missing fields come from `base`
    (the demo pizza by default, for the hand-entry form; neutral values for model results)."""
    f = dict(DEMO if base is None else base)
    if base is not None and "safe_minutes" not in food:
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
    try:
        b64 = base64.b64encode(image_bytes).decode()
        data = llm.chat_json("You are a careful food-donation intake assistant.", MULTI_PROMPT.format(hint=hint or "nothing"),
                             image_b64=b64, media_type=media_type, max_tokens=900)
        foods = [normalize(f, base=NEUTRAL) for f in (data.get("donations") or []) if f]
        for f in foods:
            f["notes"] = (f.get("notes") or "").strip() or "Identified by the vision model from the closing-time snapshot."
        return foods, llm.provider()
    except Exception:  # noqa: BLE001
        return [], "fallback"


def analyze(image_bytes, media_type="image/jpeg"):
    if not llm.available():
        return normalize(DEMO), "demo"
    try:
        b64 = base64.b64encode(image_bytes).decode()
        data = llm.chat_json("You are a careful food-donation intake assistant.", PROMPT, image_b64=b64,
                             media_type=media_type, max_tokens=500)
        return normalize(data), llm.provider()
    except Exception as e:  # noqa: BLE001
        d = dict(DEMO)
        d["notes"] = f"Vision call failed ({type(e).__name__}); showing demo values. Edit before confirming."
        return normalize(d), "fallback"
