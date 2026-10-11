"""How the rest of Uplink reaches the agents: discovery through the directory, A2A-style messages over
HTTP, and a trace of every message (who, to whom, what, how long, whether it worked).

Two transports. With AGNTCY on (a NATS server and the AGNTCY app-sdk), each step is ONE A2A broadcast
over NATS: to every shelter agent, to every driver agent, or to the three negotiators (the pattern
coffeeAGNTCY uses to ask its farms). Otherwise each agent gets an HTTP message. If a broadcast fails,
that step falls back to HTTP.

If an agent doesn't answer, the caller carries on without it: a shelter or driver that is down is
simply not consulted, and a negotiator that is down is stood in for by the same logic in-process
(logged as a fallback), so a donation never stalls on one dead process.
"""
import asyncio
import concurrent.futures
import itertools
import json
import uuid
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import requests

import agents
from mesh.view import donation_facts, world_facts

ASK_TIMEOUT = 1.5    # shelters and drivers answer from simple rules
NEGOTIATOR_TIMEOUT = 5.0
LLM_TIMEOUT = 60.0   # a negotiator reasoning with a model takes longer
A2A_TIMEOUT = 4.0    # one broadcast, all answers
DOWN_FOR = 6.0       # after a failed call, skip that agent for this long (the directory drops it too)

_pool = ThreadPoolExecutor(32)


class A2AChannel:
    """An AGNTCY A2A client over NATS, on its own event loop. broadcast() is called from normal threads."""

    def __init__(self, nats_url):
        self.nats_url = nats_url
        self.loop = asyncio.new_event_loop()
        self.client = None
        ready, self.error = threading.Event(), None
        threading.Thread(target=self._run, args=(ready,), daemon=True).start()
        ready.wait(20)
        if self.client is None:
            raise RuntimeError(self.error or "A2A client did not start")

    def _run(self, ready):
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(asyncio.wait_for(self._boot(), 15))
        except Exception as e:  # noqa: BLE001
            self.error = f"{type(e).__name__}: {e}"
        ready.set()
        self.loop.run_forever()

    async def _boot(self):
        from a2a.types import AgentCard
        from agntcy_app_sdk.factory import AgntcyFactory
        from agntcy_app_sdk.semantic.a2a.client.config import ClientConfig
        from mesh.agent import a2a_card
        factory = AgntcyFactory()
        tr = factory.create_transport("NATS", endpoint=self.nats_url, name="uplink/table/relay")
        me = {"name": "Negotiation table", "description": "relays messages between agents and counts votes",
              "skills": ["relay"]}
        self.client = await factory.a2a(ClientConfig(nats_transport=tr)).create(
            AgentCard.model_validate(a2a_card("negotiator", "table", me, self.nats_url)))

    async def _broadcast(self, names, envelope, timeout):
        from a2a.types import MessageSendParams, SendMessageRequest
        req = SendMessageRequest(id=str(uuid.uuid4()), params=MessageSendParams(message={
            "role": "user", "parts": [{"type": "text", "text": json.dumps(envelope)}], "messageId": str(uuid.uuid4()),
            "contextId": envelope.get("donation") or envelope["id"]}))
        # one recipient: publish on its own topic; several: the SDK's invite protocol reaches each by name
        topic = names[0] if len(names) == 1 else "uplink-broadcast"
        resps = await self.client.broadcast_message(req, recipients=names, broadcast_topic=topic, timeout=timeout)
        out = {}
        for r in resps:
            try:
                body = json.loads(r.root.result.parts[0].root.text)
                out[body["from"]] = body
            except Exception:  # noqa: BLE001 - a malformed answer counts as no answer
                continue
        return out

    def broadcast(self, names, envelope, timeout):
        """{agent record id: reply envelope} from every agent that answered."""
        return asyncio.run_coroutine_threadsafe(self._broadcast(names, envelope, timeout), self.loop).result(timeout + 3)


class MeshClient:
    def __init__(self, directory_url, launcher=None, nats_url=None):
        self.directory = directory_url.rstrip("/")
        self.launcher = launcher
        self.a2a = None
        self.transport = "http"
        if nats_url:
            try:
                self.a2a = A2AChannel(nats_url)
                self.transport = "a2a"
            except Exception as e:  # noqa: BLE001 - HTTP still works
                print(f"AGNTCY A2A client unavailable ({e}); agents talk over HTTP.")
        self.http = requests.Session()
        self.trace = deque(maxlen=500)
        self.stats = {}            # agent id -> {"sent", "failed", "ms"}
        self.down = {}             # agent id -> time it failed
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._cache = (0.0, [])

    # ---------------- discovery ----------------
    def agents(self, kind=None, fresh=False):
        t, recs = self._cache
        if fresh or time.time() - t > 0.5:
            try:
                recs = self.http.get(f"{self.directory}/agents", timeout=1).json()["agents"]
            except requests.RequestException:
                recs = []
            self._cache = (time.time(), recs)
        now = time.time()
        return [r for r in recs if (kind is None or r["kind"] == kind) and now - self.down.get(r["id"], 0) > DOWN_FOR]

    def alive(self, kind):
        """{agent name: record} for the agents of this kind the directory lists right now."""
        return {r["agent"]: r for r in self.agents(kind)}

    # ---------------- messaging ----------------
    def send(self, rec, mtype, payload, timeout, frm="table", donation=None):
        msg = {"id": f"m{next(self._ids)}", "type": mtype, "from": frm, "to": rec["id"], "payload": payload}
        t0 = time.perf_counter()
        err, out = None, None
        try:
            r = self.http.post(rec["locator"]["url"], json=msg, timeout=timeout)
            body = r.json()
            if r.status_code != 200:
                err = body.get("error", f"HTTP {r.status_code}")
            else:
                out = body
        except (requests.RequestException, ValueError) as e:
            err = type(e).__name__
        ms = round((time.perf_counter() - t0) * 1000, 1)
        with self._lock:
            st = self.stats.setdefault(rec["id"], {"sent": 0, "failed": 0, "ms": 0.0})
            st["sent"] += 1
            st["ms"] += ms
            if err:
                st["failed"] += 1
                self.down[rec["id"]] = time.time()
            self.trace.append({"t": time.time(), "id": msg["id"], "from": frm, "to": rec["id"], "type": mtype,
                               "reply": out["type"] if out else "error", "ms": ms, "ok": err is None, "via": "HTTP",
                               "error": err, "donation": donation})
        if err:
            raise RuntimeError(f"{rec['id']}: {err}")
        return out["payload"]

    def broadcast(self, recs, mtype, payload, timeout, frm="table", donation=None):
        """ONE A2A broadcast over NATS to these agents. {record id: payload} for those that answered.
        Raises if the broadcast itself fails (callers then use HTTP)."""
        recs = [r for r in recs if r.get("a2a")]
        if not self.a2a or not recs:
            raise RuntimeError("A2A not available")
        msg = {"id": f"m{next(self._ids)}", "type": mtype, "from": frm, "to": [r["id"] for r in recs],
               "donation": donation, "payload": payload}
        t0 = time.perf_counter()
        got = self.a2a.broadcast([r["a2a"]["name"] for r in recs], msg, timeout)
        ms = round((time.perf_counter() - t0) * 1000, 1)
        out = {}
        with self._lock:
            for r in recs:
                body = got.get(r["id"])
                ok = bool(body) and body.get("type") != "error"
                st = self.stats.setdefault(r["id"], {"sent": 0, "failed": 0, "ms": 0.0})
                st["sent"] += 1
                st["ms"] += ms
                if not ok:
                    st["failed"] += 1
                    self.down[r["id"]] = time.time()
                else:
                    out[r["id"]] = body["payload"]
                self.trace.append({"t": time.time(), "id": msg["id"], "from": frm, "to": r["id"], "type": mtype,
                                   "reply": body["type"] if ok else "error", "ms": ms, "ok": ok, "via": "A2A/NATS",
                                   "error": None if ok else ((body or {}).get("error") or "no answer"), "donation": donation})
        return out

    def _many(self, jobs):
        """Run sends in parallel; a failed one comes back as None."""
        futs = [_pool.submit(fn) for fn in jobs]
        out = []
        for f in futs:
            try:
                out.append(f.result())
            except Exception:  # noqa: BLE001 - that agent is skipped
                out.append(None)
        return out

    # ---------------- what the world asks ----------------
    def offers(self, world, d, shelters):
        """Ask each shelter's agent about this donation. {shelter id: offer, or None if it didn't answer}."""
        live = self.alive("shelter")
        dfacts = donation_facts(d)
        recs = [live[n["id"]] for n in shelters if n["id"] in live]
        if self.a2a and recs:
            try:
                facts = world_facts(world, d, [n["id"] for n in shelters])
                got = self.broadcast(recs, "offer.request", {"donation": dfacts, "facts": facts}, A2A_TIMEOUT,
                                     frm=f"business:{d.get('business', 'donor')}", donation=d["id"])
                return {n["id"]: got.get(f"shelter:{n['id']}") for n in shelters}
            except Exception:  # noqa: BLE001 - this step falls back to HTTP
                pass
        jobs, ids = [], []
        for n in shelters:
            rec = live.get(n["id"])
            if not rec:
                continue
            facts = world_facts(world, d, [n["id"]])
            jobs.append(lambda rec=rec, facts=facts: self.send(
                rec, "offer.request", {"donation": dfacts, "facts": facts}, ASK_TIMEOUT,
                frm=f"business:{d.get('business', 'donor')}", donation=d["id"]))
            ids.append(n["id"])
        got = dict(zip(ids, self._many(jobs)))
        return {n["id"]: got.get(n["id"]) for n in shelters}

    def bids(self, world, d, trips):
        """Ask each driver's agent to bid on each (shelter, driver, plan) trip. A list, None where no answer."""
        live = self.alive("driver")
        dfacts = donation_facts(d)
        if self.a2a and trips:
            by_driver, recs = {}, {}
            for i, (n, dr, p) in enumerate(trips):
                if dr["id"] not in live:
                    continue
                recs[dr["id"]] = live[dr["id"]]
                by_driver.setdefault(dr["id"], []).append({
                    "key": str(i), "shelter": {k: n.get(k) for k in ("id", "name", "lat", "lng")},
                    "driver": {k: v for k, v in dr.items() if k not in ("pos", "home", "leg_start")}, "plan": p})
            if recs:
                try:
                    got = self.broadcast(list(recs.values()), "bid.batch", {"donation": dfacts, "trips": by_driver},
                                         A2A_TIMEOUT, frm="dispatch", donation=d["id"])
                    out = [None] * len(trips)
                    for dr_id, rep in got.items():
                        for key, bid in rep["bids"].items():
                            out[int(key)] = bid
                    return out
                except Exception:  # noqa: BLE001 - this step falls back to HTTP
                    pass
        jobs, idx = [], []
        for i, (n, dr, p) in enumerate(trips):
            rec = live.get(dr["id"])
            if not rec:
                continue
            shelter = {k: n.get(k) for k in ("id", "name", "lat", "lng")}
            driver = {k: v for k, v in dr.items() if k not in ("pos", "home", "leg_start")}   # what the world knows of it
            jobs.append(lambda rec=rec, shelter=shelter, driver=driver, p=p: self.send(
                rec, "bid.request", {"donation": dfacts, "shelter": shelter, "driver": driver, "plan": p},
                ASK_TIMEOUT, frm="dispatch", donation=d["id"]))
            idx.append(i)
        out = [None] * len(trips)
        for i, b in zip(idx, self._many(jobs)):
            out[i] = b
        return out

    def council(self, world, d, plans):
        return RemoteCouncil(self, world, d, plans)

    # ---------------- for the dashboard ----------------
    def status(self, limit=80):
        recs = self.agents(fresh=True)
        listed = {r["id"] for r in recs}
        procs = self.launcher.processes() if self.launcher else {}
        rows = []
        for r in recs:
            st = self.stats.get(r["id"], {"sent": 0, "failed": 0, "ms": 0.0})
            rows.append(dict(r, status="online", sent=st["sent"], failed=st["failed"],
                             avg_ms=round(st["ms"] / st["sent"], 1) if st["sent"] else None))
        for aid, p in procs.items():   # started by us but not (or no longer) in the directory
            if aid not in listed:
                rows.append({"id": aid, "agent": p["agent"], "kind": p["kind"], "name": p["agent"],
                             "status": "starting" if p["running"] else "stopped", "pid": p["pid"],
                             "locator": {"url": f"http://127.0.0.1:{p['port']}/a2a"}, "skills": []})
        with self._lock:
            trace = list(self.trace)[-limit:]
            total = sum(s["sent"] for s in self.stats.values())
            failed = sum(s["failed"] for s in self.stats.values())
        return {"directory": self.directory, "transport": self.transport,
                "nats": self.a2a.nats_url if self.a2a else None,
                "agents": sorted(rows, key=lambda x: (x["kind"], x["id"])),
                "trace": trace[::-1], "messages": total, "failed": failed}


class RemoteCouncil:
    """Speed, Cost and Need as separate services. Same interface as agents.LocalCouncil."""
    remote = True

    def __init__(self, client, world, d, plans):
        self.c, self.world, self.d, self.plans = client, world, d, plans
        self.dfacts = donation_facts(d)
        self.facts = world_facts(world, d, {p["np"] for p in plans})
        self.live = client.alive("negotiator")
        self.local = agents.LocalCouncil(world, d, plans)
        self.fallbacks = []
        self._steps, self._step_lock = {}, threading.Lock()

    def _broadcast_step(self, key, mtype, extra, mode):
        """With A2A: the first of the three agents' calls for a step sends ONE broadcast to all three
        negotiators; the other two calls wait for it and read their own answer."""
        with self._step_lock:
            fut = self._steps.get(key)
            leader = fut is None
            if leader:
                fut = self._steps[key] = concurrent.futures.Future()
        if leader:
            try:
                payload = dict({"donation": self.dfacts, "plans": self.plans, "facts": self.facts}, **extra)
                fut.set_result(self.c.broadcast(list(self.live.values()), mtype, payload,
                                                LLM_TIMEOUT if mode == "llm" else A2A_TIMEOUT, donation=self.d["id"]))
            except Exception as e:  # noqa: BLE001
                fut.set_exception(e)
        return fut.result()

    def _ask(self, a, mtype, extra, mode="rules", key=None):
        rec = self.live.get(a)
        if not rec:
            raise RuntimeError(f"{a} is not in the directory")
        if self.c.a2a and key is not None:
            try:
                got = self._broadcast_step(key, mtype, extra, mode)
                if rec["id"] in got:
                    return got[rec["id"]]
            except Exception:  # noqa: BLE001 - fall through to HTTP for this agent
                pass
        payload = dict({"donation": self.dfacts, "plans": self.plans, "facts": self.facts}, **extra)
        return self.c.send(rec, mtype, payload, LLM_TIMEOUT if mode == "llm" else NEGOTIATOR_TIMEOUT,
                           frm="table", donation=self.d["id"])

    def evaluate(self, a):
        try:
            out = self._ask(a, "plan.evaluate", {}, key=("evaluate",))
            return out["scores"], out["vetoes"]
        except Exception:  # noqa: BLE001 - stand in with the same logic, and say so
            self.fallbacks.append(a)
            return self.local.evaluate(a)

    def propose(self, a, S, V, r, history, mode):
        try:
            out = self._ask(a, "plan.propose", {"S": S, "V": V, "r": r, "history": history, "mode": mode}, mode, key=("propose", r))
            return out["plan"], out["reason"], out["llm"]
        except Exception:  # noqa: BLE001
            self.fallbacks.append(a)
            return self.local.propose(a, S, V, r, history, mode)

    def vote(self, a, proposed, S, V, r, mode):
        try:
            out = self._ask(a, "plan.vote", {"proposed": proposed, "S": S, "V": V, "r": r, "mode": mode}, mode, key=("vote", r))
            return out["votes"], out["llm"]
        except Exception:  # noqa: BLE001
            self.fallbacks.append(a)
            return self.local.vote(a, proposed, S, V, r, mode)
