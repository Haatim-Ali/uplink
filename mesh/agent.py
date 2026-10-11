"""One agent, running as its own service.

    python -m mesh.agent --kind shelter --id grace-kitchen --port 7301 --directory http://127.0.0.1:7300
    python -m mesh.agent --kind driver --id maria --port 7310 ...
    python -m mesh.agent --kind negotiator --id Speed --port 7320 ...

On start it publishes its record in the directory, then heartbeats every 2 s. It answers A2A-style
JSON messages on POST /a2a:  {"id", "type", "from", "to", "payload"}  ->  {"id", "type", "from", "payload"}

  shelter     offer.request   -> accept / counter-offer / decline, with a reason   (network.shelter_offer)
  driver      bid.request     -> a bid for the trip, or a refusal                   (network.driver_bid)
  negotiator  plan.evaluate   -> its scores and vetoes for every safe plan          (agents.agent_evaluate)
              plan.propose    -> its proposal for this round, with a reason         (agents.agent_propose)
              plan.vote       -> accept / object / veto on each proposed plan       (agents.agent_vote)

The world simulator sends the facts (what was delivered, what is on its way, the clock); the agent
brings its own policy. Same functions as in-process, so the decisions are identical.
"""
import argparse
import json
import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import requests  # noqa: E402

import agents  # noqa: E402
import network  # noqa: E402
from mesh.view import WorldView  # noqa: E402

DATA = os.path.join(HERE, "data")
HEARTBEAT = 2.0


def _load(name):
    with open(os.path.join(DATA, name)) as f:
        return json.load(f)


def profile(kind, agent_id, name=None):
    """What this agent knows about itself at start-up."""
    if kind == "shelter":
        pool = _load("nonprofits.json") + [_load("new_pantry.json")]
        return next((n for n in pool if n["id"] == agent_id), {"id": agent_id, "name": agent_id})
    if kind == "driver":
        return next((d for d in _load("drivers.json") if d["id"] == agent_id), {"id": agent_id, "name": name or agent_id})
    return {"id": agent_id, "name": agent_id, "goal": agents.GOALS.get(agent_id, ""),
            "red_line": agents.RED_LINES.get(agent_id, "")}


def record(kind, agent_id, port, prof):
    """The directory record, modeled on an OASF agent record."""
    base = {"id": f"{kind}:{agent_id}", "agent": agent_id, "kind": kind, "version": "1.0", "pid": os.getpid(),
            "locator": {"type": "http", "url": f"http://127.0.0.1:{port}/a2a"}}
    if kind == "shelter":
        return dict(base, name=f"{prof.get('name', agent_id)} (shelter agent)", skills=["food.receive", "donation.offer"],
                    description="Answers donation requests for its shelter: accept, counter-offer or decline.",
                    capabilities={k: prof.get(k) for k in ("accepts", "has_fridge", "open_until", "capacity_servings")})
    if kind == "driver":
        return dict(base, name=f"{prof.get('name', agent_id)} (driver agent)", skills=["delivery.transport", "trip.bid"],
                    description="Bids on delivery trips, or refuses ones beyond its range.",
                    capabilities={k: prof.get(k) for k in ("type", "max_km", "base_usd", "per_km_usd")})
    return dict(base, name=f"{agent_id} (negotiator)", skills=["plan.evaluate", "plan.propose", "plan.vote"],
                description=f"Negotiates delivery plans. Goal: {prof['goal']}.",
                capabilities={"goal": prof["goal"], "red_line": prof["red_line"]})


def handle(kind, agent_id, prof, msg):
    t, p = msg["type"], msg.get("payload", {})
    if kind == "shelter" and t == "offer.request":
        view = WorldView(p["facts"])
        n = dict(prof, **view.nonprofits[agent_id])   # its own profile + what physically happened today
        return "offer.response", network.shelter_offer(view, n, p["donation"])
    if kind == "driver" and t == "bid.request":
        dr = dict(prof, **p["driver"])
        return "bid.response", network.driver_bid(None, dr, p["donation"], p["shelter"], p["plan"])
    if kind == "negotiator":
        view = WorldView(p["facts"])
        d, plans = p["donation"], p["plans"]
        if t == "plan.evaluate":
            scores, vetoes = agents.agent_evaluate(agent_id, view, d, plans)
            return "plan.evaluation", {"scores": scores, "vetoes": vetoes}
        if t == "plan.propose":
            pid, reason, used = agents.agent_propose(agent_id, view, d, plans, p["S"], p["V"], p["r"], p["history"], p["mode"])
            return "plan.proposal", {"plan": pid, "reason": reason, "llm": used}
        if t == "plan.vote":
            votes, used = agents.agent_vote(agent_id, view, d, plans, p["proposed"], p["S"], p["V"], p["r"], p["mode"])
            return "plan.votes", {"votes": votes, "llm": used}
    raise ValueError(f"{kind} agent can't handle {t}")


def make_handler(kind, agent_id, prof, rec):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/card":
                return self._send(200, rec)
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/a2a":
                return self._send(404, {"error": "not found"})
            msg = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            try:
                rtype, payload = handle(kind, agent_id, prof, msg)
                self._send(200, {"id": msg.get("id"), "type": rtype, "from": rec["id"], "to": msg.get("from"), "payload": payload})
            except Exception as e:  # noqa: BLE001 - report the failure to the sender, keep serving
                self._send(500, {"id": msg.get("id"), "type": "error", "from": rec["id"], "error": f"{type(e).__name__}: {e}"})
    return Handler


def parent_gone(parent):
    """True once the process that started us has exited (we then get re-parented)."""
    return parent is not None and os.getppid() != parent


def _keep_registered(directory, rec, stop, parent=None):
    """Register, then heartbeat; register again if the directory forgot us (e.g. it restarted).
    Exit if the app that started us is gone, so no agent outlives it."""
    registered = False
    while not stop.is_set():
        if parent_gone(parent):
            try:
                requests.post(f"{directory}/deregister", json={"id": rec["id"]}, timeout=1)
            finally:
                os._exit(0)
        try:
            if not registered:
                requests.post(f"{directory}/register", json=rec, timeout=2).raise_for_status()
                registered = True
            elif not requests.post(f"{directory}/heartbeat", json={"id": rec["id"]}, timeout=2).json().get("ok"):
                registered = False
                continue
        except requests.RequestException:
            registered = False
        stop.wait(HEARTBEAT if registered else 0.5)


def serve(kind, agent_id, port, directory, background=False, name=None):
    """Run the agent. background=True runs it in threads (tests) and returns (server, stop_event)."""
    prof = profile(kind, agent_id, name)
    rec = record(kind, agent_id, port, prof)
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(kind, agent_id, prof, rec))
    srv.daemon_threads = True
    stop = threading.Event()
    parent = None if background else os.getppid()
    threading.Thread(target=_keep_registered, args=(directory, rec, stop, parent), daemon=True).start()
    if background:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv, stop

    def bye(*_):
        stop.set()
        try:
            requests.post(f"{directory}/deregister", json={"id": rec["id"]}, timeout=1)
        except requests.RequestException:
            pass
        os._exit(0)
    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)
    srv.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="One Uplink agent as a service")
    ap.add_argument("--kind", required=True, choices=["shelter", "driver", "negotiator"])
    ap.add_argument("--id", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--directory", default="http://127.0.0.1:7300")
    ap.add_argument("--name", help="display name, for agents not in the data files (e.g. a driver who just joined)")
    a = ap.parse_args()
    serve(a.kind, a.id, a.port, a.directory, name=a.name)
