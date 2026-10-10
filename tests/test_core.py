"""Core checks. Run with:  python -m pytest   (or just:  python tests/test_core.py)"""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agents  # noqa: E402
import scenarios  # noqa: E402
from world import World  # noqa: E402

PIZZA = scenarios.PIZZA
SANDWICHES = scenarios.SANDWICHES


def fresh(policy="agents"):
    return World(policy=policy, live=False)


# ---------- safety rules ----------

def test_cold_food_never_goes_to_a_place_without_a_fridge():
    w = fresh()
    d = w.add_donation(dict(SANDWICHES), "tech-cafeteria")
    plans = w.safe_plans(d)
    assert plans
    assert all(w.nonprofits[p["np"]]["has_fridge"] for p in plans)


def test_allergen_rule_blocks_shelter_that_avoids_it():
    w = fresh()
    d = w.add_donation(dict(scenarios.PB), "campus-cafe")
    assert all(p["np"] != "northside-youth" for p in w.safe_plans(d))


def test_every_safe_plan_arrives_before_food_is_unsafe_and_before_closing():
    w = fresh()
    d = w.add_donation(dict(PIZZA), "campus-cafe")
    for p in w.safe_plans(d):
        assert p["arrive"] <= d["safe_until"] - 5
        assert p["arrive"] <= w.nonprofits[p["np"]]["open_min"]


def test_capacity_counts_food_already_on_the_way():
    w = fresh()
    big = dict(PIZZA, servings=45)
    d1 = w.add_donation(dict(big), "campus-cafe")
    w.assign(d1, next(p for p in w.safe_plans(d1) if p["np"] == "northside-youth"))
    d2 = w.add_donation(dict(PIZZA), "campus-cafe")  # 12 more servings; Northside holds 50
    assert all(p["np"] != "northside-youth" for p in w.safe_plans(d2))


# ---------- negotiation ----------

def test_negotiation_reaches_a_safe_decision_with_three_agents():
    w = fresh()
    d = w.add_donation(dict(PIZZA), "campus-cafe")
    plans = w.safe_plans(d)
    result = agents.negotiate(w, d, plans)
    assert result["outcome"] in ("consensus", "majority", "urgent", "unacceptable", "irreconcilable")
    assert set(result["rounds"][0]["proposals"]) == {"Speed", "Cost", "Need"}
    ids = {p["id"] for p in plans}
    if result["plan"]:
        assert result["plan"]["id"] in ids  # never picks a plan the safety rules removed


def test_agents_genuinely_disagree_in_round_one():
    w = fresh()
    d = w.add_donation(dict(PIZZA), "campus-cafe")
    r1 = agents.negotiate(w, d, w.safe_plans(d))["rounds"][0]
    assert len(set(r1["proposals"].values())) > 1
    assert any(not v["accept"] for votes in r1["votes"].values() for v in votes.values())


def test_short_time_forces_a_decision_in_one_round():
    w = fresh()
    d = w.add_donation(dict(PIZZA, safe_minutes=25), "campus-cafe")
    plans = w.safe_plans(d)
    if plans:
        result = agents.negotiate(w, d, plans)
        assert len(result["rounds"]) == 1


# ---------- adaptation and failures ----------

def test_cancelled_driver_loses_reliability_and_food_is_replanned():
    w = fresh()
    d = w.add_donation(dict(PIZZA), "campus-cafe")
    plan = next(p for p in w.safe_plans(d) if p["driver_type"] == "volunteer")
    w.assign(d, plan)
    before = w.drivers[plan["driver"]]["reliability"]
    w.cancel_driver(plan["driver"])
    assert w.drivers[plan["driver"]]["reliability"] < before
    assert d["status"] == "new"


def test_new_pantry_is_discoverable_by_capability():
    w = fresh()
    w.add_pantry()
    d = w.add_donation(dict(SANDWICHES), "campus-cafe")
    assert any(p["np"] == "maple-pantry" for p in w.safe_plans(d))


# ---------- evidence ----------

def test_agents_beat_baseline_on_lost_food_across_scenarios():
    r = scenarios.compare()
    assert r["totals"]["agents"]["servings_lost"] <= r["totals"]["baseline"]["servings_lost"]
    assert r["totals"]["agents"]["meals_delivered_safely"] >= r["totals"]["baseline"]["meals_delivered_safely"]


def test_scenarios_are_repeatable():
    a = scenarios.run("lunch_rush", "agents").metrics()
    b = scenarios.run("lunch_rush", "agents").metrics()
    assert a == b


def test_every_scenario_finishes():
    for name in scenarios.SCENARIOS:
        assert scenarios.run(name, "agents").done(), name


# ---------- new features ----------

def test_standoff_asks_a_human_with_two_options():
    w = scenarios.run("standoff", "agents")
    assert w.impact["escalations"] >= 1
    assert any("asking a coordinator" in f["text"] and " or " in f["text"] for f in w.feed)


def test_shelter_phone_flow_ask_decline_then_accept():
    import time
    w = World(live=True)
    w.phones = {n: time.time() for n in w.nonprofits}
    d = w.add_donation(dict(PIZZA), "campus-cafe")
    w.plan(d)
    assert d["status"] == "awaiting_shelter"
    first = d["ask"]["plan"]["np"]
    assert w.respond(d["id"], False)
    assert w.nonprofits[first]["full"]
    w.plan(d)
    assert d["status"] == "awaiting_shelter" and d["ask"]["plan"]["np"] != first
    assert w.respond(d["id"], True)
    assert d["status"] == "en_route"


def test_pending_requests_hold_shelter_capacity():
    import time
    w = World(live=True)
    w.phones = {n: time.time() for n in w.nonprofits}
    d1 = w.add_donation(dict(PIZZA, servings=45), "campus-cafe")
    w.plan(d1)
    np_id = d1["ask"]["plan"]["np"]
    room = w.nonprofits[np_id]["capacity_servings"] - 45
    d2 = w.add_donation(dict(PIZZA, servings=room + 1), "campus-cafe")
    assert all(p["np"] != np_id for p in w.safe_plans(d2, log=False))


def test_agents_never_lose_more_food_than_baseline_on_random_runs():
    r = scenarios.compare_random(30, first_seed=500)
    assert r["wins"]["more_food_lost"] == 0
    assert r["totals"]["agents"]["servings_lost"] < r["totals"]["baseline"]["servings_lost"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok ", t.__name__)
    print(f"\n{len(tests)} tests passed")
