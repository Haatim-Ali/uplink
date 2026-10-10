"""Scripted, repeatable scenarios. The same events run against both policies."""
import copy

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

PRODUCE = {"items": ["mixed produce crates"], "servings": 120, "weight_lbs": [60, 80], "allergens": [],
           "category": "produce", "needs_cold": False, "safe_minutes": 720}

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
    "standoff": {
        "name": "standoff", "title": "Standoff: every safe option is expensive, so the agents ask a coordinator",
        "events": [
            {"at": 0, "type": "cancel", "driver": "maria"},
            {"at": 0, "type": "cancel", "driver": "jordan"},
            {"at": 0, "type": "cancel", "driver": "sam"},
            {"at": 1, "type": "donation", "business": "north-market", "food": PRODUCE},
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


# ---------------- randomized evidence ----------------

FOODS = [PIZZA, SANDWICHES, GRANOLA, CURRY, PASTA, SALADS, YOGURT, SOUP, PB, PRODUCE]
BUSINESSES = ["campus-cafe", "tech-cafeteria", "corner-bakery", "lakeside-hotel", "north-market"]
DRIVERS = ["maria", "jordan", "sam", "courier-a", "courier-b"]
SHELTERS = ["harbor-house", "eastside-pantry", "grace-kitchen", "northside-youth", "valley-food-bank"]


def random_scenario(seed):
    """A seeded random lunch rush: 3-6 donations, a couple of no-shows, maybe a full shelter or a new pantry."""
    import random
    rng = random.Random(seed)
    events = []
    for _ in range(rng.randint(3, 6)):
        f = dict(rng.choice(FOODS))
        f["servings"] = max(5, int(f["servings"] * rng.uniform(0.6, 1.4)))
        f["safe_minutes"] = max(30, int(f["safe_minutes"] * rng.uniform(0.6, 1.1)))
        events.append({"at": rng.randint(0, 20), "type": "donation", "business": rng.choice(BUSINESSES), "food": f})
    for drv in rng.sample(DRIVERS, rng.randint(0, 2)):
        events.append({"at": rng.randint(1, 25), "type": "cancel", "driver": drv})
    if rng.random() < 0.6:
        events.append({"at": rng.randint(2, 25), "type": "decline", "nonprofit": rng.choice(SHELTERS)})
    if rng.random() < 0.3:
        events.append({"at": rng.randint(2, 25), "type": "new_pantry"})
    return {"name": f"random-{seed}", "title": f"Random lunch rush #{seed}", "events": events}


def run_scenario(sc, policy, max_minutes=900):
    from world import World
    w = World(copy.deepcopy(sc), policy=policy, live=False)
    for _ in range(max_minutes):
        w.tick()
        if w.done():
            break
    return w.metrics()


def compare_random(n=50, first_seed=1):
    """Run the same n random scenarios through both policies. Returns totals, per-run results and win counts."""
    runs = []
    for seed in range(first_seed, first_seed + n):
        sc = random_scenario(seed)
        runs.append({"seed": seed, "baseline": run_scenario(sc, "baseline"), "agents": run_scenario(sc, "agents")})
    keys = runs[0]["agents"].keys()
    totals = {p: {k: round(sum(r[p][k] for r in runs), 2) for k in keys} for p in ("baseline", "agents")}
    lost = [(r["agents"]["servings_lost"], r["baseline"]["servings_lost"]) for r in runs]
    wins = {
        "less_food_lost": sum(a < b for a, b in lost),
        "same_food_lost": sum(a == b for a, b in lost),
        "more_food_lost": sum(a > b for a, b in lost),
    }
    return {"n": n, "totals": totals, "wins": wins, "runs": runs}
