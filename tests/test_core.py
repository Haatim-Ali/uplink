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
    assert len(a.donations) >= 18 and a.done()   # 18 donated; counter-offers can split some in two
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
    d = w.add_donation(dict(PIZZA, servings=50), "campus-cafe")   # Housing Matters (harbor-house) serves at most 40 hot meals a day
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


# ---------- voice (ElevenLabs) and .env ----------

def test_voice_understands_yes_no_and_how_many():
    import voice
    cases = {"Yes, send it over": (True, None), "sure we'll take it": (True, None), "sorry, we're full tonight": (False, None),
             "no": (False, None), "we can only take twenty": (True, 20), "just 15 please": (True, 15),
             "we can take all 40": (True, None), "we can't take more than ten": (True, 10), "maybe half": (True, 20),
             "twenty-five works": (True, 25), "hmm let me check": None, "": None}
    for text, want in cases.items():
        got = voice.parse_answer(text, 40)
        assert (got and (got["accept"], got["servings"])) == want or (got is None and want is None), (text, got)


def test_env_file_loads_keys_without_overriding_the_terminal(tmp_path=None):
    import tempfile

    import env
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, ".env")
        with open(path, "w") as f:
            f.write("# comment\nUPLINK_TEST_A=from-file\nexport UPLINK_TEST_B='quoted'\nUPLINK_TEST_C=\nUPLINK_TEST_D=file\n")
        os.environ["UPLINK_TEST_D"] = "terminal"
        try:
            env.load(path)
            assert os.environ["UPLINK_TEST_A"] == "from-file" and os.environ["UPLINK_TEST_B"] == "quoted"
            assert "UPLINK_TEST_C" not in os.environ and os.environ["UPLINK_TEST_D"] == "terminal"
        finally:
            for k in "ABCD":
                os.environ.pop(f"UPLINK_TEST_{k}", None)


def test_shelter_can_answer_out_loud():
    import app
    import voice
    saved = voice.available
    voice.available = lambda: False
    try:
        c = app.app.test_client()
        assert c.get("/api/tts?who=Speed&text=hi").status_code == 503   # browser voice takes over
        import time
        w = World(live=True)
        app.state["world"] = w
        d = w.add_donation(dict(PIZZA), "campus-cafe")
        w.phones = {n: time.time() + 3600 for n in w.nonprofits}   # every shelter phone is online
        w.plan(d)
        assert d["status"] == "awaiting_shelter"
        np_id = d["ask"]["plan"]["np"]
        assert "Can you take it" in c.get(f"/api/shelter/{np_id}/ask_text?donation={d['id']}").get_json()["text"]
        r = c.post("/api/shelter/voice", data={"donation": d["id"], "text": "we can only take ten"}).get_json()
        assert r["ok"] and r["servings"] == 10
    finally:
        voice.available = saved


# ---------- menus ----------

def test_menu_lines_become_one_donation_per_kind_of_food():
    import menu
    foods = menu.foods_from_lines("campus-cafe", [{"id": "campus-cafe-1", "qty": 2}, {"id": "campus-cafe-3", "qty": 12},
                                                  {"id": "campus-cafe-2", "qty": 1}, {"id": "nope", "qty": 3}])
    hot = next(f for f in foods if f["category"] == "hot prepared")
    cold = next(f for f in foods if f["category"] == "cold prepared")
    assert len(foods) == 2 and hot["servings"] == 24 and set(hot["allergens"]) == {"dairy", "gluten"}
    assert cold["needs_cold"] and cold["servings"] == 12 and not cold["allergens_unverified"]


def test_photo_items_on_the_menu_take_its_allergens():
    import menu
    f = menu.enrich({"items": ["pepperoni pizza (2 pizzas)"], "allergens": [], "category": "packaged",
                     "allergens_unverified": True}, "campus-cafe")
    assert f["menu_matches"] == 1 and f["category"] == "hot prepared" and set(f["allergens"]) == {"dairy", "gluten"}
    assert f["allergens_unverified"] is False


def test_add_menu_item_and_donate_from_menu():
    import tempfile

    import app
    import menu
    saved = menu.EXTRA
    with tempfile.TemporaryDirectory() as tmp:
        menu.EXTRA = os.path.join(tmp, "extra.json")
        try:
            app.state["world"] = World(live=True)
            c = app.app.test_client()
            item = c.post("/api/menu/campus-cafe", json={"name": "Vegetable soup", "category": "hot prepared",
                                                          "serves": 4, "allergens": ["Celery"]}).get_json()["item"]
            assert item["added"] and item["allergens"] == ["celery"]
            assert any(m["name"] == "Vegetable soup" for m in c.get("/api/menu/campus-cafe").get_json()["items"])
            r = c.post("/api/donate/menu", json={"business": "campus-cafe", "lines": [{"id": item["id"], "qty": 2}]}).get_json()
            d = app.state["world"].get(r["ids"][0])
            assert d["food"]["servings"] == 8 and d["food"]["allergens"] == ["celery"]
            assert c.post("/api/donate/menu", json={"business": "campus-cafe", "lines": []}).status_code == 400
        finally:
            menu.EXTRA = saved


def test_one_time_item_is_donated_without_touching_the_menu():
    import tempfile

    import app
    import menu
    saved = menu.EXTRA
    with tempfile.TemporaryDirectory() as tmp:
        menu.EXTRA = os.path.join(tmp, "extra.json")
        try:
            app.state["world"] = World(live=True)
            c = app.app.test_client()
            before = len(c.get("/api/menu/campus-cafe").get_json()["items"])
            r = c.post("/api/donate/menu", json={"business": "campus-cafe", "lines": [{"id": "campus-cafe-1", "qty": 1}],
                                                 "extras": [{"name": "Lasagna", "qty": 2, "serves": 6, "category": "hot prepared",
                                                             "allergens": ["Dairy", "gluten"]}]}).get_json()
            assert len(r["ids"]) == 1   # same kind of food as the pizza: one donation
            f = app.state["world"].get(r["ids"][0])["food"]
            assert f["servings"] == 8 + 12 and "Lasagna ×2" in f["items"] and f["allergens_unverified"]
            assert "Lasagna" in f["notes"]
            assert len(c.get("/api/menu/campus-cafe").get_json()["items"]) == before   # the menu is unchanged
            only = c.post("/api/donate/menu", json={"business": "campus-cafe", "extras": [{"name": "Fruit cups", "qty": 5,
                                                                                         "category": "cold prepared"}]})
            assert only.status_code == 200
            assert c.post("/api/donate/menu", json={"business": "campus-cafe", "extras": [{"name": " ", "qty": 3}]}).status_code == 400
        finally:
            menu.EXTRA = saved


def test_one_time_item_checked_by_a_person_is_verified_and_can_be_saved():
    import tempfile

    import app
    import menu
    saved = menu.EXTRA
    with tempfile.TemporaryDirectory() as tmp:
        menu.EXTRA = os.path.join(tmp, "extra.json")
        try:
            app.state["world"] = World(live=True)
            c = app.app.test_client()
            x = {"name": "Vegetable lasagna", "qty": 2, "serves": 8, "category": "hot prepared",
                 "ingredients": ["pasta", "ricotta", "spinach"], "allergens": ["dairy", "gluten", "eggs"],
                 "confirmed": True, "save": True}
            r = c.post("/api/donate/menu", json={"business": "campus-cafe", "extras": [x]}).get_json()
            f = app.state["world"].get(r["ids"][0])["food"]
            assert not f["allergens_unverified"] and "ricotta" in f["notes"] and "checked by the business" in f["notes"]
            kept = [m for m in menu.items("campus-cafe") if m["name"] == "Vegetable lasagna"]
            assert kept and kept[0]["ingredients"] == ["pasta", "ricotta", "spinach"]
            # saving without checking the allergens doesn't add it to the menu
            c.post("/api/donate/menu", json={"business": "campus-cafe", "extras": [{**x, "name": "Mystery stew", "confirmed": False}]})
            assert not any(m["name"] == "Mystery stew" for m in menu.items("campus-cafe"))
        finally:
            menu.EXTRA = saved


def test_photo_items_not_on_the_menu_are_named():
    import menu
    f = menu.enrich({"items": ["pepperoni pizza (2 pizzas)", "lasagna tray"], "allergens": [], "category": "packaged",
                     "allergens_unverified": True}, "campus-cafe")
    assert f["menu_matches"] == 1 and f["off_menu"] == ["lasagna tray"] and f["allergens_unverified"]


def test_each_demo_scenario_shows_the_outcome_in_its_title():
    """Guards the demo: a scenario named after an outcome must still produce it."""
    want = {"majority_dissent": "majority", "unacceptable_compromise": "unacceptable", "irreconcilable": "irreconcilable",
            "insufficient_evidence": "insufficient_evidence", "standoff": "unacceptable"}
    for name, outcome in want.items():
        w = World(copy.deepcopy(scenarios.SCENARIOS[name]), live=False)
        for _ in range(40):
            w.tick()
        assert w.outcomes.get(outcome), (name, w.outcomes)


def test_spoken_leftovers_fill_in_the_menu():
    import app
    import llm
    saved = llm.available
    llm.available = lambda: False   # the word-matching path, no AI needed
    try:
        c = app.app.test_client()
        r = c.post("/api/voice/donation", data={"business": "corner-bakery",
                   "text": "we have two dozen bagels and 12 croissants and 4 country loaves"}).get_json()
        got = {ln["name"]: ln["qty"] for ln in r["lines"]}
        assert got == {"Bagel": 24, "Croissant": 12, "Country loaf": 4}, got
        r = c.post("/api/voice/donation", data={"business": "lakeside-hotel",
                   "text": "two trays of campanella pasta and one quart of dream inn chowder"}).get_json()
        assert {ln["name"]: ln["qty"] for ln in r["lines"]} == {"Campanella Pasta": 2, "Dream Inn Chowder": 1}
        assert c.post("/api/voice/donation", data={"business": "campus-cafe"}).status_code == 400
    finally:
        llm.available = saved


# ---------- AGNTCY ----------

def test_every_agent_has_an_a2a_card_and_an_oasf_record():
    import app
    app.state["world"] = World(live=True)
    r = app.app.test_client().get("/agntcy/records").get_json()
    w = app.state["world"]
    assert r["count"] == len(w.businesses) + len(w.nonprofits) + len(w.drivers) + 3   # + Speed, Cost, Need
    rec = r["records"][0]
    assert rec["schema_version"] and rec["modules"][0]["name"] == "integration/a2a"
    card = rec["modules"][0]["data"]["card_data"]
    assert card["name"].startswith("uplink/") and card["preferredTransport"] == "natspatterns"


def test_agntcy_off_means_in_process_and_same_answers():
    import agntcy_bridge
    assert not agntcy_bridge.enabled()   # tests never need a NATS server
    w = World(live=True)
    d = w.add_donation(dict(PIZZA), "campus-cafe")
    assert agntcy_bridge.offers(w, d, list(w.nonprofits.values())) is None   # caller falls back to in-process


def test_new_information_opens_the_replan_and_each_agent_says_if_it_changed_its_mind():
    w = World(copy.deepcopy(scenarios.SCENARIOS["volunteer_no_show"]), live=False)
    for _ in range(60):
        w.tick()
    replans = [n for n in w.negotiations if n.get("new_info")]
    assert replans, "a driver cancelled, so some negotiation should carry the new information"
    first = replans[0]["rounds"][0]["messages"]
    assert first[0]["type"] == "news" and "cancelled" in first[0]["text"]
    assert {m["agent"] for m in first if m["type"] == "revise"} == {"Speed", "Cost", "Need"}
    assert any(m["text"].startswith("That changes my pick") for m in first if m["type"] == "revise")


def test_a_rejected_key_stops_ai_calls_and_falls_back():
    import llm
    saved = (llm._call, llm._auth_error, os.environ.get("ANTHROPIC_API_KEY"))
    calls = []

    class Unauthorized(Exception):
        status_code = 401

    def bad(*a, **k):
        calls.append(1)
        raise Unauthorized("invalid x-api-key")
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test-0000"
    llm._call, llm._auth_error = bad, None
    try:
        for _ in range(3):
            try:
                llm.chat_json("s", "u", retries=2)
            except Exception:
                pass
        assert len(calls) == 1, "a 401 must not be retried or repeated"
        assert llm.provider() is None and not llm.available() and "rejected" in llm.auth_error()
    finally:
        llm._call, llm._auth_error = saved[0], saved[1]
        if saved[2] is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = saved[2]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok ", t.__name__)
    print(f"\n{len(tests)} tests passed")


# ---------- drivers are never stranded as "busy" ----------

def test_driver_is_freed_after_a_reconsider_that_finds_nothing_better():
    w = fresh()
    d = w.add_donation(dict(PIZZA), "campus-cafe")
    w.plan(d)
    drv = d["plan"]["driver"]
    d["reconsider"] = True
    real = w.safe_plans
    w.safe_plans = lambda *a, **k: []   # nothing better turns up
    w.plan(d)
    w.safe_plans = real
    for _ in range(300):
        w.tick(plan_inline=False)
        if d["status"] == "delivered":
            break
    assert d["status"] == "delivered"
    assert w.drivers[drv]["status"] == "free"


def test_an_expired_donation_does_not_keep_its_driver_locked():
    w = fresh()
    d1 = w.add_donation(dict(PIZZA), "campus-cafe")
    d1.update(locked_driver="maria", status="stuck", safe_until=w.now)
    w.tick(plan_inline=False)
    assert d1["status"] == "expired" and "locked_driver" not in d1
    for x in w.drivers.values():
        if x["id"] != "maria":
            x["status"] = "off"
    d2 = w.add_donation(dict(PIZZA), "campus-cafe")
    w.plan(d2)
    for _ in range(300):
        w.tick(plan_inline=False)
        if d2["status"] == "delivered":
            break
    assert d2["status"] == "delivered"
    assert w.drivers["maria"]["status"] == "free"
