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
    d2 = w.add_donation(dict(PIZZA), "campus-cafe")  # 12 more servings; Northside holds 50, so 5 left
    north = [p for p in w.safe_plans(d2) if p["np"] == "northside-youth"]
    assert north and all(p["partial"] and p["servings"] == 5 for p in north)  # its agent counter-offers


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
    d2 = w.add_donation(dict(PIZZA, servings=room + 10), "campus-cafe")
    # the pending 45 count against that shelter's room: it can only counter-offer what's left
    assert all(p["servings"] <= room for p in w.safe_plans(d2, log=False) if p["np"] == np_id)


def test_agents_never_lose_more_food_than_baseline_on_random_runs():
    r = scenarios.compare_random(30, first_seed=500)
    assert r["wins"]["more_food_lost"] == 0
    assert r["totals"]["agents"]["servings_lost"] < r["totals"]["baseline"]["servings_lost"]


def test_city_mode_combines_trips_and_beats_baseline():
    a, b = scenarios.run("city_rush", "agents"), scenarios.run("city_rush", "baseline")
    assert len(a.donations) == 18 and a.done()
    assert any("rides along" in f["text"] for f in a.feed)
    assert a.metrics()["servings_lost"] <= b.metrics()["servings_lost"]


def test_combined_trip_respects_safety_and_vehicle_room():
    w = fresh()
    d1 = w.add_donation(dict(PIZZA), "campus-cafe")
    w.assign(d1, next(p for p in w.safe_plans(d1) if p["driver_type"] == "paid"))
    d2 = w.add_donation(dict(SANDWICHES), "campus-cafe")   # cold food: only joins if that shelter has a fridge
    for p in w.safe_plans(d2, log=False):
        if p.get("join"):
            assert w.nonprofits[p["np"]]["has_fridge"]
    huge = w.add_donation(dict(PIZZA, servings=200), "campus-cafe")
    assert not any(p.get("join") for p in w.safe_plans(huge, log=False))


# ---------- agent network ----------

def test_shelter_agents_accept_counter_and_decline():
    import network
    w = fresh()
    d = w.add_donation(dict(PIZZA, servings=30), "campus-cafe")
    n = w.nonprofits["northside-youth"]
    assert network.shelter_offer(w, n, d)["kind"] == "accept"
    n["received"] = 40   # 10 servings of room left
    o = network.shelter_offer(w, n, d)
    assert o["kind"] == "counter" and o["servings"] == 10
    n["received"] = 48
    assert network.shelter_offer(w, n, d)["kind"] == "decline"


def test_category_limit_shapes_the_offer():
    import network
    w = fresh()
    d = w.add_donation(dict(PIZZA, servings=50), "campus-cafe")   # Harbor House serves at most 40 hot meals a day
    o = network.shelter_offer(w, w.nonprofits["harbor-house"], d)
    assert o["kind"] == "counter" and o["servings"] == 40


def test_driver_refuses_trips_beyond_its_range():
    w = fresh()
    d = w.add_donation(dict(scenarios.PRODUCE), "north-market")    # far from Sam, who drives at most 6 km
    assert not any(p["driver"] == "sam" and p["km"] > 6 for p in w.safe_plans(d))


def test_counter_offer_splits_the_donation_and_nothing_is_lost():
    w = fresh()
    w.nonprofits["northside-youth"]["received"] = 40
    d = w.add_donation(dict(PIZZA, servings=30), "campus-cafe")
    partial = next(p for p in w.safe_plans(d) if p["np"] == "northside-youth")
    w.dispatch(d, partial)
    rest = w.get(d["id"] + "-2")
    assert d["food"]["servings"] == 10 and rest and rest["food"]["servings"] == 20
    assert "northside-youth" in rest["skip"]


def test_network_messages_are_logged():
    w = fresh()
    d = w.add_donation(dict(PIZZA), "campus-cafe")
    w.plan(d)
    kinds = {m["kind"] for m in w.network if m["donation"] == d["id"]}
    assert {"announce", "bid", "award"} <= kinds and kinds & {"accept", "counter"}


def test_camera_counts_become_safe_separate_donations():
    import camera
    assert camera.stable_counts([{"pizza": 2}, {"pizza": 2, "sandwich": 1}, {"pizza": 2}])["pizza"] == 2
    foods = {f["category"]: f for f in camera.donations_from_counts({"pizza": 2, "sandwich": 3, "apple": 0})}
    assert set(foods) == {"hot prepared", "cold prepared"}          # different safety rules, separate donations
    assert foods["cold prepared"]["needs_cold"] and foods["hot prepared"]["servings"] == 8


class _Box:
    def __init__(self, cls, conf):
        self.cls, self.conf, self.xyxy = cls, conf, [[0, 0, 10, 10]]


class _FakeModel:
    """Stands in for the detector: 'cake' at 45% (a snack bag false alarm) and a pizza at 80%."""
    def predict(self, frame, conf, verbose):
        class R:
            names = {0: "cake", 1: "pizza", 2: "person"}
            boxes = [_Box(0, 0.45), _Box(1, 0.8), _Box(2, 0.9)]
        return [R()]


def test_camera_ignores_low_confidence_false_alarms_and_non_food():
    import camera
    counts, boxes = camera.detect(_FakeModel(), None, 0.3)
    assert dict(counts) == {"pizza": 1}          # cake needs 60%; people aren't food


def test_camera_prefers_the_vision_model_and_falls_back_to_counts():
    import camera
    up = camera.Uplink.__new__(camera.Uplink)
    up.server, up.business = "http://x", "campus-cafe"
    sent = []

    class Resp:
        def __init__(self, data): self.data = data
        def json(self): return self.data

    def fake_post(url, **kw):
        if url.endswith("/api/vision"):
            assert kw["data"]["hint"] == "cake x1"
            return Resp({"source": "openai", "foods": [{"items": ["popcorn (2 bags)"], "servings": 8, "category": "packaged"}]})
        sent.append(kw["json"]["food"])
        return Resp({"id": "D1"})

    real = camera.requests.post
    camera.requests.post = fake_post
    try:
        up.donate({"cake": 1}, b"jpg")
        assert sent[0]["items"] == ["popcorn (2 bags)"]        # the model's answer wins over the detector's guess
        sent.clear()
        camera.requests.post = lambda url, **kw: Resp({"source": "demo"}) if url.endswith("/api/vision") else (sent.append(kw["json"]["food"]) or Resp({"id": "D2"}))
        up.donate({"pizza": 2}, b"jpg")
        assert sent[0]["items"] == ["pizza x2"] and sent[0]["allergens_unverified"]   # no model: counts, allergens unconfirmed
    finally:
        camera.requests.post = real


def test_vision_multi_uses_neutral_defaults():
    import llm
    import vision
    saved = (llm.available, llm.provider, llm.chat_json)
    llm.available, llm.provider = (lambda: True), (lambda: "openai")
    llm.chat_json = lambda s, u, **k: {"donations": [{"items": ["apples"], "servings": 3, "category": "produce"}]}
    try:
        foods, src = vision.analyze_many(b"x", hint="apple x3")
        assert src == "openai" and foods[0]["allergens"] == [] and foods[0]["safe_minutes"] == 720
    finally:
        llm.available, llm.provider, llm.chat_json = saved


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok ", t.__name__)
    print(f"\n{len(tests)} tests passed")
