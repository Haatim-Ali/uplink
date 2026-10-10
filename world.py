"""The simulated world: directory, safety rules, drivers, clock, events, impact.

The agents are real; the world around them is simulated (1 tick = 1 minute).
"""
import itertools
import json
import math
import os

import agents
from config import (COST_LIMIT, HANDOFF_MIN, HUMAN_TIMEOUT, RELIABILITY_PENALTY, SAFETY_MARGIN, SPEED_KMH,
                    START, WEIGHT_BONUS)

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")


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
        self.now = START
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
        self.impact = {"meals": 0, "lbs": 0.0, "cost": 0.0, "spoiled": 0, "escalations": 0, "orgs": set()}
        self.negotiation = None
        self.negotiations = []
        self.events = []
        self.scenario_name = None
        self.busy = False
        self._ids = itertools.count(1)
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
        if n["full"]:
            return "reported full"
        if n["open_min"] <= self.now:
            return "closed"
        room = n["capacity_servings"] - n["received"] - self.committed(n["id"])
        if room < food["servings"]:
            return f"only room for {max(room, 0)} servings"
        return None

    def committed(self, np_id, exclude=None):
        """Servings already on their way to this nonprofit."""
        return sum(d["food"]["servings"] for d in self.donations
                   if d["status"] == "en_route" and d["plan"]["np"] == np_id and d is not exclude)

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
        }

    def usable_drivers(self, d, n):
        out = []
        for dr in self.drivers.values():
            if d.get("locked_driver"):
                if dr["id"] != d["locked_driver"]:
                    continue
            elif dr["status"] != "free":
                continue
            if dr.get("owner") and dr["owner"] != n["id"]:
                continue
            out.append(dr)
        return out

    def safe_plans(self, d, log=True):
        """Every (nonprofit, driver) plan that passes the safety rules."""
        ok, removed = self.search_directory(d["food"])
        plans, late = [], 0
        for n in ok:
            for dr in self.usable_drivers(d, n):
                p = self.make_plan(d, n, dr)
                if p["arrive"] > d["safe_until"] - SAFETY_MARGIN or p["arrive"] > n["open_min"]:
                    late += 1
                    continue
                plans.append(p)
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
        self.feed.append({"time": hhmm(self.now), "agent": agent, "type": kind, "text": text, "donation": donation})
        self.feed = self.feed[-300:]

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
        if not plans:
            d["reconsider"] = False
            if d["status"] == "new":
                d["status"] = "stuck"
                self.impact["escalations"] += 1
                self.say("Human", f"{d['id']}: no safe plan exists right now. A coordinator should step in.", "human", d["id"])
            return None
        return plans

    def decide_plan(self, d, plans):
        if self.policy == "baseline":
            return baseline_plan(self, d)
        return agents.negotiate(self, d, plans)

    def finish(self, d, plans, result):
        if self.policy == "baseline":
            if result is None:
                d["status"] = "stuck"
                return
            self.say("Baseline", f"{d['id']}: nearest shelter {result['np_name']}, nearest driver {result['driver_name']}.", "result", d["id"])
            self.assign(d, result)
            return

        reconsidering = d.get("reconsider") and d["status"] == "en_route"
        d["reconsider"] = False
        self.negotiation = dict(result, donation=d["id"], food=", ".join(d["food"]["items"]),
                                time=hhmm(self.now), seq=len(self.negotiations) + 1)
        self.negotiations.append(self.negotiation)
        self.negotiations = self.negotiations[-12:]
        for rnd in result["rounds"]:
            for m in rnd["messages"]:
                self.say(m["agent"], f"R{rnd['round']} · {m['text']}", m["type"], d["id"])
        plan = result["plan"]
        if result["outcome"] == "escalate" or (plan and plan["cost"] > COST_LIMIT):
            why = "no agreement after 3 rounds" if result["outcome"] == "escalate" else f"cost ${plan['cost']:.2f} is over the ${COST_LIMIT} limit"
            d["options"] = result["options"]
            if reconsidering:
                self.say("Result", f"{d['id']}: no agreement on a better plan; keeping the current one.", "result", d["id"])
                d.pop("locked_driver", None)
                return
            d["status"] = "awaiting_human"
            self.impact["escalations"] += 1
            opts = " or ".join(short_plan(o) for o in d["options"])
            self.say("Human", f"{d['id']}: asking a coordinator ({why}). Options: {opts}.", "human", d["id"])
            if not self.live:
                self.approve(d["id"], d["options"][0]["id"], auto=True)
            return
        label = {"consensus": "Agreed 3 of 3", "majority": "Majority", "urgent": "Time is short, acting on best-supported plan"}[result["outcome"]]
        d["dissent"] = result["dissent"]
        # remember every reliability objection raised in any round, to check later who was right
        d["objections"] = [{"agent": a, "driver": pid.split("|")[1]}
                           for rnd in result["rounds"] for pid, vs in rnd["votes"].items()
                           for a, v in vs.items() if v["kind"] == "reliability"]
        if result["dissent"]:
            label += " · dissent kept on record: " + ", ".join(x["agent"] for x in result["dissent"])
        if reconsidering:
            d.pop("locked_driver", None)
            if plan["np"] == d["plan"]["np"]:
                self.say("Result", f"{d['id']}: new information reviewed; current plan still best.", "result", d["id"])
                return
            self.say("Result", f"{label}: reroute {d['id']} to {plan['np_name']} (new information).", "result", d["id"])
            self.drivers[d["plan"]["driver"]]["status"] = "free"
            self.assign(d, plan)
            return
        self.say("Result", f"{label}: {short_plan(plan)}, arrives {plan['arrive_hhmm']}"
                 + (f", ${plan['cost']:.2f}" if plan["cost"] else ", free") + ".", "result", d["id"])
        self.assign(d, plan)

    def approve(self, did, plan_id, auto=False):
        d = self.get(did)
        if not d or d["status"] != "awaiting_human":
            return False
        plan = next((o for o in d["options"] if o["id"] == plan_id), None)
        if not plan:
            return False
        dr = self.drivers[plan["driver"]]
        if dr["status"] != "free" and d.get("locked_driver") != dr["id"]:
            d["status"] = "new"  # option no longer valid: renegotiate
            return False
        who = "Auto-approved" if auto else "Coordinator approved"
        self.say("Human", f"{who}: {short_plan(plan)} for {did}.", "human", did)
        self.assign(d, plan)
        return True

    def assign(self, d, plan):
        dr = self.drivers[plan["driver"]]
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
        else:
            dr["status"] = "free"
            self.say("World", f"{d['id']}: {why}. Replanning.", "event", d["id"])
        d["status"] = "new"

    def cancel_driver(self, driver_id):
        dr = self.drivers.get(driver_id)
        if not dr or dr["status"] == "off":
            return
        carrying = any(d["status"] == "en_route" and d["plan"]["driver"] == driver_id and self.now >= d["t_pick"]
                       for d in self.donations)
        if carrying:
            return  # already has the food on board; finishes the trip
        old = dr["reliability"]
        dr["reliability"] = round(max(0.1, old - RELIABILITY_PENALTY), 2)
        dr["status"] = "off"
        self.say("World", f"{dr['name']} cancelled. Reliability {old:.0%} → {dr['reliability']:.0%}; every agent now sees that.", "event")
        for d in self.donations:
            if d["status"] == "en_route" and d["plan"]["driver"] == driver_id:
                for agent in sorted({x["agent"] for x in d.get("objections", []) if x["driver"] == driver_id}):
                    self.weights[agent] = round(self.weights[agent] + WEIGHT_BONUS, 2)
                    self.say("Adapt", f"{agent} warned that {dr['name']} might not show, and was right. "
                             f"{agent}'s vote now weighs {self.weights[agent]}.", "adapt", d["id"])
                d["status"] = "new"
                d["plan"] = None
                self.say("World", f"{d['id']} needs a new driver.", "event", d["id"])

    def add_pantry(self):
        n = load("new_pantry.json")
        if n["id"] in self.nonprofits:
            return
        self._register(n)
        for d in self.donations:
            if d["status"] in ("stuck", "awaiting_human"):
                d["status"] = "new"
            elif d["status"] == "en_route" and self.now < d["t_pick"] and self.policy == "agents":
                d["reconsider"] = True

    # ---------------- clock ----------------
    def tick(self, minutes=1, plan_inline=True):
        for _ in range(minutes):
            self.now += 1
            while self.events and self.events[0]["at"] + START <= self.now:
                self.run_event(self.events.pop(0))
            for d in self.donations:
                if d["status"] == "en_route":
                    self._move(d)
                    if self.now >= d["t_arr"]:
                        self.arrive(d)
            for d in self.donations:
                if d["status"] in ("new", "stuck", "awaiting_human") and self.now > d["safe_until"]:
                    self.expire(d)
                elif d["status"] == "awaiting_human" and d["safe_until"] - self.now <= HUMAN_TIMEOUT and d["options"]:
                    self.say("System", f"{d['id']}: no human answer and food is running out of time. Stop and act.", "human", d["id"])
                    if not self.approve(d["id"], d["options"][0]["id"], auto=True):
                        d["status"] = "new"
                elif d["status"] == "stuck" and self.now % 5 == 0:
                    d["status"] = "new"  # retry: a driver may have freed up
            if plan_inline:
                for d in self.needs_planning():
                    self.plan(d)

    def _move(self, d):
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
            self.say("World", f"{d['id']} arrived at {n['name']} but it's {why}. Turned away.", "event", d["id"])
            return
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
        n["last_donation_days"] = 0
        self.impact["meals"] += f["servings"]
        self.impact["lbs"] += sum(f["weight_lbs"]) / 2
        self.impact["orgs"].add(n["id"])
        d["status"] = "delivered"
        d["t_done"] = self.now
        self.records.append({
            "donation": d["id"], "date": "2026-10-10", "donor": d["business_name"], "recipient": n["name"],
            "items": ", ".join(f["items"]), "category": f["category"], "servings": f["servings"],
            "weight_lbs": f"{f['weight_lbs'][0]:g}–{f['weight_lbs'][1]:g}", "picked_up": hhmm(d["t_pick"]),
            "delivered": hhmm(self.now), "transport": d["plan"]["driver_type"],
        })
        self.say("World", f"{d['id']} delivered to {n['name']}: {f['servings']} meals. Donation record created.", "delivered", d["id"])

    def expire(self, d):
        if d.get("locked_driver"):
            self.drivers[d["locked_driver"]]["status"] = "free"
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
        }

    def to_json(self):
        drivers = []
        for dr in self.drivers.values():
            p = dr.get("pos", pos(dr))
            drivers.append({k: dr[k] for k in ("id", "name", "type", "status", "reliability")} | p)
        dons = []
        for d in self.donations:
            x = {k: d.get(k) for k in ("id", "food", "business_name", "status", "plan", "options", "origin", "dest", "picked")}
            x["safe_until"] = hhmm(d["safe_until"])
            x["minutes_left"] = d["safe_until"] - self.now
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
            "impact": {**{k: v for k, v in self.impact.items() if k != "orgs"}, "orgs": len(self.impact["orgs"]),
                       "lbs": round(self.impact["lbs"], 1), "cost": round(self.impact["cost"], 2)},
            "pending": len(self.events),
        }


def short_plan(p):
    return f"{p['np_name']} via {p['driver_name']}"


def baseline_plan(world, d):
    """The simple approach to beat: nearest shelter that takes this food type, nearest free driver.
    No fridge, hours, allergen, capacity or timer checks, and no negotiation."""
    nps = [n for n in world.nonprofits.values() if d["food"]["category"] in n["accepts"] and not n["full"]]
    if not nps:
        return None
    n = min(nps, key=lambda n: km(d["origin"], n))
    drivers = world.usable_drivers(d, n)
    if not drivers:
        return None
    dr = min(drivers, key=lambda dr: km(dr.get("pos", dr), d["origin"]))
    return world.make_plan(d, n, dr)
