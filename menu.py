"""Each business's menu: pick leftovers from it instead of describing them, and help the photo reader.

- items(biz)               -> the menu, including anything the business added
- add(biz, item)           -> add an item that wasn't on the menu (kept in data/menu_additions.json, not in git)
- foods_from_lines(biz, lines) -> donations ready for /api/donate, one per food category
- hint(biz)                -> the menu as text for the vision prompt
- enrich(food, biz)        -> after a photo read: match items to the menu and take its allergens and category
"""
import json
import os
import re
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "data", "menus.json")
EXTRA = os.path.join(HERE, "data", "menu_additions.json")
CATEGORIES = ["hot prepared", "cold prepared", "packaged", "produce"]
SAFE_MINUTES = {"hot prepared": 120, "cold prepared": 90, "packaged": 1440, "produce": 720}
_lock = threading.Lock()


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def items(biz):
    return _load(BASE).get(biz, []) + _load(EXTRA).get(biz, [])


def find(biz, item_id):
    return next((m for m in items(biz) if m["id"] == item_id), None)


def add(biz, item):
    """Add a leftover that isn't on the menu yet. Returns the saved item, or raises ValueError."""
    name = re.sub(r"\s+", " ", str(item.get("name", ""))).strip()[:60]
    if not name:
        raise ValueError("Give the item a name.")
    cat = item.get("category") if item.get("category") in CATEGORIES else "hot prepared"
    serves = max(1, min(200, int(float(item.get("serves") or 1))))
    alg = [a.strip().lower() for a in (item.get("allergens") or []) if str(a).strip()][:8]
    with _lock:
        extra = _load(EXTRA)
        mine = extra.setdefault(biz, [])
        existing = next((m for m in items(biz) if m["name"].lower() == name.lower()), None)
        if existing:
            return existing
        new = {"id": f"{biz}-x{len(mine) + 1}", "name": name, "unit": str(item.get("unit") or "item")[:20],
               "serves": serves, "lbs": round(0.5 * serves, 1), "category": cat, "allergens": alg,
               "cold": bool(item.get("cold")) or cat == "cold prepared", "added": True}
        mine.append(new)
        with open(EXTRA, "w", encoding="utf-8") as f:
            json.dump(extra, f, indent=1)
    return new


def foods_from_lines(biz, lines):
    """[{"id": item id, "qty": n}] -> list of donation foods, one per (category, must stay cold)."""
    groups = {}
    for ln in lines or []:
        m = find(biz, ln.get("id"))
        qty = int(float(ln.get("qty") or 0))
        if not m or qty <= 0:
            continue
        key = (m["category"], bool(m.get("cold")))
        g = groups.setdefault(key, {"items": [], "servings": 0, "lbs": 0.0, "allergens": set()})
        g["items"].append(f"{m['name']} ×{qty}" if qty > 1 else m["name"])
        g["servings"] += qty * int(m.get("serves", 1))
        g["lbs"] += qty * float(m.get("lbs", 0.5))
        g["allergens"].update(m.get("allergens", []))
    out = []
    for (cat, cold), g in groups.items():
        lbs = max(0.5, round(g["lbs"], 1))
        out.append({"items": g["items"], "servings": g["servings"], "weight_lbs": [round(lbs * .9, 1), round(lbs * 1.1, 1)],
                    "category": cat, "needs_cold": cold, "allergens": sorted(g["allergens"]),
                    "safe_minutes": SAFE_MINUTES[cat], "allergens_unverified": False,
                    "notes": "Picked from the business's menu, so the allergens come from its recipes."})
    return out


def hint(biz):
    ms = items(biz)
    if not ms:
        return ""
    lines = "\n".join(f"- {m['name']} (unit: {m['unit']})" for m in ms)
    return ("\n\nThis business's menu. When something in the photo matches a menu item, use the menu's exact "
            f"name for it. Food that isn't on the menu is fine, just name it plainly.\n{lines}")


def _norm(s):
    return re.sub(r"[^a-z ]", "", s.lower()).replace("es ", " ").replace("s ", " ").strip()


def enrich(food, biz):
    """After a photo read: items that match the menu take the menu's allergens and category.
    Returns the food with "menu_matches" (how many items matched)."""
    ms = items(biz)
    if not ms or not food:
        return food
    hits = []
    for name in food.get("items", []):
        base = _norm(re.sub(r"\s*[x×(].*$", "", name) + " ")
        m = next((m for m in ms if _norm(m["name"] + " ") in base or base in _norm(m["name"] + " ")), None)
        if m:
            hits.append(m)
    if hits:
        food["allergens"] = sorted(set(food.get("allergens", [])) | {a for m in hits for a in m.get("allergens", [])})
        cats = [m["category"] for m in hits]
        food["category"] = max(set(cats), key=cats.count)
        food["needs_cold"] = food.get("needs_cold") or any(m.get("cold") for m in hits)
        if len(hits) == len(food.get("items", [])):
            food["allergens_unverified"] = False   # every item is on the menu: its recipes are known
    food["menu_matches"] = len(hits)
    return food
