"""Flask server: runs the live world on a background clock and serves the pages.

Run:  python app.py   then open http://localhost:5000  (business page: /business)
"""
import copy
import os
import threading
import time

from flask import Flask, Response, jsonify, redirect, request, send_from_directory

import env

env.load()   # API keys from .env (gitignored) before anything reads them

import agents  # noqa: E402
import llm  # noqa: E402
import menu  # noqa: E402
import scenarios  # noqa: E402
import vision  # noqa: E402
import voice  # noqa: E402
from world import World  # noqa: E402

app = Flask(__name__, static_folder="static")
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0   # browsers re-check pages/CSS/JS, so updates show without a hard refresh
lock = threading.Lock()
state = {"world": World(live=True), "speed": 1.0, "paused": False,
         "closing": {"seq": 0, "business": None},   # bumped by the dashboard's "Closing time" button
         "cameras": {}}                               # business id -> {"counts": {...}, "seen": time}


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
def customer_site():
    return send_from_directory("static", "app.html")


@app.get("/ops")
def dashboard():
    return send_from_directory("static", "dashboard.html")


@app.get("/business")
def business():
    return redirect("/#/schedule")


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
    v["voice"] = voice.available()
    return jsonify(v)


@app.post("/api/shelter/respond")
def api_shelter_respond():
    body = request.get_json(silent=True) or {}
    with lock:
        ok = W().respond(body.get("donation"), bool(body.get("accept")), body.get("servings"))
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
    prov = llm.provider()
    claude = prov == "anthropic"
    s["mode"] = {"agents": "llm" if agents.use_llm() else "rules", "vision": prov or "demo",
                 "voice": "elevenlabs" if voice.available() else "browser",
                 # which models are actually answering, so the dashboard can credit them
                 "agents_model": (os.getenv("AGENT_MODEL") or (os.getenv("ANTHROPIC_MODEL") or llm.CLAUDE_MODEL if claude else os.getenv("OPENAI_MODEL", ""))) if agents.use_llm() else "",
                 "vision_model": (os.getenv("ANTHROPIC_MODEL") or llm.CLAUDE_MODEL) if claude else (os.getenv("OPENAI_MODEL", "") if prov else "")}
    s["scenarios"] = [{"name": k, "title": v["title"]} for k, v in scenarios.SCENARIOS.items()]
    s["cameras"] = {b: c["counts"] for b, c in state["cameras"].items() if time.time() - c["seen"] < 5}
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
    if request.form.get("multi"):   # camera at closing time: one donation per food category
        foods, source = vision.analyze_many(f.read(), f.mimetype or "image/jpeg", request.form.get("hint", ""))
        return jsonify(foods=foods, source=source)
    biz = request.form.get("business", "")
    food, source = vision.analyze(f.read(), f.mimetype or "image/jpeg", menu.hint(biz))
    if source not in ("demo", "fallback"):
        food = menu.enrich(food, biz)   # menu items bring their known allergens and category
    return jsonify(food=food, source=source)


# ---------------- menus ----------------

@app.get("/api/menu/<biz>")
def api_menu(biz):
    return jsonify(items=menu.items(biz))


@app.post("/api/menu/<biz>")
def api_menu_add(biz):
    """Add a leftover that isn't on the menu yet; it stays on this business's menu from now on."""
    try:
        return jsonify(item=menu.add(biz, request.get_json(silent=True) or {}))
    except ValueError as e:
        return jsonify(error=str(e)), 400


@app.post("/api/voice/donation")
def api_voice_donation():
    """Hands-free donation: the business says what's left. ElevenLabs Scribe transcribes it (or the browser
    sends its own transcript as 'text'), then Claude (or word matching) maps it onto the business's menu."""
    biz = request.form.get("business", "")
    text = (request.form.get("text") or "").strip()
    f = request.files.get("audio")
    stt = "browser"
    if f and voice.available():
        try:
            text = voice.transcribe(f.read(), f.filename or "say.webm", f.mimetype or "audio/webm")
            stt = "elevenlabs"
        except Exception as e:  # noqa: BLE001
            return jsonify(error=f"Couldn't transcribe that ({type(e).__name__}). Try again or tap items instead."), 502
    if not text:
        return jsonify(error="Didn't catch anything. Tap the mic and say what's left, like 'twenty turkey sandwiches'."), 400
    lines, extras, parser = menu.parse_speech(biz, text)
    return jsonify(heard=text, lines=lines, extras=extras, stt=stt, parser=parser)


@app.post("/api/donate/menu")
def api_donate_menu():
    """Donate items picked from the menu. Different kinds of food (hot, cold, packaged, produce) have
    different safety rules, so each kind becomes its own donation."""
    body = request.get_json(silent=True) or {}
    biz = body.get("business")
    foods = menu.foods_from_lines(biz, body.get("lines"))
    if not foods:
        return jsonify(error="Pick at least one item."), 400
    with lock:
        ids = [W().add_donation(vision.normalize(f, base=vision.NEUTRAL), biz)["id"] for f in foods]
    return jsonify(ok=True, ids=ids)


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


# ---------------- voice (ElevenLabs) ----------------

@app.get("/api/tts")
def api_tts():
    """?who=Speed|Cost|Need|Dispatch&text=...  ->  mp3. 503 without a key, so the browser uses its own voice."""
    if not voice.available():
        return jsonify(error="no ElevenLabs key"), 503
    try:
        audio = voice.speak(request.args.get("who", "Dispatch"), request.args.get("text", ""))
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"voice failed: {type(e).__name__}"), 502
    return Response(audio, mimetype="audio/mpeg", headers={"Cache-Control": "max-age=86400"})


@app.get("/api/shelter/<np_id>/ask_text")
def api_ask_text(np_id):
    """The sentence the dispatcher says to this shelter for a pending request."""
    did = request.args.get("donation")
    with lock:
        v = W().shelter_view(np_id)
    ask = next((a for a in (v or {}).get("asks", []) if a["donation"] == did), None)
    if not ask:
        return jsonify(error="no such request"), 404
    return jsonify(text=voice.ask_text(v["nonprofit"]["name"], ask))


@app.post("/api/shelter/voice")
def api_shelter_voice():
    """A shelter answers out loud: audio -> ElevenLabs speech-to-text -> yes / no / how many -> respond.
    The browser can instead send text it transcribed itself (form field 'text') when there's no key."""
    did = request.form.get("donation")
    text = (request.form.get("text") or "").strip()
    f = request.files.get("audio")
    if f and voice.available():
        try:
            text = voice.transcribe(f.read(), f.filename or "answer.webm", f.mimetype or "audio/webm")
        except Exception as e:  # noqa: BLE001
            return jsonify(error=f"Couldn't transcribe ({type(e).__name__}). Tap a button instead."), 502
    if not text:
        return jsonify(error="Didn't catch that. Try again or tap a button.", heard=""), 400
    with lock:
        d = W().get(did)
        if not d or d["status"] != "awaiting_shelter":
            return jsonify(error="That request is no longer waiting.", heard=text), 409
        ans = voice.parse_answer(text, d["food"]["servings"])
        if ans is None:
            return jsonify(error="Not sure if that was a yes or a no. Try again or tap a button.", heard=text), 422
        np_name = d["ask"]["plan"]["np_name"]
        ok = W().respond(did, ans["accept"], ans["servings"])
        if ok:
            W().say(np_name, f'(by voice) "{text}"', "event", did)
    return jsonify(ok=ok, heard=text, **ans)


# ---------------- camera at the business ----------------

@app.post("/api/closing")
def api_closing():
    """Dashboard button: tell the camera(s) it's closing time, so they donate what they see."""
    body = request.get_json(silent=True) or {}
    state["closing"] = {"seq": state["closing"]["seq"] + 1, "business": body.get("business")}
    return jsonify(state["closing"])


@app.get("/api/closing")
def api_closing_poll():
    return jsonify(state["closing"])


@app.post("/api/camera/status")
def api_camera_status():
    body = request.get_json(silent=True) or {}
    state["cameras"][body.get("business", "?")] = {"counts": body.get("counts", {}), "seen": time.time()}
    return jsonify(ok=True)


@app.get("/api/compare")
def api_compare():
    """Scripted scenarios plus N seeded random runs. Deterministic, so cached after the first call."""
    n = max(5, min(200, int(request.args.get("n", 50))))
    return jsonify(compare_results(n))


_compare_lock = threading.Lock()


def compare_results(n=50):
    with _compare_lock:   # the startup warm-up and a page load never compute it twice
        if n not in _compare_cache:
            rnd = scenarios.compare_random(n, solo=True)
            rnd.pop("runs")
            _compare_cache[n] = {"scripted": scenarios.compare(), "random": rnd}
        return _compare_cache[n]


if __name__ == "__main__":
    threading.Thread(target=clock_loop, daemon=True).start()
    threading.Thread(target=planner_loop, daemon=True).start()
    threading.Thread(target=compare_results, daemon=True).start()   # warm the Evidence page in the background
    port = int(os.getenv("PORT", "5050"))   # 5000 is taken by AirPlay on Macs
    print("Uplink · food rescue agents")
    print(f"Customer site: http://localhost:{port}   Schedule a pickup: http://localhost:{port}/#/schedule")
    print(f"Ops dashboard (judges): http://localhost:{port}/ops   Shelter phone: http://localhost:{port}/shelter")
    print(f"Agents: {'LLM' if agents.use_llm() else 'rules'} · Vision: {llm.provider() or 'demo (no API key)'}"
          f" · Voice: {'ElevenLabs' if voice.available() else 'browser (no ElevenLabs key)'}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
