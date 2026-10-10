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


def normalize(food):
    """Make sure the shape matches what the rest of the app expects."""
    f = dict(DEMO)
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
    f["safe_minutes"] = max(10, int(float(f.get("safe_minutes", 120))))
    return f


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
