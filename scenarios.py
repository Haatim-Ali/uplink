"""Scripted, repeatable scenarios. The same events run against both policies."""

PIZZA = {"items": ["pepperoni pizza"], "servings": 12, "weight_lbs": [3, 5], "allergens": ["dairy", "gluten"],
         "category": "hot prepared", "needs_cold": False, "safe_minutes": 120}
SANDWICHES = {"items": ["turkey sandwiches"], "servings": 40, "weight_lbs": [12, 16], "allergens": ["gluten"],
              "category": "cold prepared", "needs_cold": True, "safe_minutes": 90}
GRANOLA = {"items": ["granola bars"], "servings": 60, "weight_lbs": [6, 8], "allergens": ["nuts", "gluten"],
           "category": "packaged", "needs_cold": False, "safe_minutes": 1440}
CURRY = {"items": ["chicken curry", "rice"], "servings": 30, "weight_lbs": [14, 18], "allergens": [],
         "category": "hot prepared", "needs_cold": False, "safe_minutes": 45}
PASTA = {"items": ["pasta trays"], "servings": 25, "weight_lbs": [10, 14], "allergens": ["gluten", "dairy"],
         "category": "hot prepared", "needs_cold": False, "safe_minutes": 60}
SALADS = {"items": ["garden salads"], "servings": 20, "weight_lbs": [6, 9], "allergens": [],
          "category": "cold prepared", "needs_cold": True, "safe_minutes": 75}
YOGURT = {"items": ["yogurt parfaits"], "servings": 30, "weight_lbs": [8, 10], "allergens": ["dairy", "nuts"],
          "category": "cold prepared", "needs_cold": True, "safe_minutes": 90}
SOUP = {"items": ["vegetable soup"], "servings": 20, "weight_lbs": [10, 12], "allergens": [],
        "category": "hot prepared", "needs_cold": False, "safe_minutes": 50}
PB = {"items": ["peanut butter sandwiches"], "servings": 24, "weight_lbs": [6, 8], "allergens": ["peanuts", "gluten"],
      "category": "cold prepared", "needs_cold": True, "safe_minutes": 120}

SCENARIOS = {
    "lunch_rush": {
        "name": "lunch_rush", "title": "Lunch rush: four donations, a full shelter and a no-show",
        "events": [
            {"at": 0, "type": "donation", "business": "campus-cafe", "food": PIZZA},
            {"at": 1, "type": "donation", "business": "tech-cafeteria", "food": SANDWICHES},
            {"at": 2, "type": "donation", "business": "corner-bakery", "food": GRANOLA},
            {"at": 3, "type": "cancel", "driver": "maria"},
            {"at": 4, "type": "donation", "business": "lakeside-hotel", "food": CURRY},
            {"at": 6, "type": "decline", "nonprofit": "harbor-house"},
        ],
    },
    "volunteer_no_show": {
        "name": "volunteer_no_show", "title": "Volunteer no-show: two volunteers cancel on short-lived hot food",
        "events": [
            {"at": 0, "type": "donation", "business": "lakeside-hotel", "food": PASTA},
            {"at": 1, "type": "donation", "business": "tech-cafeteria", "food": SALADS},
            {"at": 2, "type": "cancel", "driver": "sam"},
            {"at": 3, "type": "cancel", "driver": "maria"},
            {"at": 5, "type": "donation", "business": "campus-cafe", "food": PB},
        ],
    },
    "new_pantry": {
        "name": "new_pantry", "title": "New information: a pantry joins the directory mid-run",
        "events": [
            {"at": 0, "type": "donation", "business": "corner-bakery", "food": YOGURT},
            {"at": 2, "type": "donation", "business": "campus-cafe", "food": SOUP},
            {"at": 3, "type": "new_pantry"},
            {"at": 4, "type": "decline", "nonprofit": "grace-kitchen"},
        ],
    },
}


def run(name, policy, max_minutes=600):
    import copy
    from world import World
    w = World(copy.deepcopy(SCENARIOS[name]), policy=policy, live=False)
    for _ in range(max_minutes):
        w.tick()
        if w.done():
            break
    return w


def compare():
    rows = []
    for name, sc in SCENARIOS.items():
        b, a = run(name, "baseline"), run(name, "agents")
        rows.append({"scenario": name, "title": sc["title"], "baseline": b.metrics(), "agents": a.metrics()})
    totals = {}
    for pol in ("baseline", "agents"):
        totals[pol] = {k: round(sum(r[pol][k] for r in rows), 2) for k in rows[0][pol]}
    return {"rows": rows, "totals": totals}


if __name__ == "__main__":
    import json
    print(json.dumps(compare(), indent=1))
