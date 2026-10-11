"""The simulated world: directory, safety rules, drivers, clock, events, impact.

The agents are real; the world around them is simulated (1 tick = 1 minute).
"""
import datetime
import itertools
import time
import json
import math
import os

import agents
import agntcy_bridge
import network
from config import (COST_LIMIT, HANDOFF_MIN, HUMAN_TIMEOUT, JOIN_EXTRA_MIN, PHONE_ONLINE_SECONDS,
                    MIN_LOT, RELIABILITY_PENALTY, SAFETY_MARGIN, SHELTER_TIMEOUT, SPEED_KMH, START,
                    VEHICLE_SERVINGS, WEIGHT_BONUS)

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
EVIDENCE_WAIT = 15         # wait at most this long for the business to answer a question...
EVIDENCE_DEADLINE = 30     # ...and never past this many minutes before the food is unsafe


def load(name):
    with open(os.path.join(DATA, name)) as f:
        return json.load(f)


def km(a, b):
    r = 6371.0
    la1, la2 = math.radians(a["lat"]), math.radians(b["lat"])
    dla, dlo = la2 - la1, math.radians(b["lng"] - a["lng"])
    h = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def travel(a, b):
    return km(a, b) / SPEED_KMH * 60 + HANDOFF_MIN


def hhmm(m):
    m = int(round(m))
    day = m // 1440
    m %= 1440
    return f"{m // 60:02d}:{m % 60:02d}" + (f" +{day}d" if day else "")


def to_min(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def pos(o):
    return {"lat": o["lat"], "lng": o["lng"]}


def lerp(a, b, t):
    t = max(0.0, min(1.0, t))
    return {"lat": a["lat"] + (b["lat"] - a["lat"]) * t, "lng": a["lng"] + (b["lng"] - a["lng"]) * t}


class World:
    def __init__(self, scenario=None, policy="agents", live=False):
        self.policy = policy          # "agents" or "baseline"
        self.live = live              # live: humans answer escalations; headless: auto-approve
        self.now = self.start = START
        self.nonprofits = {}
        for n in load("nonprofits.json"):
            self._register(n, announce=False)
        self.drivers = {}
        for d in load("drivers.json"):
            d = dict(d, status="free", home=pos(d), pos=pos(d))
            self.drivers[d["id"]] = d
        self.businesses = {b["id"]: b for b in load("businesses.json")}
        self.donations = []
        self.feed, self.decisions, self.records = [], [], []
        self.weights = {a: 1.0 for a in agents.AGENTS}
        self.mesh = None   # set by app.py when agents run as separate services (mesh/)
        self.impact = {"meals": 0, "lbs": 0.0, "cost": 0.0, "spoiled": 0, "escalations": 0, "orgs": set()}
        self.outcomes = {}         # how each negotiation ended (consensus, majority, urgent, ...)
        self.negotiation = None
        self.live_rounds = None   # the debate so far, while agents are still deliberating (live demo only)
        self.live_donation = None
        self.negotiations = []
        self.phones = {}              # nonprofit id -> last time its phone page checked in (real seconds)
        self.network = []             # agent-to-agent messages: announce, offers, bids, awards
        self.events = []
        self.scenario_name = None
        self.busy = False
        self._ids = itertools.count(1)
        self._neg_ids = itertools.count(1)
        if scenario:
            self.load_scenario(scenario)

    # ---------------- directory (capability-based discovery) ----------------
    def _register(self, n, announce=True):
        n = dict(n, open_min=to_min(n["open_until"]), received=0, full=False)
        self.nonprofits[n["id"]] = n
        if announce:
            caps = ", ".join(n["accepts"]) + (", fridge" if n["has_fridge"] else ", no fridge")
            self.say("Directory", f"New member registered: {n['name']} ({caps}, open until {n['open_until']}).", "event")

    def search_directory(self, food):
        """Find nonprofits by capability. Returns (matches, removed-with-reason)."""
        ok, removed = [], []
        for n in self.nonprofits.values():
            why = self.block_reason(n, food)
            (removed.append((n, why)) if why else ok.append(n))
        return ok, removed

    # ---------------- safety rules (code, never negotiated) ----------------
    def block_reason(self, n, food):
        if food["category"] not in n["accepts"]:
            return f"doesn't accept {food['category']}"
        if food["needs_cold"] and not n["has_fridge"]:
            return "no fridge for food that must stay cold"
        bad = [a for a in food["allergens"] if a in n.get("avoid_allergens", [])]
        if bad:
            return f"can't take {', '.join(bad)}"
        if food.get("allergens_unverified") and n.get("avoid_allergens"):
            return f"must avoid {', '.join(n['avoid_allergens'])} and the allergens aren't confirmed"
        if n["full"]:
            return "reported full"
        if n["open_min"] <= self.now:
            return "closed"
        room = n["capacity_servings"] - n["received"] - self.committed(n["id"])
        if room < MIN_LOT:
            return "no room left"
        return None

    def committed_category(self, np_id, category, exclude=None):
        total = 0
        for d in self.donations:
            if d is exclude or d["food"]["category"] != category:
                continue
            if (d["status"] == "en_route" and d["plan"]["np"] == np_id) or \
               (d["status"] == "awaiting_shelter" and d["ask"]["plan"]["np"] == np_id):
                total += d["food"]["servings"]
        return total

    def committed(self, np_id, exclude=None):
        """Servings already on their way to this nonprofit."""
        total = 0
        for d in self.donations:
            if d is exclude:
                continue
            if d["status"] == "en_route" and d["plan"]["np"] == np_id:
                total += d["food"]["servings"]
            elif d["status"] == "awaiting_shelter" and d["ask"]["plan"]["np"] == np_id:
                total += d["food"]["servings"]  # asked and waiting for an answer: hold the room
        return total

    # ---------------- plans ----------------
    def make_plan(self, d, n, dr):
        origin = d["origin"]
        pick = 0.0 if d.get("picked") else travel(dr["pos"] if "pos" in dr else dr, origin)
        deliver = travel(origin, n)
        dist = (0 if d.get("picked") else km(dr.get("pos", dr), origin)) + km(origin, n)
        cost = 0.0 if dr["type"] != "paid" else round(dr["base_usd"] + dr["per_km_usd"] * dist, 2)
        dur = pick + deliver
        arrive = self.now + dur
        return {
            "id": f"{n['id']}|{dr['id']}", "np": n["id"], "np_name": n["name"],
            "driver": dr["id"], "driver_name": dr["name"], "driver_type": dr["type"],
            "pick": round(pick), "dur": round(dur), "arrive": arrive, "arrive_hhmm": hhmm(arrive),
            "slack": round(d["safe_until"] - arrive), "cost": cost,
            "reliability": round(dr["reliability"], 2), "km": round(dist, 1),
            "servings": d["food"]["servings"], "partial": False,
        }

    def join_plans(self, d, ok_nonprofits):
        """Combined trips: a driver already on the way to this same pickup can carry this food too,
        if it's going to a shelter that passes the safety rules and the vehicle has room."""
        if d.get("picked") or d.get("locked_driver"):
            return []
        ok_ids = {n["id"] for n in ok_nonprofits}
        plans = []
        for e in self.donations:
            if e is d or e["status"] != "en_route" or e.get("picked") or self.now >= e["t_pick"]:
                continue
            if e["business"] != d["business"] or e["plan"]["np"] not in ok_ids:
                continue
            load = sum(x["food"]["servings"] for x in self.donations
                       if x["status"] == "en_route" and x["plan"]["driver"] == e["plan"]["driver"])
            if load + d["food"]["servings"] > VEHICLE_SERVINGS:
                continue
            n, dr = self.nonprofits[e["plan"]["np"]], self.drivers[e["plan"]["driver"]]
            dur = e["t_arr"] - self.now + JOIN_EXTRA_MIN
            arrive = self.now + dur
            if arrive > d["safe_until"] - SAFETY_MARGIN or arrive > n["open_min"]:
                continue
            plans.append({
                "id": f"{n['id']}|{dr['id']}|join-{e['id']}", "np": n["id"], "np_name": n["name"],
                "driver": dr["id"], "driver_name": dr["name"] + " (combined trip)", "driver_type": dr["type"],
                "pick": round(e["t_pick"] - self.now), "dur": round(dur), "arrive": arrive, "arrive_hhmm": hhmm(arrive),
                "slack": round(d["safe_until"] - arrive), "cost": 0.0, "reliability": round(dr["reliability"], 2),
                "km": 0.0, "join": e["id"], "servings": d["food"]["servings"], "partial": False,
            })
        return plans

    def usable_drivers(self, d, n):
        out = []
        for dr in self.drivers.values():
            if d.get("locked_driver"):
                if dr["id"] != d["locked_driver"]:
                    continue
            elif dr["status"] != "free":
                continue
            if dr.get("owner") and dr["owner"] != n["id"] and not d.get("locked_driver"):
                continue  # a nonprofit's van serves its own shelter, unless it's already carrying this food
            out.append(dr)
        return out

    def safe_plans(self, d, log=True, food=None):
        """Every (nonprofit, driver) plan that passes the safety rules."""
        ok, removed = self.search_directory(food or d["food"])
        skip = d.get("skip", [])
        removed += [(n, "didn't answer this request") for n in ok if n["id"] in skip]
        ok = [n for n in ok if n["id"] not in skip]
        f = d["food"]
        if log:
            self.net(d, d["business_name"], "network", "announce",
                     f"{'Re-announcing' if d.get('announced') else 'Surplus'}: {f['servings']} servings of {', '.join(f['items'])}, "
                     f"safe until {hhmm(d['safe_until'])}. {len(ok)} shelters can safely take it.")
            d["announced"] = True
        # each shelter agent answers from its own point of view: over AGNTCY (A2A over NATS, agntcy_bridge.py)
        # when that's on, else as its own service (mesh/) when the mesh is on, else in-process
        remote = agntcy_bridge.offers(self, d, ok) if (log and self.live) else None
        if remote is not None:
            offers = {n["id"]: remote[n["id"]] for n in ok}
        elif self.mesh:
            got = self.mesh.offers(self, d, ok)
            removed += [(n, "its agent isn't answering") for n in ok if got[n["id"]] is None]
            ok = [n for n in ok if got[n["id"]] is not None]
            offers = {n["id"]: got[n["id"]] for n in ok}
        else:
            offers = {n["id"]: network.shelter_offer(self, n, d) for n in ok}
        if log:
            for n in ok:
                self.net(d, n["name"], d["business_name"], offers[n["id"]]["kind"], offers[n["id"]]["reason"])
        ok = [n for n in ok if offers[n["id"]]["kind"] != "decline"]
        # each driver agent bids on each trip that could still arrive safely
        trips, late = [], 0
        for n in ok:
            for dr in self.usable_drivers(d, n):
                p = self.make_plan(d, n, dr)
                if p["arrive"] > d["safe_until"] - SAFETY_MARGIN or p["arrive"] > n["open_min"]:
                    late += 1
                    continue
                trips.append((n, dr, p))
        # one A2A broadcast over AGNTCY carries every trip the drivers could make; else the mesh; else in-process
        remote_bids = agntcy_bridge.bids(self, d, [(f"{n['id']}|{dr['id']}", dr, n, p) for n, dr, p in trips]) \
            if (log and self.live) else None
        if remote_bids is not None:
            bids = [remote_bids[f"{n['id']}|{dr['id']}"] for n, dr, p in trips]
        elif self.mesh:
            bids = self.mesh.bids(self, d, trips)
        else:
            bids = [network.driver_bid(self, dr, d, n, p) for n, dr, p in trips]
        plans, refused, silent = [], 0, set()
        bids_by_driver = {}
        for (n, dr, p), bid in zip(trips, bids):
            o = offers[n["id"]]
            if bid is None:
                silent.add(dr["name"])
                continue
            if not bid["willing"]:
                refused += 1
                bids_by_driver.setdefault(dr["name"], []).append(f"declines {n['name']}: {bid['reason']}")
                continue
            p["servings"] = o["servings"]
            p["partial"] = o["kind"] == "counter"
            p["offer"] = o["reason"]
            bids_by_driver.setdefault(dr["name"], []).append(f"{n['name']}: {bid['reason']}")
            plans.append(p)
        if log and silent:
            self.decide(d, "blocked", f"No answer from the agent of {', '.join(sorted(silent))}")
        if log:
            for name, lines in bids_by_driver.items():
                more = f" (+{len(lines) - 2} more)" if len(lines) > 2 else ""
                self.net(d, name, "coordinators", "bid", "; ".join(lines[:2]) + more)
        plans += self.join_plans(d, [n for n in ok if offers[n["id"]]["kind"] == "accept"])
        if log:
            for n, why in removed:
                self.decide(d, "blocked", f"{n['name']}: {why}")
            if late:
                self.decide(d, "blocked", f"{late} plan(s) would arrive too late or after closing")
            if removed:
                names = "; ".join(f"{n['name']} ({why})" for n, why in removed[:4])
                more = f" +{len(removed) - 4} more" if len(removed) > 4 else ""
                self.say("Safety", f"{d['id']}: removed {names}{more}. {len(plans)} safe plans left.", "safety")
        return plans

    # ---------------- feed ----------------
    def say(self, agent, text, kind="info", donation=None):
        self._feed_seq = getattr(self, "_feed_seq", 0) + 1
        self.feed.append({"seq": self._feed_seq, "time": hhmm(self.now), "agent": agent, "type": kind, "text": text,
                          "donation": donation})
        self.feed = self.feed[-300:]

    def net(self, d, frm, to, kind, text):
        self.network.append({"time": hhmm(self.now), "donation": d["id"], "from": frm, "to": to, "kind": kind, "text": text})
        self.network = self.network[-400:]

    def decide(self, d, verdict, text):
        self.decisions.append({"time": hhmm(self.now), "donation": d["id"], "verdict": verdict, "text": text})
        self.decisions = self.decisions[-300:]

    # ---------------- donations ----------------
    def add_donation(self, food, business_id):
        b = self.businesses.get(business_id) or next(iter(self.businesses.values()))
        did = f"D{next(self._ids)}"
        d = {
            "id": did, "food": food, "business": b["id"], "business_name": b["name"],
            "origin": pos(b), "created": self.now, "safe_until": self.now + food["safe_minutes"],
            "status": "new", "plan": None, "picked": False, "dissent": [], "options": [],
        }
        self.donations.append(d)
        self.say("Intake", f"{did} from {b['name']}: {food['servings']} servings of {', '.join(food['items'])} "
                 f"({food['category']}{', keep cold' if food['needs_cold'] else ''}), safe until {hhmm(d['safe_until'])}.",
                 "intake", did)
        return d

    def needs_planning(self):
        return [d for d in self.donations if d["status"] == "new" or d.get("reconsider")]

    def plan(self, d):
        """Synchronous planning (headless runs and rules mode)."""
        plans = self.prepare(d)
        if plans is None:
            return
        result = self.decide_plan(d, plans)
        self.finish(d, plans, result)

    def prepare(self, d):
        if d.get("reconsider") and d["status"] == "en_route":
            d["locked_driver"] = d["plan"]["driver"]
        if self.policy == "baseline":
            return []
        plans = self.safe_plans(d)
        if self.policy == "agents" and d["food"].get("allergens_unverified") and d["status"] == "new":
            relaxed = self.safe_plans(d, log=False, food=dict(d["food"], allergens_unverified=False))
            gap = agents.evidence_gap(self, d, plans, relaxed)
            if gap:
                self.ask_business(d, gap)
                return None
        if not plans:
            d["reconsider"] = False
            if d["status"] == "en_route":
                d.pop("locked_driver", None)   # nothing better found: keep the current trip, and don't strand its driver
            if d["status"] == "new":
                d["status"] = "stuck"
                if not d.get("flagged_stuck"):
                    d["flagged_stuck"] = True
                    self.impact["escalations"] += 1
                    self.say("Human", f"{d['id']}: no safe plan exists right now. A coordinator should step in; "
                             "the agents keep retrying as drivers free up.", "human", d["id"])
            return None
        return plans

    def decide_plan(self, d, plans):
        if self.policy == "baseline":
            return baseline_plan(self, d)
        if self.policy.startswith("solo:"):
            agent = self.policy[5:]
            return max(plans, key=lambda p: agents.score(agent, self, d, p))
        return agents.negotiate(self, d, plans)

    def finish(self, d, plans, result):
        if self.policy == "baseline":
            if result is None:
                d["status"] = "stuck"
                return
            self.say("Baseline", f"{d['id']}: nearest shelter {result['np_name']}, nearest driver {result['driver_name']}.", "result", d["id"])
            self.assign(d, result)
            return
        if self.policy.startswith("solo:"):
            d["reconsider"] = False
            if d["status"] == "en_route":
                d.pop("locked_driver", None)
                if result["np"] != d["plan"]["np"]:
                    self.drivers[d["plan"]["driver"]]["status"] = "free"
                    self.assign(d, result)
                return
            self.say(f"{self.policy[5:]} alone", f"{d['id']}: {short_plan(result)}.", "result", d["id"])
            self.assign(d, result)
            return

        reconsidering = d.get("reconsider") and d["status"] == "en_route"
        d["reconsider"] = False
        self.outcomes[result["outcome"]] = self.outcomes.get(result["outcome"], 0) + 1
        info = d.pop("new_info", None)
        if info:
            self._mark_new_info(d, result, info)
        self.negotiation = dict(result, donation=d["id"], food=", ".join(d["food"]["items"]),
                                time=hhmm(self.now), seq=next(self._neg_ids))
        self.negotiations.append(self.negotiation)
        self.negotiations = self.negotiations[-12:]
        for rnd in result["rounds"]:
            for m in rnd["messages"]:
                self.say(m["agent"], f"R{rnd['round']} · {m['text']}", m["type"], d["id"])
        plan = result["plan"]
        # remember every reliability objection raised in any round, to check later who was right
        d["objections"] = [{"agent": a, "driver": pid.split("|")[1]}
                           for rnd in result["rounds"] for pid, vs in rnd["votes"].items()
                           for a, v in vs.items() if v["kind"] == "reliability"]
        if result["outcome"] in ("irreconcilable", "unacceptable") or (plan and plan["cost"] > COST_LIMIT):
            if plan is None:
                why = result["why"]
            else:
                why = f"cost ${plan['cost']:.2f} is over the ${COST_LIMIT} limit"
                self.outcomes["over_budget"] = self.outcomes.get("over_budget", 0) + 1
            d["options"] = list(result["options"])
            if len(d["options"]) < 2:  # give the coordinator a real choice: add the best different plan
                rest = [p for p in plans if p["id"] not in {o["id"] for o in d["options"]}]
                if rest:
                    d["options"].append(min(rest, key=lambda p: (p["cost"], p["dur"])))
            d["why"] = why
            if reconsidering:
                self.say("Result", f"{d['id']}: no agreement on a better plan; keeping the current one.", "result", d["id"])
                d.pop("locked_driver", None)
                return
            d["status"] = "awaiting_human"
            self.impact["escalations"] += 1
            self.net(d, "coordinators", "human coordinator", "escalate", f"No deal without a human: {why}.")
            opts = " or ".join(short_plan(o) for o in d["options"])
            self.say("Human", f"{d['id']}: asking a coordinator ({why}). Options: {opts}.", "human", d["id"])
            if not self.live:
                self.approve(d["id"], d["options"][0]["id"], auto="scripted")
            return
        label = {"consensus": "Agreed 3 of 3", "majority": "Majority 2 of 3", "urgent": "Time is short, acting on best-supported plan"}[result["outcome"]]
        d["dissent"] = result["dissent"]
        if result["dissent"]:
            who = " and ".join(x["agent"] for x in result["dissent"])
            label += f" ({who} {'disagrees' if len(result['dissent']) == 1 else 'disagree'}, kept on record)"
        if reconsidering:
            d.pop("locked_driver", None)
            if plan["np"] == d["plan"]["np"]:
                self.say("Result", f"{d['id']}: new information reviewed; current plan still best.", "result", d["id"])
                return
            self.say("Result", f"{label}: reroute {d['id']} to {plan['np_name']} (new information).", "result", d["id"])
            self.drivers[d["plan"]["driver"]]["status"] = "free"
            if plan.get("partial") and plan["servings"] < d["food"]["servings"]:
                new = self.split(d, plan["servings"], plan["np_name"])
                if new:
                    new["skip"].append(plan["np"])
            self.assign(d, plan)
            return
        self.say("Result", f"{label}: {short_plan(plan)}, arrives {plan['arrive_hhmm']}"
                 + (f", ${plan['cost']:.2f}" if plan["cost"] else ", free") + ".", "result", d["id"])
        self.net(d, "coordinators", plan["np_name"], "award",
                 f"{label}. {plan['servings']} servings to {plan['np_name']} with {plan['driver_name']}, arriving {plan['arrive_hhmm']}.")
        self.dispatch(d, plan)

    def last_call(self, d):
        """When the fallback must act if no human answers: the last minute the agents' options can still
        arrive safely (with a 2-minute buffer), and never later than HUMAN_TIMEOUT before the food is unsafe."""
        latest = max((d["safe_until"] - SAFETY_MARGIN - o["dur"] for o in d["options"]), default=d["safe_until"])
        return min(latest - 2, d["safe_until"] - HUMAN_TIMEOUT)

    def approve(self, did, plan_id, auto=False):
        d = self.get(did)
        if not d or d["status"] != "awaiting_human":
            return False
        plan = next((o for o in d["options"] if o["id"] == plan_id), None)
        if not plan:
            return False
        dr = self.drivers[plan["driver"]]
        if dr["status"] != "free" and d.get("locked_driver") != dr["id"] and not plan.get("join"):
            d["status"] = "new"  # option no longer valid: renegotiate
            return False
        # The option was priced when the agents asked. If time has passed, it may no longer arrive safely.
        arrive = self.now + plan["dur"]
        if not plan.get("join") and (arrive > d["safe_until"] - SAFETY_MARGIN
                                     or arrive > self.nonprofits[plan["np"]]["open_min"]):
            self.say("Safety", f"{did}: {short_plan(plan)} would now arrive at {hhmm(arrive)}, too late to be safe. "
                     "Not approved; the agents will find a plan that still works.", "safety", did)
            d["status"] = "new"
            return False
        who = {
            False: "Coordinator approved",
            "scripted": "Simulated coordinator (scripted run) picked the agents' top-ranked option",
            "timeout": "Fallback rule, not a decision-maker: no human answered in time, so the agents' top-ranked option goes",
        }[auto]
        self.say("Human", f"{who}: {short_plan(plan)} for {did}.", "human", did)
        self.net(d, "human coordinator", plan["np_name"], "award", f"{who}: {plan['servings']} servings with {plan['driver_name']}.")
        self.dispatch(d, plan)
        return True

    # ---------------- shelter phones ----------------
    def phone_online(self, np_id):
        return self.live and time.time() - self.phones.get(np_id, 0) < PHONE_ONLINE_SECONDS

    def split(self, d, servings, to_name):
        """A shelter took only part of the food: keep that part on this donation, re-announce the rest."""
        f = d["food"]
        rest = f["servings"] - servings
        if rest <= 0:
            return None
        share = servings / f["servings"]
        lo, hi = f["weight_lbs"]
        d["food"] = dict(f, servings=servings, weight_lbs=[round(lo * share, 1), round(hi * share, 1)])
        rf = dict(f, servings=rest, weight_lbs=[round(lo * (1 - share), 1), round(hi * (1 - share), 1)])
        base = d["id"].split("-")[0]
        lot = sum(1 for x in self.donations if x["id"].split("-")[0] == base) + 1
        new = {
            "id": f"{base}-{lot}", "food": rf, "business": d["business"],
            "business_name": d["business_name"], "origin": dict(d["origin"]), "created": d["created"],
            "safe_until": d["safe_until"], "status": "new", "plan": None, "picked": False, "dissent": [],
            "options": [], "announced": True, "skip": list(d.get("skip", [])) + [],
        }
        self.donations.append(new)
        self.say("Result", f"Split {d['id']}: {servings} servings go to {to_name}; the other {rest} become {new['id']} "
                 "and are offered to the network again.", "result", d["id"])
        self.net(d, "coordinators", d["business_name"], "split",
                 f"{to_name} takes {servings}; {rest} servings re-announced as {new['id']}.")
        return new

    def dispatch(self, d, plan):
        """Ask the shelter first if someone is answering its phone; otherwise go straight away."""
        if plan.get("partial") and plan["servings"] < d["food"]["servings"]:
            new = self.split(d, plan["servings"], plan["np_name"])
            if new:
                new["skip"].append(plan["np"])   # that shelter already said how much it can take
        if plan.get("join") or not self.phone_online(plan["np"]):
            self.assign(d, plan)
            return
        dr = self.drivers[plan["driver"]]
        if dr["status"] == "free":
            dr["status"] = "reserved"   # hold the driver while the shelter decides
        d["ask"] = {"plan": plan, "asked_at": self.now}
        d["status"] = "awaiting_shelter"
        self.say("Contact", f"Asking {plan['np_name']} to accept {d['id']} ({d['food']['servings']} servings of "
                 f"{', '.join(d['food']['items'])}, arriving {plan['arrive_hhmm']}). Waiting for their reply.", "contact", d["id"])

    def respond(self, did, accept, servings=None):
        """A person answering a shelter's phone: accept all, accept part (a counter-offer), or decline."""
        d = self.get(did)
        if not d or d["status"] != "awaiting_shelter":
            return False
        plan = d.pop("ask")["plan"]
        n = self.nonprofits[plan["np"]]
        if accept:
            if servings is not None and 0 < int(servings) < d["food"]["servings"]:
                take = int(servings)
                self.net(d, n["name"], "coordinators", "counter", f"(by phone) We can take {take} of {d['food']['servings']}.")
                new = self.split(d, take, n["name"])
                if new:
                    new["skip"].append(n["id"])
            plan = self.make_plan(d, n, self.drivers[plan["driver"]])  # refresh the ETA: time passed while they decided
            self.say("Contact", f"{n['name']} accepted {d['food']['servings']} servings of {did}. Driver on the way, "
                     f"arriving {plan['arrive_hhmm']}.", "contact", did)
            self.net(d, n["name"], "coordinators", "accept", f"(by phone) Confirmed {d['food']['servings']} servings.")
            self.assign(d, plan)
            return True
        self._release(d, plan)
        d["status"] = "new"
        self.say("Contact", f"{n['name']} declined {did}.", "contact", did)
        self.decline(plan["np"])
        return True

    def _release(self, d, plan):
        dr = self.drivers[plan["driver"]]
        if dr["status"] == "reserved" and d.get("locked_driver") != dr["id"]:
            dr["status"] = "free"

    def shelter_view(self, np_id):
        self.phones[np_id] = time.time()
        n = self.nonprofits.get(np_id)
        if not n:
            return None
        asks = [{"donation": d["id"], "business": d["business_name"], "food": d["food"],
                 "arrive": d["ask"]["plan"]["arrive_hhmm"], "driver": d["ask"]["plan"]["driver_name"],
                 "minutes_left": d["safe_until"] - self.now,
                 "waiting": self.now - d["ask"]["asked_at"], "timeout": SHELTER_TIMEOUT}
                for d in self.donations if d["status"] == "awaiting_shelter" and d["ask"]["plan"]["np"] == np_id]
        coming = [{"donation": d["id"], "items": ", ".join(d["food"]["items"]), "servings": d["food"]["servings"],
                   "eta": d["plan"]["arrive_hhmm"], "driver": d["plan"]["driver_name"]}
                  for d in self.donations if d["status"] == "en_route" and d["plan"]["np"] == np_id]
        got = [r for r in self.records if r["recipient"] == n["name"]]
        return {"now": hhmm(self.now), "nonprofit": {k: n[k] for k in ("id", "name", "full", "open_until", "has_fridge",
                                                                         "capacity_servings", "received")},
                "asks": asks, "coming": coming, "received": got}

    def assign(self, d, plan):
        dr = self.drivers[plan["driver"]]
        if plan.get("join"):
            e = self.get(plan["join"])
            if not e or e["status"] != "en_route" or self.now >= e["t_pick"]:
                d["status"] = "new"   # that trip already left the pickup; renegotiate
                return
            extra = JOIN_EXTRA_MIN
            e["t_arr"] += extra       # the shared trip takes a little longer to load
            d.update(plan=plan, status="en_route", t_assign=e["t_assign"], t_pick=e["t_pick"],
                     t_arr=e["t_arr"], dest=e["dest"], origin=dict(e["origin"]))
            self.decide(d, "allowed", f"{d['id']} joins {e['id']}'s trip with {dr['name']} to {plan['np_name']}")
            self.say("Result", f"{d['id']} rides along with {e['id']}: one trip, two donations.", "result", d["id"])
            return
        dr["status"] = "busy"
        dr["leg_start"] = dict(dr.get("pos", pos(dr)))
        d["plan"] = plan
        d["status"] = "en_route"
        d["t_assign"] = self.now
        d["t_pick"] = self.now + plan["pick"]
        d["t_arr"] = self.now + plan["dur"]
        d["dest"] = pos(self.nonprofits[plan["np"]])
        d.pop("locked_driver", None)
        self.decide(d, "allowed", f"{short_plan(plan)} (arrives {plan['arrive_hhmm']}, {plan['slack']} min before unsafe)")

    def get(self, did):
        return next((d for d in self.donations if d["id"] == did), None)

    # ---------------- events ----------------
    def load_scenario(self, sc):
        self.scenario_name = sc["name"]
        self.events = sorted(sc["events"], key=lambda e: e["at"])
        setup = sc.get("setup", {})
        if "start" in setup:
            self.now = self.start = to_min(setup["start"])
        for np_id, fields in setup.get("nonprofits", {}).items():
            self.nonprofits[np_id].update(fields)
            if "open_until" in fields:
                self.nonprofits[np_id]["open_min"] = to_min(fields["open_until"])
        for dr_id, fields in setup.get("drivers", {}).items():
            self.drivers[dr_id].update(fields)
            self.drivers[dr_id]["pos"] = self.drivers[dr_id]["home"] = pos(self.drivers[dr_id])
        for dr_id in setup.get("drivers_off", []):
            self.drivers[dr_id]["status"] = "off"
        if setup.get("note"):
            self.say("System", setup["note"], "event")
        self.say("System", f"Scenario loaded: {sc['title']}.", "event")

    def run_event(self, e):
        t = e["type"]
        if t == "donation":
            self.add_donation(dict(e["food"]), e["business"])
        elif t == "decline":
            self.decline(e["nonprofit"])
        elif t == "cancel":
            self.cancel_driver(e["driver"])
        elif t == "new_pantry":
            self.add_pantry()
        elif t == "driver_joins":
            dr = dict(e["driver"])
            if dr["id"] not in self.drivers:
                self.drivers[dr["id"]] = dict(dr, status="free", home=pos(dr), pos=pos(dr))
                self.say("Directory", f"{dr['name']} started a shift ({dr['type']}, {dr['reliability']:.0%} reliable).", "event")
                if self.mesh and self.mesh.launcher:   # the new driver's own agent starts and joins the directory
                    self.mesh.launcher.spawn("driver", dr["id"], name=dr["name"], wait=8.0)
                    self.mesh.agents(fresh=True)
        elif t == "confirm":
            d = next((x for x in self.donations if x["business"] == e["business"] and x["status"] == "awaiting_info"), None)
            if d:
                self.confirm_allergens(d["id"], e.get("allergens"))

    # ---------------- insufficient evidence: ask the business ----------------
    def ask_business(self, d, gap):
        d["status"] = "awaiting_info"
        d["evidence_asked"] = True
        d["asked_about"] = gap["allergens"]
        d["answer_by"] = min(self.now + EVIDENCE_WAIT, d["safe_until"] - EVIDENCE_DEADLINE)
        self.outcomes["insufficient_evidence"] = self.outcomes.get("insufficient_evidence", 0) + 1
        for agent, text in gap["messages"]:
            self.say(agent, text, "propose", d["id"])
        self.say("Result", f"{d['id']}: not enough evidence to decide. Asking {d['business_name']}: "
                 f"\"Is this free of {gap['allergens']}?\" Will act on what we know by "
                 f"{hhmm(d['answer_by'])} if there's no answer.", "result", d["id"])

    def _mark_new_info(self, d, result, info):
        """The effect of new information: open the debate with what changed, then each agent says whether
        it changed its pick (compared with its final pick last time) and why."""
        result["new_info"] = info
        prev = next((n for n in reversed(self.negotiations) if n["donation"] == d["id"]), None)
        if not result.get("rounds"):
            return
        lines = [{"agent": "News", "type": "news", "text": f"New information: {info}."}]
        first = result["rounds"][0]["proposals"]
        before = prev["rounds"][-1]["proposals"] if prev and prev.get("rounds") else {}

        def name(pid):
            if not pid:
                return "nothing"
            np, dr = (pid.split("|") + [""])[:2]
            n, x = self.nonprofits.get(np), self.drivers.get(dr)
            return f"{n['name'] if n else np}" + (f" via {x['name']}" if x else "")
        for a in agents.AGENTS:
            was, now = before.get(a), first.get(a)
            if was and now and was != now:
                lines.append({"agent": a, "type": "revise", "text": f"That changes my pick: I wanted {name(was)}, now {name(now)}."})
            elif was and now:
                lines.append({"agent": a, "type": "revise", "text": f"Still {name(now)}; this doesn't change my pick."})
        result["rounds"][0]["messages"] = lines + result["rounds"][0]["messages"]

    def confirm_allergens(self, did, allergens=None):
        """The business answers. allergens=None means "can't confirm": keep treating them as present."""
        d = self.get(did)
        if not d or d["status"] != "awaiting_info":
            return False
        if allergens is None:
            self.say("World", f"{d['business_name']}: \"Sorry, we can't say for sure.\" Acting on what we know.", "event", did)
        else:
            d["food"]["allergens"] = list(allergens)
            d["food"]["allergens_unverified"] = False
            listed = ", ".join(allergens) or "none of the common ones"
            self.say("World", f"{d['business_name']} confirms the allergens: {listed}. New information; replanning.", "event", did)
            d["new_info"] = f"{d['business_name']} confirmed the allergens are only: {listed}"
        d["status"] = "new"
        return True

    def decline(self, np_id):
        n = self.nonprofits.get(np_id)
        if not n or n["full"]:
            return
        n["full"] = True
        self.say("World", f"{n['name']}: \"Sorry, we're full tonight.\"", "event")
        for d in self.donations:
            if d["status"] == "en_route" and d["plan"]["np"] == np_id:
                self._replan_en_route(d, f"{n['name']} is full")

    def _replan_en_route(self, d, why):
        dr = self.drivers[d["plan"]["driver"]]
        if self.now >= d["t_pick"]:
            d["picked"] = True
            d["origin"] = dict(dr["pos"])
            d["locked_driver"] = dr["id"]
            self.say("World", f"{d['id']}: {why}. {dr['name']} already has the food; replanning from here.", "event", d["id"])
            d["new_info"] = f"{why}, and {dr['name']} already has the food"
        else:
            dr["status"] = "free"
            self.say("World", f"{d['id']}: {why}. Replanning.", "event", d["id"])
            d["new_info"] = why
        d["status"] = "new"

    def cancel_driver(self, driver_id):
        dr = self.drivers.get(driver_id)
        if not dr or dr["status"] == "off":
            return
        carrying = any((d["status"] == "en_route" and d["plan"]["driver"] == driver_id and self.now >= d["t_pick"])
                       or (d.get("picked") and d.get("locked_driver") == driver_id
                           and d["status"] not in ("delivered", "spoiled", "expired"))  # turned away, food still on board
                       for d in self.donations)
        if carrying:
            return  # already has the food on board; finishes the trip
        old = dr["reliability"]
        dr["reliability"] = round(max(0.1, old - RELIABILITY_PENALTY), 2)
        dr["status"] = "off"
        self.say("World", f"{dr['name']} cancelled. Reliability {old:.0%} → {dr['reliability']:.0%}; every agent now sees that.", "event")
        for d in self.donations:
            if d["status"] == "awaiting_shelter" and d["ask"]["plan"]["driver"] == driver_id:
                d["new_info"] = f"{dr['name']} cancelled; reliability dropped from {old:.0%} to {dr['reliability']:.0%}"
                d.pop("ask")
                d["status"] = "new"
                self.say("World", f"{d['id']} needs a new driver.", "event", d["id"])
            if d["status"] == "en_route" and d["plan"]["driver"] == driver_id:
                for agent in sorted({x["agent"] for x in d.get("objections", []) if x["driver"] == driver_id}):
                    self.weights[agent] = round(self.weights[agent] + WEIGHT_BONUS, 2)
                    self.say("Adapt", f"{agent} warned that {dr['name']} might not show, and was right. "
                             f"{agent}'s vote now weighs {self.weights[agent]}.", "adapt", d["id"])
                d["status"] = "new"
                d["plan"] = None
                d["new_info"] = f"{dr['name']} cancelled; reliability dropped from {old:.0%} to {dr['reliability']:.0%}"
                self.say("World", f"{d['id']} needs a new driver.", "event", d["id"])

    def add_pantry(self):
        n = load("new_pantry.json")
        if n["id"] in self.nonprofits:
            return
        self._register(n)
        if self.mesh and self.mesh.launcher:   # the new pantry's own agent starts and joins the directory
            if self.mesh.launcher.spawn("shelter", n["id"], wait=8.0):
                self.say("Directory", f"{n['name']}'s agent registered in the agent directory.", "event")
            self.mesh.agents(fresh=True)   # discover it now, not on the next cache refresh
        for d in self.donations:
            if d["status"] in ("stuck", "awaiting_human"):
                d["status"] = "new"
                d["skip"] = []
                d["new_info"] = f"{n['name']} just joined the network"
            elif d["status"] == "en_route" and self.now < d["t_pick"] and self.policy == "agents":
                d["reconsider"] = True
                d["new_info"] = f"{n['name']} just joined the network"

    # ---------------- clock ----------------
    def tick(self, minutes=1, plan_inline=True):
        for _ in range(minutes):
            self.now += 1
            while self.events and self.events[0]["at"] + self.start <= self.now:
                self.run_event(self.events.pop(0))
            for d in self.donations:
                if d["status"] == "en_route":
                    self._move(d)
                    if self.now >= d["t_arr"]:
                        self.arrive(d)
            for d in self.donations:
                if d["status"] in ("new", "stuck", "awaiting_human", "awaiting_info", "awaiting_shelter") and self.now > d["safe_until"]:
                    if d.get("ask"):
                        self._release(d, d.pop("ask")["plan"])
                    self.expire(d)
                elif d["status"] == "awaiting_shelter" and self.now - d["ask"]["asked_at"] >= SHELTER_TIMEOUT:
                    plan = d.pop("ask")["plan"]
                    self._release(d, plan)
                    d.setdefault("skip", []).append(plan["np"])
                    d["status"] = "new"
                    self.say("Contact", f"No answer from {plan['np_name']} after {SHELTER_TIMEOUT} min. Trying elsewhere.", "contact", d["id"])
                elif d["status"] == "awaiting_human" and d["options"] and self.now >= self.last_call(d):
                    # Nobody answered and waiting longer would make every option too late: act now,
                    # on the agents' best-ranked option that can still arrive safely.
                    self.outcomes["human_timeout"] = self.outcomes.get("human_timeout", 0) + 1
                    ok = [o for o in d["options"] if self.now + o["dur"] <= d["safe_until"] - SAFETY_MARGIN]
                    if not ok or not self.approve(d["id"], ok[0]["id"], auto="timeout"):
                        d["status"] = "new"
                elif d["status"] == "awaiting_info" and self.now >= d["answer_by"]:
                    self.say("System", f"{d['id']}: no answer from {d['business_name']} in time. "
                             "Acting on what we know: treating the allergens as present.", "human", d["id"])
                    d["status"] = "new"
                elif d["status"] == "stuck" and self.now % 5 == 0:
                    d["status"] = "new"  # retry: a driver may have freed up
            if plan_inline:
                for d in self.needs_planning():
                    self.plan(d)

    def _move(self, d):
        if d["plan"].get("join"):
            return  # the trip it joined moves the driver
        dr = self.drivers[d["plan"]["driver"]]
        if self.now < d["t_pick"]:
            span = max(1, d["t_pick"] - d["t_assign"])
            dr["pos"] = lerp(dr["leg_start"], d["origin"], (self.now - d["t_assign"]) / span)
        else:
            d["picked"] = True
            span = max(1, d["t_arr"] - d["t_pick"])
            dr["pos"] = lerp(d["origin"], d["dest"], (self.now - d["t_pick"]) / span)

    def arrive(self, d):
        n = self.nonprofits[d["plan"]["np"]]
        dr = self.drivers[d["plan"]["driver"]]
        dr["pos"] = pos(n)
        f = d["food"]
        turned_away = n["full"] or self.now > n["open_min"] or n["received"] + f["servings"] > n["capacity_servings"]
        if turned_away:
            why = "full" if n["full"] else "closed" if self.now > n["open_min"] else "out of room"
            d["picked"] = True
            d["origin"] = pos(n)
            d["locked_driver"] = dr["id"]
            d["status"] = "new"
            d.setdefault("skip", []).append(n["id"])
            self.say("World", f"{d['id']} arrived at {n['name']} but it's {why}. Turned away.", "event", d["id"])
            return
        if not any(x is not d and x["status"] == "en_route" and x["plan"]["driver"] == dr["id"] for x in self.donations) \
                and not any(x is not d and x.get("locked_driver") == dr["id"]
                            and x["status"] not in ("delivered", "spoiled", "expired") for x in self.donations):
            dr["status"] = "free"
        if d["plan"]["cost"]:
            self.impact["cost"] += d["plan"]["cost"]
        safe = self.now <= d["safe_until"] and (not f["needs_cold"] or n["has_fridge"])
        if not safe:
            reason = "arrived after its safe window" if self.now > d["safe_until"] else "no fridge to keep it cold"
            self.impact["spoiled"] += f["servings"]
            d["status"] = "spoiled"
            self.say("World", f"{d['id']} delivered to {n['name']} but {reason}. {f['servings']} servings unsafe to serve.", "event", d["id"])
            return
        n["received"] += f["servings"]
        n.setdefault("received_by_category", {})
        n["received_by_category"][f["category"]] = n["received_by_category"].get(f["category"], 0) + f["servings"]
        n["last_donation_days"] = 0
        self.impact["meals"] += f["servings"]
        self.impact["lbs"] += sum(f["weight_lbs"]) / 2
        self.impact["orgs"].add(n["id"])
        d["status"] = "delivered"
        d["t_done"] = self.now
        if f["safe_minutes"] <= 180:  # perishable food only; packaged food would swamp the average
            self.impact["spare"] = self.impact.get("spare", 0) + (d["safe_until"] - self.now)
            self.impact["perishable"] = self.impact.get("perishable", 0) + 1
        self.records.append({
            "donation": d["id"], "date": datetime.date.today().isoformat(), "donor": d["business_name"], "recipient": n["name"],
            "items": ", ".join(f["items"]), "category": f["category"], "servings": f["servings"],
            "weight_lbs": f"{f['weight_lbs'][0]:g}–{f['weight_lbs'][1]:g}", "picked_up": hhmm(d["t_pick"]),
            "delivered": hhmm(self.now), "transport": d["plan"]["driver_type"],
        })
        self.say("World", f"{d['id']} delivered to {n['name']}: {f['servings']} meals. Donation record created.", "delivered", d["id"])

    def expire(self, d):
        if d.get("locked_driver"):
            self.drivers[d.pop("locked_driver")]["status"] = "free"
        d["status"] = "expired"
        self.impact["spoiled"] += d["food"]["servings"]
        self.say("World", f"{d['id']} passed its safe time before delivery. {d['food']['servings']} servings lost.", "event", d["id"])

    def done(self):
        return not self.events and all(d["status"] in ("delivered", "spoiled", "expired") for d in self.donations)

    # ---------------- output ----------------
    def metrics(self):
        return {
            "meals_delivered_safely": self.impact["meals"],
            "servings_lost": self.impact["spoiled"],
            "money_spent": round(self.impact["cost"], 2),
            "shelters_fed": len(self.impact["orgs"]),
            "human_escalations": self.impact["escalations"],
            "deliveries": self.impact.get("perishable", 0),
            "spare_minutes": self.impact.get("spare", 0),
            "outcomes": dict(self.outcomes),
        }

    def to_json(self):
        drivers = []
        for dr in self.drivers.values():
            p = dr.get("pos", pos(dr))
            drivers.append({k: dr[k] for k in ("id", "name", "type", "status", "reliability")} | p)
        dons = []
        for d in self.donations:
            x = {k: d.get(k) for k in ("id", "food", "business_name", "status", "plan", "options", "origin", "dest",
                                       "picked", "why", "asked_about")}
            x["safe_until"] = hhmm(d["safe_until"])
            x["minutes_left"] = d["safe_until"] - self.now
            if d["status"] == "awaiting_human" and d.get("options"):
                x["decide_by"] = hhmm(self.last_call(d))   # after this the fallback rule acts
            dons.append(x)
        return {
            "now": hhmm(self.now), "scenario": self.scenario_name, "busy": self.busy,
            "nonprofits": [{k: n[k] for k in ("id", "name", "lat", "lng", "accepts", "has_fridge", "open_until",
                                              "capacity_servings", "received", "full", "last_donation_days")}
                           for n in self.nonprofits.values()],
            "businesses": list(self.businesses.values()),
            "drivers": drivers, "donations": dons,
            "feed": self.feed[-120:], "decisions": self.decisions[-60:], "records": self.records,
            "negotiation": self.negotiation, "negotiations": self.negotiations, "weights": self.weights,
            "deliberating": None if self.live_rounds is None else {
                "donation": self.live_donation, "rounds": [dict(r, messages=list(r["messages"])) for r in list(self.live_rounds)]},
            "outcomes": self.outcomes,
            "network": self.network[-200:],
            "agents_online": {"businesses": len(self.businesses), "shelters": len(self.nonprofits),
                              "drivers": sum(1 for x in self.drivers.values() if x["status"] != "off"), "coordinators": 3},
            "impact": {**{k: v for k, v in self.impact.items() if k != "orgs"}, "orgs": len(self.impact["orgs"]),
                       "lbs": round(self.impact["lbs"], 1), "cost": round(self.impact["cost"], 2)},
            "pending": len(self.events),
        }


def short_plan(p):
    return f"{p['np_name']} via {p['driver_name']}"


def baseline_plan(world, d):
    """The simple approach to beat, as a busy coordinator with a phone list would do it:
    nearest shelter that takes this food type, is open right now, isn't full and has room,
    with the nearest free driver who agrees to the trip. It never retries a shelter that already turned this food away.
    It does NOT check fridges, allergens, whether food arrives in time or before closing,
    driver reliability, cost, or which shelter needs food most. There is no negotiation."""
    f = d["food"]
    skip = d.get("skip", [])
    nps = [n for n in world.nonprofits.values()
           if f["category"] in n["accepts"] and not n["full"] and n["open_min"] > world.now
           and n["capacity_servings"] - n["received"] - world.committed(n["id"]) >= f["servings"]
           and n["id"] not in skip]
    if not nps:
        return None
    n = min(nps, key=lambda n: km(d["origin"], n))
    # drivers still have to agree to the trip: a volunteer asked to go too far says no
    options = [(dr, world.make_plan(d, n, dr)) for dr in world.usable_drivers(d, n)]
    options = [(dr, p) for dr, p in options if network.driver_bid(world, dr, d, n, p)["willing"]]
    if not options:
        return None
    dr, p = min(options, key=lambda x: km(x[0].get("pos", x[0]), d["origin"]))
    return p
