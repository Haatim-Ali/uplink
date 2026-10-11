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
SALADS_SHORT = dict(SALADS, safe_minutes=35)
CHILI = {"items": ["homemade chili", "cornbread"], "servings": 30, "weight_lbs": [12, 15], "allergens": ["gluten"],
         "category": "hot prepared", "needs_cold": False, "safe_minutes": 120, "allergens_unverified": True}
PAD_THAI = {"items": ["pad thai"], "servings": 20, "weight_lbs": [8, 10], "allergens": ["soy", "eggs"],
            "category": "hot prepared", "needs_cold": False, "safe_minutes": 90, "allergens_unverified": True}

PRODUCE = {"items": ["mixed produce crates"], "servings": 120, "weight_lbs": [60, 80], "allergens": [],
           "category": "produce", "needs_cold": False, "safe_minutes": 720}

RICE_BOWLS = {"items": ["teriyaki rice bowls"], "servings": 18, "weight_lbs": [8, 11], "allergens": ["soy", "gluten"],
              "category": "hot prepared", "needs_cold": False, "safe_minutes": 100}
TACOS = {"items": ["chicken tacos"], "servings": 22, "weight_lbs": [7, 9], "allergens": ["dairy"],
         "category": "hot prepared", "needs_cold": False, "safe_minutes": 90}
DUMPLINGS = {"items": ["vegetable dumplings"], "servings": 15, "weight_lbs": [4, 6], "allergens": ["gluten", "soy"],
             "category": "hot prepared", "needs_cold": False, "safe_minutes": 90}
BREAD = {"items": ["day-old bread"], "servings": 40, "weight_lbs": [10, 14], "allergens": ["gluten"],
         "category": "packaged", "needs_cold": False, "safe_minutes": 2880}
MILK = {"items": ["milk cartons"], "servings": 36, "weight_lbs": [20, 24], "allergens": ["dairy"],
        "category": "cold prepared", "needs_cold": True, "safe_minutes": 150}

CITY_DRIVERS = [
    {"id": "priya", "name": "Priya (volunteer)", "type": "volunteer", "reliability": 0.9, "lat": 37.3601, "lng": -121.9452, "base_usd": 0, "per_km_usd": 0},
    {"id": "luis", "name": "Luis (volunteer)", "type": "volunteer", "reliability": 0.75, "lat": 37.3452, "lng": -121.9702, "base_usd": 0, "per_km_usd": 0},
    {"id": "kim", "name": "Kim (volunteer)", "type": "volunteer", "reliability": 0.85, "lat": 37.3952, "lng": -121.9402, "base_usd": 0, "per_km_usd": 0},
    {"id": "courier-c", "name": "Rapid Courier C (paid)", "type": "paid", "reliability": 0.95, "lat": 37.3402, "lng": -121.9602, "base_usd": 6, "per_km_usd": 1.4},
]


def _d(at, business, food, **change):
    return {"at": at, "type": "donation", "business": business, "food": dict(food, **change)}


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
    "city_rush": {
        "name": "city_rush", "title": "City mode: 18 donations across Santa Clara in 45 minutes",
        "events": [{"at": 0, "type": "driver_joins", "driver": d} for d in CITY_DRIVERS] + [
            _d(1, "campus-cafe", PIZZA),
            _d(2, "food-hall", RICE_BOWLS),
            _d(3, "food-hall", TACOS),
            _d(4, "food-hall", DUMPLINGS),
            _d(5, "tech-cafeteria", SANDWICHES, servings=30),
            _d(6, "grocer", BREAD),
            _d(8, "campus-dining", PASTA, servings=20),
            _d(9, "campus-dining", SALADS, servings=16),
            {"at": 10, "type": "cancel", "driver": "maria"},
            _d(11, "lakeside-hotel", CURRY, servings=20, safe_minutes=60),
            _d(13, "caterer", SOUP),
            _d(14, "grocer", MILK),
            {"at": 15, "type": "decline", "nonprofit": "harbor-house"},
            _d(17, "corner-bakery", GRANOLA, servings=40),
            _d(19, "food-hall", PIZZA, items=["margherita pizza"]),
            _d(21, "caterer", YOGURT, servings=20),
            {"at": 22, "type": "new_pantry"},
            _d(24, "campus-cafe", PB, servings=18),
            _d(28, "north-market", PRODUCE, servings=60),
            {"at": 30, "type": "cancel", "driver": "luis"},
            _d(33, "tech-cafeteria", SALADS, servings=14),
            _d(40, "lakeside-hotel", RICE_BOWLS, servings=20),
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
    "majority_dissent": {
        "name": "majority_dissent", "title": "Majority with dissent: Cost is outvoted on a paid courier; its objection stays on record",
        "setup": {
            "start": "18:00",
            "note": "18:00. Evening surge pricing on couriers. Sam is the only volunteer left, across town.",
            "drivers_off": ["courier-b", "maria", "jordan", "grace-van"],
            "drivers": {"courier-a": {"base_usd": 10}, "sam": {"reliability": 0.5, "lat": 37.3405, "lng": -121.9301, "max_km": 15}},
        },
        "events": [
            {"at": 0, "type": "donation", "business": "lakeside-hotel", "food": PASTA},
        ],
    },
    "unacceptable_compromise": {
        "name": "unacceptable_compromise", "title": "Unacceptable compromise: the majority's plan crosses an agent's red line",
        "setup": {
            "start": "19:30",
            "note": "19:30. Couriers are offline and most volunteers have gone home. Grace Kitchen got food this morning.",
            "drivers_off": ["courier-a", "courier-b", "maria", "jordan"],
            "drivers": {"sam": {"reliability": 0.45}},
            "nonprofits": {"grace-kitchen": {"last_donation_days": 0}},
        },
        "events": [
            {"at": 0, "type": "donation", "business": "lakeside-hotel", "food": PASTA},
            {"at": 3, "type": "cancel", "driver": "sam"},
        ],
    },
    "irreconcilable": {
        "name": "irreconcilable", "title": "Irreconcilable goals: no plan wins a majority, so a human decides",
        "setup": {
            "start": "16:00",
            "note": "16:00. Surge pricing on couriers. One courier and one volunteer (Jordan, across town) available. "
                    "Valley Food Bank hasn't had fresh food in 6 days; Northside is full.",
            "drivers_off": ["courier-b", "maria", "sam", "grace-van"],
            "drivers": {"courier-a": {"base_usd": 8}, "jordan": {"lat": 37.3405, "lng": -121.9301}},
            "nonprofits": {"valley-food-bank": {"last_donation_days": 6}, "grace-kitchen": {"last_donation_days": 0},
                           "northside-youth": {"full": True}},
        },
        "events": [
            {"at": 0, "type": "donation", "business": "lakeside-hotel", "food": SALADS_SHORT},
        ],
    },
    "insufficient_evidence": {
        "name": "insufficient_evidence", "title": "Insufficient evidence: agents ask the business instead of guessing",
        "events": [
            {"at": 0, "type": "donation", "business": "corner-bakery", "food": CHILI},
            {"at": 2, "type": "donation", "business": "campus-cafe", "food": PAD_THAI},
            {"at": 9, "type": "confirm", "business": "corner-bakery", "allergens": ["gluten"]},
        ],
    },
}


POLICIES = {
    "baseline": "Nearest shelter",
    "solo:Speed": "Speed alone",
    "solo:Cost": "Cost alone",
    "solo:Need": "Need alone",
    "agents": "Agents together",
}
METRICS = [("meals_delivered_safely", "Meals delivered safely"), ("servings_lost", "Servings lost"),
           ("money_spent", "Money spent ($)"), ("shelters_fed", "Shelters fed"),
           ("avg_spare_minutes", "Avg minutes to spare (perishable food)"), ("human_escalations", "Asked a human")]


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
    """Run every scenario under every policy. Same events, same safety rules (except the nearest-shelter
    baseline, which has none). The single-agent policies answer: is the team better than any one agent?"""
    rows = []
    for name, sc in SCENARIOS.items():
        res = {}
        for pol in POLICIES:
            m = run(name, pol).metrics()
            m["avg_spare_minutes"] = round(m["spare_minutes"] / m["deliveries"]) if m["deliveries"] else 0
            res[pol] = m
        rows.append({"scenario": name, "title": sc["title"], "results": res})
    totals = {}
    for pol in POLICIES:
        totals[pol] = {k: round(sum(r["results"][pol][k] for r in rows), 2) for k, _ in METRICS}
        n = sum(r["results"][pol]["deliveries"] for r in rows)
        totals[pol]["avg_spare_minutes"] = round(sum(r["results"][pol]["spare_minutes"] for r in rows) / n) if n else 0
        outcomes = {}
        for r in rows:
            for k, v in r["results"][pol]["outcomes"].items():
                outcomes[k] = outcomes.get(k, 0) + v
        totals[pol]["outcomes"] = outcomes
    return {"policies": POLICIES, "order": list(POLICIES), "metrics": dict(METRICS), "rows": rows, "totals": totals}


def markdown(c):
    head = "| Metric | " + " | ".join(c["policies"].values()) + " |\n|---" + "|---:" * len(c["policies"]) + "|\n"
    body = "".join(f"| {label} | " + " | ".join(str(c["totals"][p][k]) for p in c["policies"]) + " |\n"
                   for k, label in c["metrics"].items())
    out = head + body + "\n**How the team's negotiations ended:** " + ", ".join(
        f"{k.replace('_', ' ')} {v}" for k, v in sorted(c["totals"]["agents"]["outcomes"].items(), key=lambda x: -x[1])) + "\n"
    for r in c["rows"]:
        out += f"\n**{r['title']}**\n\n" + "| Metric | " + " | ".join(c["policies"].values()) + " |\n|---" + "|---:" * len(c["policies"]) + "|\n"
        out += "".join(f"| {label} | " + " | ".join(str(r["results"][p][k]) for p in c["policies"]) + " |\n"
                       for k, label in c["metrics"].items())
        oc = r["results"]["agents"]["outcomes"]
        out += "\nTeam outcomes: " + (", ".join(f"{k.replace('_', ' ')} {v}" for k, v in oc.items()) or "none") + "\n"
    return out


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
    keys = [k for k, v in runs[0]["agents"].items() if isinstance(v, (int, float))]
    totals = {p: {k: round(sum(r[p][k] for r in runs), 2) for k in keys} for p in ("baseline", "agents")}
    lost = [(r["agents"]["servings_lost"], r["baseline"]["servings_lost"]) for r in runs]
    wins = {
        "less_food_lost": sum(a < b for a, b in lost),
        "same_food_lost": sum(a == b for a, b in lost),
        "more_food_lost": sum(a > b for a, b in lost),
    }
    return {"n": n, "totals": totals, "wins": wins, "runs": runs}


if __name__ == "__main__":
    import json
    import sys
    c = compare()
    print(json.dumps(c, indent=1) if "--json" in sys.argv else markdown(c))
