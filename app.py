"""Flask server: runs the live world on a background clock and serves the pages.

Run:  python app.py   then open http://localhost:5000  (business page: /business)
"""
import copy
import os
import threading
import time

from flask import Flask, jsonify, request, send_from_directory

import agents
import llm
import scenarios
import vision
from world import World

app = Flask(__name__, static_folder="static")
lock = threading.Lock()
state = {"world": World(live=True), "speed": 1.0, "paused": False}


def W():
    return state["world"]


# ---------------- background loops ----------------

def clock_loop():
    """1 simulated minute per real second (times the speed setting). Pauses while agents deliberate."""
    while True:
        time.sleep(1.0 / max(0.1, state["speed"]))
        with lock:
            w = W()
            if state["paused"] or w.busy:
                continue
            w.tick(plan_inline=False)


def planner_loop():
    """Runs negotiations outside the lock so slow model calls don't freeze the dashboard."""
    while True:
        time.sleep(0.2)
        with lock:
            w = W()
            todo = w.needs_planning()
            if not todo:
                continue
            d = todo[0]
            plans = w.prepare(d)
            if plans is None:
                continue
            w.busy = True
        try:
            result = w.decide_plan(d, plans)
        except Exception as e:  # noqa: BLE001
            with lock:
                w.busy = False
                w.say("System", f"Negotiation error: {e}", "event")
            continue
        with lock:
            if W() is not w:
                continue  # reset happened mid-negotiation
            w.busy = False
            plan = result.get("plan")
            if plan and not plan.get("join") and w.drivers[plan["driver"]]["status"] != "free" \
                    and d.get("locked_driver") != plan["driver"] \
                    and not (d["status"] == "en_route" and d["plan"]["driver"] == plan["driver"]):
                d["status"] = "new"  # driver was taken meanwhile; renegotiate
                continue
            w.finish(d, plans, result)


# ---------------- pages ----------------

@app.get("/")
def dashboard():
    return send_from_directory("static", "dashboard.html")


@app.get("/business")
def business():
    return send_from_directory("static", "business.html")


@app.get("/shelter")
def shelter_page():
    return send_from_directory("static", "shelter.html")


@app.get("/api/shelter/<np_id>")
def api_shelter(np_id):
    with lock:
        v = W().shelter_view(np_id)
        options = [{"id": n["id"], "name": n["name"]} for n in W().nonprofits.values()]
    if v is None:
        return jsonify(error="unknown shelter", options=options), 404
    v["options"] = options
    return jsonify(v)


@app.post("/api/shelter/respond")
def api_shelter_respond():
    body = request.get_json(silent=True) or {}
    with lock:
        ok = W().respond(body.get("donation"), bool(body.get("accept")))
    return jsonify(ok=ok)


@app.get("/records")
def records_page():
    return send_from_directory("static", "records.html")


# ---------------- API ----------------

@app.get("/api/state")
def api_state():
    with lock:
        s = W().to_json()
    s["speed"] = state["speed"]
    s["paused"] = state["paused"]
    s["mode"] = {"agents": "llm" if agents.use_llm() else "rules", "vision": llm.provider() or "demo"}
    s["scenarios"] = [{"name": k, "title": v["title"]} for k, v in scenarios.SCENARIOS.items()]
    return jsonify(s)


@app.post("/api/reset")
def api_reset():
    name = (request.get_json(silent=True) or {}).get("scenario")
    sc = copy.deepcopy(scenarios.SCENARIOS[name]) if name in scenarios.SCENARIOS else None
    with lock:
        state["world"] = World(sc, live=True)
        state["paused"] = False
    return jsonify(ok=True)


@app.post("/api/control")
def api_control():
    body = request.get_json(silent=True) or {}
    if "speed" in body:
        state["speed"] = float(body["speed"])
    if "paused" in body:
        state["paused"] = bool(body["paused"])
    return jsonify(ok=True, speed=state["speed"], paused=state["paused"])


@app.post("/api/vision")
def api_vision():
    f = request.files.get("photo")
    if not f:
        return jsonify(error="no photo"), 400
    food, source = vision.analyze(f.read(), f.mimetype or "image/jpeg")
    return jsonify(food=food, source=source)


@app.post("/api/donate")
def api_donate():
    body = request.get_json(silent=True) or {}
    food = vision.normalize(body.get("food") or {})
    with lock:
        d = W().add_donation(food, body.get("business"))
    return jsonify(ok=True, id=d["id"])


@app.post("/api/event/<kind>")
def api_event(kind):
    body = request.get_json(silent=True) or {}
    with lock:
        w = W()
        active = [d for d in w.donations if d["status"] == "en_route"]
        target = w.get(body["donation"]) if body.get("donation") else (active[-1] if active else None)
        if kind == "decline":
            np_id = body.get("nonprofit") or (target["plan"]["np"] if target else None)
            if not np_id:
                return jsonify(error="No donation is on its way to a shelter yet."), 400
            w.decline(np_id)
        elif kind == "cancel":
            drv = body.get("driver")
            if not drv:
                pending = [d for d in active if w.now < d["t_pick"]]
                if not pending:
                    return jsonify(error="No driver is on the way to a pickup right now."), 400
                drv = pending[-1]["plan"]["driver"]
            w.cancel_driver(drv)
        elif kind == "new_pantry":
            w.add_pantry()
        else:
            return jsonify(error="unknown event"), 400
    return jsonify(ok=True)


@app.post("/api/approve")
def api_approve():
    body = request.get_json(silent=True) or {}
    with lock:
        ok = W().approve(body["donation"], body["plan"])
    return jsonify(ok=ok)


@app.post("/api/confirm")
def api_confirm():
    """The business answers the agents' question. allergens=null means "we can't confirm"."""
    body = request.get_json(silent=True) or {}
    with lock:
        ok = W().confirm_allergens(body.get("donation"), body.get("allergens"))
    return jsonify(ok=ok)


_compare_cache = {}


@app.get("/api/compare")
def api_compare():
    """Scripted scenarios plus N seeded random runs. Deterministic, so cached after the first call."""
    n = max(5, min(200, int(request.args.get("n", 50))))
    if n not in _compare_cache:
        rnd = scenarios.compare_random(n)
        rnd.pop("runs")
        _compare_cache[n] = {"scripted": scenarios.compare(), "random": rnd}
    return jsonify(_compare_cache[n])


if __name__ == "__main__":
    threading.Thread(target=clock_loop, daemon=True).start()
    threading.Thread(target=planner_loop, daemon=True).start()
    port = int(os.getenv("PORT", "5000"))
    print("Uplink · food rescue agents")
    print(f"Dashboard: http://localhost:{port}   Business page: http://localhost:{port}/business")
    print(f"Agents: {'LLM' if agents.use_llm() else 'rules'} · Vision: {llm.provider() or 'demo (no API key)'}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
