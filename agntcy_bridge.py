"""AGNTCY transport for the agent network (Cisco Outshift's open agent stack).

With AGNTCY=1 in .env, every shelter agent and every driver agent becomes its own A2A agent, served over
NATS with the AGNTCY app-sdk. The coordinators reach them only by message:

  1. Announce: one A2A broadcast to every shelter agent that can safely take the food. Each answers
     accept / counter-offer / decline from its own point of view.
  2. Bids: one A2A broadcast to every driver agent with the trips it could make. Each answers with
     its own price and timing, or refuses a trip that's too far.

The same pattern coffeeAGNTCY uses to ask its coffee farms for inventory. Each agent also publishes an
A2A AgentCard and an OASF record (AGNTCY's agent description format), served at /agntcy/records.

Without the SDK (pip install -r requirements-agntcy.txt) or a NATS server (nats-server), everything
runs in-process exactly as before, so the demo never depends on it.
"""
import asyncio
import json
import os
import threading
import time
import uuid

import network

NATS_URL = os.getenv("NATS_URL", "nats://localhost:4222")
TIMEOUT = 6.0

state = {"on": False, "transport": "in-process", "reason": "AGNTCY is off (set AGNTCY=1 in .env)",
         "agents": 0, "messages": 0, "broadcasts": 0, "last_ms": None}
_loop = None
_client = None
_factory = None
_session = None
_registered = set()
_world = None       # callable returning the live World
_reg_lock = threading.Lock()


def enabled():
    return state["on"]


def name_for(kind, ident):
    return f"uplink/{kind}/{ident}"


# ---------------- A2A cards and OASF records (always available, no SDK needed) ----------------

def card_dict(kind, ident, label, desc, skills):
    """An A2A AgentCard as plain JSON (the same shape the SDK builds)."""
    nm = name_for(kind, ident)
    return {"name": nm, "description": f"{label}: {desc}", "url": f"{NATS_URL}/{nm}", "version": "1.0.0",
            "defaultInputModes": ["text"], "defaultOutputModes": ["text"], "capabilities": {"streaming": False},
            "provider": {"organization": "Uplink (UCSC AI Hackathon)", "url": "https://github.com/saraxjain/uplink"},
            "preferredTransport": "natspatterns",
            "additionalInterfaces": [{"transport": "natspatterns", "url": f"{NATS_URL}/{nm}"}],
            "skills": [{"id": s[0], "name": s[1], "description": s[2], "tags": ["food-rescue"]} for s in skills]}


def all_cards(world):
    cards = [card_dict("business", b["id"], b["name"], "announces surplus food to the shelter network",
                       [("announce", "Announce surplus", "Broadcast what food is left, how much, and until when it is safe")])
             for b in world.businesses.values()]
    cards += [card_dict("shelters", n["id"], n["name"], "answers donation requests for one shelter",
                        [("offer", "Answer a donation", "Accept, counter-offer (take only part) or decline, with a reason")])
              for n in world.nonprofits.values()]
    cards += [card_dict("drivers", d["id"], d["name"], "bids on trips for one driver",
                        [("bid", "Bid on trips", "Price and arrival time for each trip, or refuse one that's too far")])
              for d in world.drivers.values()]
    goals = {"Speed": "fast, reliable delivery with a big safety margin", "Cost": "spend as little as possible",
             "Need": "feed whoever needs it most"}
    cards += [card_dict("coordinators", a.lower(), a, f"negotiates with the other coordinators; goal: {g}",
                        [("negotiate", "Negotiate", "Propose a plan, vote on every plan, object or veto, and revise across rounds")])
              for a, g in goals.items()]
    return cards


def oasf_records(world):
    """OASF records for every agent, converted with the AGNTCY SDK when it's installed."""
    cards = all_cards(world)
    try:
        from a2a.types import AgentCard
        from agntcy_app_sdk.directory.oasf_converter import agent_card_to_oasf
        return [agent_card_to_oasf(AgentCard.model_validate(c)) for c in cards], "agntcy_app_sdk.oasf_converter"
    except Exception:  # noqa: BLE001 - same record shape, built by hand
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        return [{"name": c["name"], "schema_version": "1.0.0", "version": c["version"], "description": c["description"],
                 "authors": [c["provider"]["organization"]], "created_at": now, "skills": [{"id": 101}], "domains": [],
                 "modules": [{"id": 203, "name": "integration/a2a", "data": {"card_data": c, "card_schema_version": "v1.0.0"}}]}
                for c in cards], "built-in"


# ---------------- the live transport ----------------

def start(world_getter):
    """Start the AGNTCY agents on a background event loop. Safe to call when AGNTCY is off."""
    global _world
    _world = world_getter
    if os.getenv("AGNTCY", "").strip() not in ("1", "true", "yes", "on"):
        return state
    try:
        import nats  # noqa: F401
        from agntcy_app_sdk.factory import AgntcyFactory  # noqa: F401
    except Exception as e:  # noqa: BLE001
        state["reason"] = f"AGNTCY SDK not installed ({type(e).__name__}); pip install -r requirements-agntcy.txt"
        return state
    ready = threading.Event()
    threading.Thread(target=_run, args=(ready,), daemon=True).start()
    ready.wait(20)
    return state


def _run(ready):
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    try:
        _loop.run_until_complete(_boot())
    except Exception as e:  # noqa: BLE001
        state.update(on=False, transport="in-process", reason=f"Couldn't reach NATS at {NATS_URL} ({type(e).__name__}). Start it with: nats-server")
        ready.set()
        return
    ready.set()
    _loop.run_forever()


async def _boot():
    global _client, _factory, _session
    import nats
    nc = await asyncio.wait_for(nats.connect(NATS_URL, connect_timeout=3, max_reconnect_attempts=1), 5)   # fail fast if no server
    await nc.close()
    from agntcy_app_sdk.factory import AgntcyFactory
    from agntcy_app_sdk.semantic.a2a.client.config import ClientConfig
    _factory = AgntcyFactory()
    _session = _factory.create_app_session(max_sessions=200)
    w = _world()
    for n in w.nonprofits.values():
        await _serve("shelters", n["id"])
    for d in w.drivers.values():
        await _serve("drivers", d["id"])
    await asyncio.sleep(0.5)
    tr = _factory.create_transport("NATS", endpoint=NATS_URL, name="uplink/coordinators/broadcaster")
    first = next(iter(w.nonprofits))
    _client = await _factory.a2a(ClientConfig(nats_transport=tr)).create(_card("shelters", first))
    state.update(on=True, transport="AGNTCY A2A over NATS", reason="", agents=len(_registered))


def _card(kind, ident):
    from a2a.types import AgentCard
    w = _world()
    label = (w.nonprofits.get(ident) or w.drivers.get(ident) or {}).get("name", ident)
    return AgentCard.model_validate(card_dict(kind, ident, label, "Uplink agent", [("offer" if kind == "shelters" else "bid", kind, kind)]))


async def _serve(kind, ident):
    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.tasks import InMemoryTaskStore
    nm = name_for(kind, ident)
    if nm in _registered:
        return
    ex = _ShelterAgent(ident) if kind == "shelters" else _DriverAgent(ident)
    await _session.add_a2a_card(_card(kind, ident), DefaultRequestHandler(agent_executor=ex, task_store=InMemoryTaskStore())) \
        .with_factory(_factory).start(keep_alive=False)
    _registered.add(nm)
    state["agents"] = len(_registered)


def _make_executor(answer):
    from a2a.server.agent_execution import AgentExecutor
    from a2a.utils import new_agent_text_message

    class Exec(AgentExecutor):
        def __init__(self, ident):
            self.ident = ident

        async def execute(self, context, event_queue):
            try:
                reply = answer(self.ident, json.loads(context.get_user_input()))
            except Exception as e:  # noqa: BLE001 - an agent that fails says so instead of hanging the broadcast
                reply = {"error": f"{type(e).__name__}: {e}"}
            reply["agent"] = self.ident
            await event_queue.enqueue_event(new_agent_text_message(json.dumps(reply)))

        async def cancel(self, context, event_queue):
            pass
    return Exec


def _shelter_answer(ident, req):
    """A shelter agent: reads only its own shelter's situation and answers for it."""
    w = _world()
    d = w.get(req["donation"])
    return {"offer": network.shelter_offer(w, w.nonprofits[ident], d)}


def _driver_answer(ident, req):
    """A driver agent: bids on the trips addressed to it, from its own point of view."""
    w = _world()
    d = w.get(req["donation"])
    dr = w.drivers[ident]
    out = {}
    for trip in req["trips"].get(ident, []):
        out[trip["key"]] = network.driver_bid(w, dr, d, w.nonprofits[trip["np"]], trip["plan"])
    return {"bids": out}


def _ShelterAgent(ident):
    return _make_executor(_shelter_answer)(ident)


def _DriverAgent(ident):
    return _make_executor(_driver_answer)(ident)


async def _broadcast(kind, payload, idents):
    from a2a.types import MessageSendParams, SendMessageRequest
    for i in idents:   # agents that joined after startup (a new pantry) get served on first use
        await _serve(kind, i)
    req = SendMessageRequest(id=str(uuid.uuid4()), params=MessageSendParams(message={
        "role": "user", "parts": [{"type": "text", "text": json.dumps(payload)}], "messageId": str(uuid.uuid4()),
        "contextId": payload.get("donation")}))
    t = time.time()
    resps = await _client.broadcast_message(req, recipients=[name_for(kind, i) for i in idents],
                                            broadcast_topic=f"uplink-{kind}", timeout=TIMEOUT)
    out = {}
    for r in resps:
        try:
            m = r.root.result
            body = json.loads(m.parts[0].root.text)
            out[body.pop("agent")] = body
        except Exception:  # noqa: BLE001
            continue
    state["broadcasts"] += 1
    state["messages"] += 1 + len(out)
    state["last_ms"] = round(1000 * (time.time() - t), 1)
    return out


def _call(coro):
    """Run a broadcast on the AGNTCY loop from the planner thread and wait for the answers."""
    return asyncio.run_coroutine_threadsafe(coro, _loop).result(TIMEOUT + 2)


def offers(world, d, shelters):
    """{shelter id: offer} from the shelter agents over AGNTCY, or None to fall back to in-process."""
    if not enabled() or not shelters:
        return None
    try:
        got = _call(_broadcast("shelters", {"type": "announce", "donation": d["id"]}, [n["id"] for n in shelters]))
        res = {k: v["offer"] for k, v in got.items() if "offer" in v}
        missing = [n for n in shelters if n["id"] not in res]
        for n in missing:   # an agent that didn't answer in time is asked directly, so nothing is dropped
            res[n["id"]] = network.shelter_offer(world, n, d)
        return res
    except Exception as e:  # noqa: BLE001
        state["reason"] = f"last broadcast failed ({type(e).__name__}); used in-process answers"
        return None


def bids(world, d, trips):
    """trips: [(key, driver, shelter, plan)] -> {key: bid} from the driver agents over AGNTCY, or None."""
    if not enabled() or not trips:
        return None
    by_driver = {}
    for key, dr, n, p in trips:
        by_driver.setdefault(dr["id"], []).append({"key": key, "np": n["id"], "plan": p})
    try:
        got = _call(_broadcast("drivers", {"type": "bid_request", "donation": d["id"], "trips": by_driver}, list(by_driver)))
        res = {}
        for v in got.values():
            res.update(v.get("bids", {}))
        for key, dr, n, p in trips:
            if key not in res:
                res[key] = network.driver_bid(world, dr, d, n, p)
        return res
    except Exception as e:  # noqa: BLE001
        state["reason"] = f"last broadcast failed ({type(e).__name__}); used in-process answers"
        return None
