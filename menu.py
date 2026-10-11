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


# ---------- spoken donations: "we've got twenty turkey sandwiches and two pizzas" ----------

_STOP = {"of", "the", "a", "an", "and", "with", "in", "on", "for", "fresh", "plain", "mixed", "whole", "mini", "1", "gallon"}
_UNITWORDS = {"tray", "trays", "pan", "pans", "box", "boxes", "bag", "bags", "half", "case", "cases", "crate", "crates",
              "dozen", "loaf", "loaves", "bunch", "bunches", "cup", "cups", "carton", "cartons", "container", "containers"}


def _sing(w):
    """Crude singular, applied the same way to the menu and to what was said."""
    w = w.lower().strip(".,!?'\"")
    w = {"loaves": "loaf", "halves": "half", "dozens": "dozen"}.get(w, w)
    if len(w) > 4 and w.endswith(("ches", "shes", "sses", "xes", "oes")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


_BREAK = {"and", "plus", "also", "with", "then", "some", "few", "couple"}


def _qty_before(words, heads, i):
    """The amount said just before word i, without crossing into the previous item ("3 bananas and some salads")."""
    import voice   # number words ("twenty five") live with the voice code
    span = []
    for j in range(i - 1, max(-1, i - 6), -1):
        w = words[j]
        if w in _BREAK or _sing(w) in heads:
            break
        span.insert(0, w)
    t = " ".join(span)
    nums = [n for n in voice._numbers(t.replace("dozen", "")) if n > 0]
    q = nums[-1] if nums else (1 if "dozen" not in t else 0)
    if "dozen" in t:
        q = (q or 1) * 12
    return q or 1


def parse_speech_rules(biz, text):
    """No AI: find menu items named in the sentence and the amount said just before each one."""
    words = [w for w in re.split(r"[\s,.;!?]+", text.lower()) if w]
    sing = [_sing(w) for w in words]
    ms = items(biz)
    # "Chicken curry with rice" is a curry: the food is named before "with"
    name_words = {m["id"]: [_sing(w) for w in re.findall(r"[a-z]+", re.split(r"\bwith\b|,", m["name"].lower())[0]) if w not in _STOP] for m in ms}
    heads = {ws[-1] for ws in name_words.values() if ws}
    lines, used = [], set()
    for m in ms:
        keys = name_words[m["id"]]
        if not keys:
            continue
        head = keys[-1]   # "turkey sandwich" -> "sandwich": the last word names the food
        # skip a word used as a modifier of another food ("vegetable" in "vegetable lasagna")
        hits = [i for i, w in enumerate(sing) if w == head and i not in used and not (i + 1 < len(sing) and sing[i + 1] in heads)]
        if not hits:
            continue
        near = lambda i: sum(k in sing[max(0, i - 4):i] for k in keys[:-1])
        best = max(hits, key=near)
        same_head = [o for o in ms if name_words[o["id"]] and name_words[o["id"]][-1] == head]
        if len(same_head) > 1 and len(keys) > 1 and not near(best):
            continue   # "sandwich" with two sandwiches on the menu: let the person pick
        used.add(best)
        lines.append({"id": m["id"], "name": m["name"], "qty": max(1, min(500, _qty_before(words, heads, best))), "serves": m["serves"]})
    return lines


def parse_speech(biz, text):
    """Spoken leftovers -> menu lines. Claude when a key is set (handles 'a couple', 'half a tray', items not
    on the menu); the word-matching rules otherwise. Returns (lines, extras, source)."""
    import llm
    ms = items(biz)
    if llm.available() and ms:
        try:
            menu_txt = "\n".join(f'{m["id"]}: {m["name"]} (unit: {m["unit"]})' for m in ms)
            out = llm.chat_json(
                "You turn what a restaurant worker says about leftover food into an order against their menu. "
                "Reply with JSON only.",
                f"Menu (id: name):\n{menu_txt}\n\nThey said: \"{text}\"\n\n"
                'Return {"lines": [{"id": "<menu id>", "qty": <number of units>}], '
                '"extras": [{"name": "<food not on the menu>", "qty": <number>}]}. '
                "Count in the menu's units. Only use ids from the menu. Leave out anything that isn't food.",
                max_tokens=800, effort="low", model=llm.agent_model())
            by_id = {m["id"]: m for m in ms}
            lines = [{"id": ln["id"], "name": by_id[ln["id"]]["name"], "qty": max(1, int(float(ln.get("qty") or 1))),
                      "serves": by_id[ln["id"]]["serves"]} for ln in out.get("lines", []) if ln.get("id") in by_id]
            extras = [{"name": str(e.get("name", ""))[:60], "qty": max(1, int(float(e.get("qty") or 1)))}
                      for e in out.get("extras", []) if e.get("name")]
            if lines or extras:
                return lines, extras, llm.provider()
        except Exception:  # noqa: BLE001 - fall back to the rules
            pass
    return parse_speech_rules(biz, text), [], "rules"
