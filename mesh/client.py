"""How the rest of Uplink reaches the agents: discovery through the directory, A2A-style messages over
HTTP, and a trace of every message (who, to whom, what, how long, whether it worked).

If an agent doesn't answer, the caller carries on without it: a shelter or driver that is down is
simply not consulted, and a negotiator that is down is stood in for by the same logic in-process
(logged as a fallback), so a donation never stalls on one dead process.
"""
import itertools
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
DOWN_FOR = 6.0       # after a failed call, skip that agent for this long (the directory drops it too)

_pool = ThreadPoolExecutor(32)


class MeshClient:
    def __init__(self, directory_url, launcher=None):
        self.directory = directory_url.rstrip("/")
        self.launcher = launcher
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
                               "reply": out["type"] if out else "error", "ms": ms, "ok": err is None,
                               "error": err, "donation": donation})
        if err:
            raise RuntimeError(f"{rec['id']}: {err}")
        return out["payload"]

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
        return {"directory": self.directory, "agents": sorted(rows, key=lambda x: (x["kind"], x["id"])),
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

    def _ask(self, a, mtype, extra, mode="rules"):
        rec = self.live.get(a)
        if not rec:
            raise RuntimeError(f"{a} is not in the directory")
        payload = dict({"donation": self.dfacts, "plans": self.plans, "facts": self.facts}, **extra)
        return self.c.send(rec, mtype, payload, LLM_TIMEOUT if mode == "llm" else NEGOTIATOR_TIMEOUT,
                           frm="table", donation=self.d["id"])

    def evaluate(self, a):
        try:
            out = self._ask(a, "plan.evaluate", {})
            return out["scores"], out["vetoes"]
        except Exception:  # noqa: BLE001 - stand in with the same logic, and say so
            self.fallbacks.append(a)
            return self.local.evaluate(a)

    def propose(self, a, S, V, r, history, mode):
        try:
            out = self._ask(a, "plan.propose", {"S": S, "V": V, "r": r, "history": history, "mode": mode}, mode)
            return out["plan"], out["reason"], out["llm"]
        except Exception:  # noqa: BLE001
            self.fallbacks.append(a)
            return self.local.propose(a, S, V, r, history, mode)

    def vote(self, a, proposed, S, V, r, mode):
        try:
            out = self._ask(a, "plan.vote", {"proposed": proposed, "S": S, "V": V, "r": r, "mode": mode}, mode)
            return out["votes"], out["llm"]
        except Exception:  # noqa: BLE001
            self.fallbacks.append(a)
            return self.local.vote(a, proposed, S, V, r, mode)
