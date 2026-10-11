"""Three agents with competing goals negotiate a plan. No agent has the final say.

Protocol (Level 3, no central decision-maker):
  0. Safety rules (code, in world.py) have already removed every unsafe plan.
  1. Each round, every agent proposes a plan. Round 1 = its own favourite; in later
     rounds it concedes toward plans the others can live with.
  2. Every agent votes accept/object on every proposed plan, with a reason.
  3. A plan everyone accepts wins (consensus). If time is short, act on the plan
     with the most support ("stop and act"). After 3 rounds, a weighted majority
     wins and the dissent is recorded. Otherwise, ask a human.

Consensus is not always right. Each agent also has a red line (a veto): a plan
it will never accept, and that a majority cannot push through. The negotiation
can therefore end four ways besides agreement:
  - urgent:        time is short, act on the best-supported plan nobody vetoed
  - unacceptable:  a majority wants a plan the third agent vetoes -> ask a human
  - irreconcilable: no plan has majority support after 3 rounds -> ask a human
  - insufficient evidence: the decision hinges on a fact nobody has confirmed
    (see evidence_gap) -> ask the business before committing

Adaptation: an agent whose objection later proves right gets more vote weight
(world.weights), and drivers who cancel lose reliability, which every agent sees.

Set LLM_AGENTS=1 (plus an API key) to have each agent's proposal, votes and
reasons come from the model; rules are the fallback for any failed call.
"""
import os
from concurrent.futures import ThreadPoolExecutor

import llm
from config import CONCESSION, JOIN_BONUS, THRESHOLDS, TIGHT_SLACK, URGENT_MINUTES

AGENTS = ["Speed", "Cost", "Need"]
GIVE_UP_MARGIN = 0.15   # a Claude agent accepting a plan this far below its bar is overruled by its rules vote
GOALS = {
    "Speed": "get the food there fast and reliably, with a big safety margin before it spoils",
    "Cost": "spend as little money as possible (volunteers and nonprofit vans are free; paid couriers cost money)",
    "Need": "send food where it helps most: shelters that have waited longest for a donation and have room",
}
# red lines: an agent vetoes any plan past these, in every round
SPEED_MIN_SLACK = 10       # minutes to spare before the food is unsafe
SPEED_MIN_RELIABILITY = 0.5
COST_MAX_USD = 20          # per-donation budget for paid drivers
NEED_WAITING_DAYS = 4      # Need vetoes feeding a shelter fed today while another has waited this long
EVIDENCE_MIN_MINUTES = 45  # only stop to ask for missing facts if at least this much time is left
RED_LINES = {
    "Speed": f"never accept under {SPEED_MIN_SLACK} min to spare or a driver under {SPEED_MIN_RELIABILITY:.0%} reliable",
    "Cost": f"never accept a plan over ${COST_MAX_USD}",
    "Need": f"never accept feeding a shelter that got food today while another has waited {NEED_WAITING_DAYS}+ days",
}


def clamp(x):
    return max(0.0, min(1.0, x))


def score(agent, world, d, p):
    remaining = max(1.0, d["safe_until"] - world.now)
    frac = p.get("servings", d["food"]["servings"]) / d["food"]["servings"]   # share a counter-offer takes
    if agent == "Speed":   # a partial take leaves food still waiting for a home: riskier
        return clamp(p["slack"] / remaining) * (0.6 + 0.4 * p["reliability"]) * (0.6 + 0.4 * frac)
    if agent == "Cost":    # a partial take means paying for another trip for the rest: price it per serving moved
        effective = p["cost"] / max(frac, 0.2)
        base = (1 - min(effective, 30) / 30) * (0.55 + 0.45 * p["reliability"]) * (0.7 + 0.3 * frac)
        return clamp(base + (JOIN_BONUS if p.get("join") else 0))  # a combined trip also saves a driver
    n = world.nonprofits[p["np"]]
    incoming = world.committed(n["id"])
    room = 1 - (n["received"] + incoming) / max(1, n["capacity_servings"])
    days = 0 if incoming else n["last_donation_days"]  # food already on its way counts as fed
    return clamp(0.7 * min(days, 5) / 5 + 0.3 * room)


def fed_recently(world, np_id):
    return world.nonprofits[np_id]["last_donation_days"] == 0 or world.committed(np_id) > 0


def red_line(agent, world, d, p, plans):
    """The agent's hard limit. Returns a veto reason, or None if the plan is tolerable."""
    if agent == "Speed":
        if p["slack"] < SPEED_MIN_SLACK:
            return f"Veto: only {p['slack']} min to spare. One delay and {d['food']['servings']} servings spoil."
        if p["reliability"] < SPEED_MIN_RELIABILITY:
            return f"Veto: {p['driver_name']} is {p['reliability']:.0%} reliable. I won't bet this food on a likely no-show."
        return None
    if agent == "Cost":
        if p["cost"] > COST_MAX_USD:
            return f"Veto: ${p['cost']:.2f} is over our ${COST_MAX_USD} budget for one donation."
        return None
    if not fed_recently(world, p["np"]):
        return None
    waiting = [world.nonprofits[q["np"]] for q in plans if not fed_recently(world, q["np"])]
    waiting = [n for n in waiting if n["last_donation_days"] >= NEED_WAITING_DAYS]
    if not waiting:
        return None
    w = max(waiting, key=lambda n: n["last_donation_days"])
    return (f"Veto: {p['np_name']} already got food today while {w['name']} has waited "
            f"{w['last_donation_days']} days. That's not a fair split.")


def evidence_gap(world, d, strict, relaxed):
    """Insufficient evidence: is the decision hanging on a fact nobody has confirmed?

    strict  = safe plans assuming the unconfirmed allergens ARE present (what safety enforces)
    relaxed = safe plans if the business confirms they are not
    If some agent's best plan exists only in `relaxed` and there's time to ask, the agents
    agree to stop and ask instead of guessing. Returns feed messages, or None to go ahead.
    """
    if not relaxed or d.get("evidence_asked"):
        return None
    left = d["safe_until"] - world.now
    if left < EVIDENCE_MIN_MINUTES:
        return None
    strict_ids = {p["id"] for p in strict}
    S = all_scores(world, d, relaxed)
    blocked = {}
    for a in AGENTS:
        best = max(relaxed, key=lambda p: S[p["id"]][a])
        if best["id"] not in strict_ids:
            blocked[a] = best
    if not blocked:
        return None
    allergens = ", ".join(sorted({x for p in blocked.values()
                                  for x in world.nonprofits[p["np"]].get("avoid_allergens", [])})) or "allergens"
    msgs = []
    for a, p in blocked.items():
        n = world.nonprofits[p["np"]]
        why = (f"has waited {n['last_donation_days']} days" if a == "Need" else
               f"is the fastest option ({p['dur']} min)" if a == "Speed" else f"costs ${p['cost']:.2f}")
        msgs.append((a, f"My best option, {p['np_name']}, {why}, but it's ruled out only because nobody "
                        f"has confirmed this food is free of {allergens}. I won't guess: let's ask the business."))
    for a in AGENTS:
        if a in blocked:
            continue
        if a == "Speed":
            msgs.append((a, f"Agreed. {left} min left, so we can afford a few minutes to ask. "
                            "If there's no answer in time, we act on what we know."))
        elif a == "Cost":
            msgs.append((a, "Agreed. Asking costs nothing."))
        else:
            msgs.append((a, "Agreed. Better information beats a guess here."))
    return {"messages": msgs, "allergens": allergens}


def all_scores(world, d, plans):
    return {p["id"]: {a: round(score(a, world, d, p), 3) for a in AGENTS} for p in plans}


def short(p):
    return f"{p['np_name']} via {p['driver_name']}"


def propose_reason(agent, p, world, compromise=False):
    if compromise:
        why = propose_reason(agent, p, world)
        return "Not my first choice, but I can live with it to reach agreement: " + why[0].lower() + why[1:]
    tail = f" (they offered to take {p['servings']}, not all of it)" if p.get("partial") else ""
    return _propose_reason(agent, p, world) + tail


def _propose_reason(agent, p, world):
    if agent == "Speed":
        return f"Arrives in {p['dur']} min with {p['slack']} min to spare ({p['reliability']:.0%} reliable)."
    if agent == "Cost":
        if p.get("join"):
            return f"Ride along with {p['join']}: no extra trip, and another driver stays free for the next donation."
        return "Costs nothing." if p["cost"] == 0 else f"${p['cost']:.2f} is the lowest cost I can find."
    n = world.nonprofits[p["np"]]
    room = n["capacity_servings"] - n["received"] - world.committed(n["id"])
    if world.committed(n["id"]):
        return f"{n['name']} already has food on the way, but it still has room for {room} servings. Which shelter matters to me, not which driver."
    # contrast with the shelter fed most recently, so it's clear what this choice is weighed against
    others = [o for o in world.nonprofits.values() if o["id"] != n["id"] and not o.get("full")]
    fresh = min(others, key=lambda o: (o["last_donation_days"] - (1 if world.committed(o["id"]) else 0)), default=None)
    vs = ""
    if fresh and (fresh["last_donation_days"] < n["last_donation_days"] or world.committed(fresh["id"])):
        vs = f" {fresh['name']} {'already has food coming' if world.committed(fresh['id']) else _fed(fresh['last_donation_days'])}."
    return f"{n['name']} {_waited(n['last_donation_days'])} and has room for {room} more servings.{vs} Which shelter matters to me, not which driver."


def _fed(days):
    return "got food today" if days == 0 else "got food yesterday" if days == 1 else f"got food {days} days ago"


def _waited(days):
    return "got food today" if days == 0 else "has waited a day" if days == 1 else f"has waited {days} days for food"


def accept_reason(agent, p, world):
    """Why an agent can live with a plan, in its own terms."""
    if agent == "Speed":
        return f"Accept: arrives with {p['slack']} min to spare and {p['driver_name']} is {p['reliability']:.0%} reliable."
    if agent == "Cost":
        return "Accept: costs nothing." if p["cost"] == 0 else f"Accept: ${p['cost']:.2f} is close enough to the cheapest option."
    n = world.nonprofits[p["np"]]
    if world.committed(n["id"]) or n["last_donation_days"] == 0:
        return f"Accept, reluctantly: {n['name']} isn't the one that needs it most, but the others can live with this."
    return f"Accept: {n['name']} {_waited(n['last_donation_days'])}. Any safe driver is fine with me."


def object_reason(agent, p, best, world):
    """Return (text, kind). kind is used later to check whether the objection proved right."""
    if agent == "Speed":
        if p["reliability"] < 0.75 or (p["slack"] < TIGHT_SLACK and p["reliability"] < 0.9):
            return (f"Object: {p['driver_name']} is only {p['reliability']:.0%} reliable and there's just {p['slack']} min "
                    "of margin; a no-show would spoil this food."), "reliability"
        return f"Object: only {p['slack']} min margin; {short(best)} leaves {best['slack']}.", "time"
    if agent == "Cost":
        if p["cost"] <= best["cost"]:
            return (f"Object: free, but {p['driver_name']} is only {p['reliability']:.0%} reliable. "
                    "A no-show means paying a courier to rescue it."), "reliability"
        return f"Object: ${p['cost']:.2f} when {short(best)} costs ${best['cost']:.2f} and is also safe.", "cost"
    n, bn = world.nonprofits[p["np"]], world.nonprofits[best["np"]]
    mine = "already has food on the way" if world.committed(n["id"]) else _fed(n["last_donation_days"])
    room = bn["capacity_servings"] - bn["received"] - world.committed(bn["id"])
    return (f"Object: {p['np_name']} {mine}, while {bn['name']} {_waited(bn['last_donation_days'])} "
            f"and has room for {room}. Send it where it's needed."), "need"


def _rules_round(world, d, plans, S, V, r):
    proposals = {}
    lam = CONCESSION[r]
    for a in AGENTS:
        others = [o for o in AGENTS if o != a]
        # never propose past your own red line; after round 1, also steer clear of plans others vetoed
        pool = [p for p in plans if not V[p["id"]][a]] or plans
        if r > 0:
            pool = [p for p in pool if not any(V[p["id"]][o] for o in others)] or pool
        proposals[a] = max(
            pool,
            key=lambda p: (1 - lam) * S[p["id"]][a] + lam * min(S[p["id"]][o] for o in others) + 1e-3 * sum(S[p["id"]].values()),
        )["id"]
    return proposals


def _rules_vote(agent, pid, S, best_score, r, plan=None):
    if agent == "Speed" and plan and plan["slack"] < TIGHT_SLACK and plan["reliability"] < 0.9:
        return False  # tight margin + unreliable driver: Speed won't sign off
    return S[pid][agent] >= THRESHOLDS[r] * best_score[agent]


# ---------- optional LLM-driven agents ----------

def _table(world, d, plans, S, agent, best=None):
    """Each agent sees only the facts its own goal is about, plus how good each plan is for it.
    (Showing everyone everything made Claude agents argue each other's cases.)"""
    best = best if best is not None else max((S[p["id"]][agent] for p in plans), default=1) or 1
    lines = []
    for p in plans:
        share = S[p["id"]][agent] / best if best else 0
        if agent == "Speed":
            facts = f"arrives in {p['dur']} min, {p['slack']} min of margin before unsafe, driver {p['reliability']:.0%} reliable"
        elif agent == "Cost":
            facts = f"costs ${p['cost']:.2f}, driver {p['reliability']:.0%} reliable (a no-show means paying a courier to rescue it)"
        else:
            n = world.nonprofits[p["np"]]
            room = n["capacity_servings"] - n["received"] - world.committed(n["id"])
            fed = "already has food on the way" if world.committed(n["id"]) else ("got food today" if n["last_donation_days"] == 0 else f"last got food {n['last_donation_days']} days ago")
            facts = f"shelter {fed}, room for {room} servings"
        lines.append(f"{p['id']}: {p['np_name']} via {p['driver_name']} | {facts} | {round(100 * share)}% of your best option")
    return "\n".join(lines)


_VOICE = {
    "Speed": "You only care about getting the food there fast and safely: arrival time, margin, and whether the driver shows up. "
             "You don't care about price or which shelter, so never argue about those.",
    "Cost": "You only care about money: what the trip costs, and the risk of paying a courier to rescue food after a no-show. "
            "You don't care about speed or which shelter, so never argue about those.",
    "Need": "You only care about which shelter gets the food: the one that has waited longest and has room. "
            "You don't care about price or which driver, so never argue about those.",
}


def _llm_shortlist(plans, S, limit=8):
    keep = {max(plans, key=lambda p: S[p["id"]][a])["id"] for a in AGENTS}
    ranked = sorted(plans, key=lambda p: -sum(S[p["id"]].values()))
    for p in ranked:
        if len(keep) >= limit:
            break
        keep.add(p["id"])
    return [p for p in plans if p["id"] in keep]


def _llm_propose(agent, world, d, plans, S, r, history):
    sysmsg = (f"You are the {agent} agent in a food-rescue negotiation. {_VOICE[agent]} "
              f"Your red line, which you never cross: {RED_LINES[agent]}. "
              "There is no boss: a plan passes when every agent accepts, or by majority with the dissent on record. "
              "Round 1: propose your favourite. Later rounds: stand firm unless your favourite was objected to; "
              "then you may move to a plan that still gives you a good share of your best option. "
              "Argue only from your own goal, with numbers. "
              'Reply with JSON only: {"propose": "<plan id>", "reason": "<one sentence, under 25 words>"}')
    user = (f"Food: {', '.join(d['food']['items'])}, {d['food']['servings']} servings, "
            f"{d['safe_until'] - world.now} minutes until unsafe.\nRound {r + 1} of 3.\n"
            f"Safe candidate plans:\n{_table(world, d, plans, S, agent)}\n\nEarlier rounds:\n{history or 'none'}")
    out = llm.chat_json(sysmsg, user, max_tokens=200, model=os.getenv("AGENT_MODEL"), effort="low")
    pid = out["propose"]
    if pid not in S:
        raise ValueError("unknown plan")
    return pid, out.get("reason", "")


def _llm_vote(agent, world, d, proposed, plans_by_id, S, r, best=None):
    bar = round(100 * THRESHOLDS[r])
    sysmsg = (f"You are the {agent} agent in a food-rescue negotiation. {_VOICE[agent]} "
              f"Your red line, which you never cross: {RED_LINES[agent]}. "
              f"Vote on each proposed plan. This is round {r + 1} of 3: accept a plan only if it gives you at least "
              f"{bar}% of your best option; otherwise object, and say in numbers what it costs your goal. "
              "You are one voice in a team, so defend your goal; the other agents defend theirs. "
              "Argue only from your own goal. "
              'Reply with JSON only: {"votes": {"<plan id>": {"accept": true|false, "reason": "<under 20 words>"}}}')
    user = (f"Round {r + 1} of 3. {d['safe_until'] - world.now} minutes until the food is unsafe.\n"
            f"Proposed plans:\n{_table(world, d, [plans_by_id[i] for i in proposed], S, agent, best)}")
    out = llm.chat_json(sysmsg, user, max_tokens=300, model=os.getenv("AGENT_MODEL"), effort="low")
    return {pid: (bool(out["votes"][pid]["accept"]), out["votes"][pid].get("reason", "")) for pid in proposed}


def use_llm():
    return os.getenv("LLM_AGENTS") == "1" and llm.available()


# ---------- the negotiation ----------

# ---------- one agent's own steps ----------
# Each negotiator does three things, using only what it is sent. They run here in-process, or inside
# that agent's own service (mesh/), which calls these same functions: the decisions are identical.

def agent_evaluate(a, world, d, plans):
    """Agent a scores every safe plan against its own goal and marks the ones past its red line."""
    return ({p["id"]: round(score(a, world, d, p), 3) for p in plans},
            {p["id"]: red_line(a, world, d, p, plans) for p in plans})


def agent_propose(a, world, d, plans, S, V, r, history, mode):
    """Agent a proposes one plan for round r. Returns (plan id, reason, used_llm)."""
    pid, reason, used = _rules_round(world, d, plans, S, V, r)[a], None, False
    if mode == "llm":
        try:
            pid, reason = _llm_propose(a, world, d, plans, S, r, history)
            used = True
        except Exception:  # noqa: BLE001 - fall back to rules for this agent
            pass
    best = max(S[q["id"]][a] for q in plans)
    p = next(q for q in plans if q["id"] == pid)
    return pid, reason or propose_reason(a, p, world, S[pid][a] < best - 1e-9), used


def agent_vote(a, world, d, plans, proposed, S, V, r, mode):
    """Agent a votes on every proposed plan. Returns ({plan id: {accept, reason, kind}}, used_llm)."""
    plans_by_id = {p["id"]: p for p in plans}
    best_score = {x: max(S[p["id"]][x] for p in plans) for x in AGENTS}
    best_plan = max(plans, key=lambda p: S[p["id"]][a])
    llm_votes, used = None, False
    if mode == "llm":
        try:
            llm_votes, used = _llm_vote(a, world, d, proposed, plans_by_id, S, r, best_score[a]), True
        except Exception:  # noqa: BLE001
            pass
    out = {}
    for pid in proposed:
        p = plans_by_id[pid]
        if V[pid][a]:  # red lines hold in every round, whatever the model says
            acc, why, kind = False, V[pid][a], ("reliability" if "reliable" in V[pid][a] else "veto")
        elif llm_votes is not None and pid in llm_votes and not (
                llm_votes[pid][0] and S[pid][a] < (THRESHOLDS[r] - GIVE_UP_MARGIN) * best_score[a]):
            acc, why = llm_votes[pid]
            kind = object_reason(a, p, best_plan, world)[1]
            why = ("Accept: " if acc else "Object: ") + why if why else ("Accept." if acc else "Object.")
        else:
            acc = _rules_vote(a, pid, S, best_score, r, p)
            if acc:
                why, kind = accept_reason(a, p, world), None
            else:
                why, kind = object_reason(a, p, best_plan, world)
        out[pid] = {"accept": acc, "reason": why, "kind": None if acc else kind}
    return out, used


class LocalCouncil:
    """The three negotiators as plain function calls in this process."""
    remote = False

    def __init__(self, world, d, plans):
        self.world, self.d, self.plans = world, d, plans

    def evaluate(self, a):
        return agent_evaluate(a, self.world, self.d, self.plans)

    def propose(self, a, S, V, r, history, mode):
        return agent_propose(a, self.world, self.d, self.plans, S, V, r, history, mode)

    def vote(self, a, proposed, S, V, r, mode):
        return agent_vote(a, self.world, self.d, self.plans, proposed, S, V, r, mode)


def _each(fn, parallel):
    """Run fn(agent) for all three agents: in parallel when they are slow (model calls, network)."""
    if not parallel:
        return {a: fn(a) for a in AGENTS}
    with ThreadPoolExecutor(3) as ex:
        futs = {a: ex.submit(fn, a) for a in AGENTS}
    return {a: f.result() for a, f in futs.items()}


# ---------- the negotiation ----------

def negotiate(world, d, plans, council=None):
    """No agent has the final say: this only relays messages and counts votes. The agents themselves
    evaluate, propose and vote, in-process (LocalCouncil) or as separate services (mesh.RemoteCouncil)."""
    if council is None:
        mesh = getattr(world, "mesh", None)
        council = mesh.council(world, d, plans) if mesh else LocalCouncil(world, d, plans)
    plans_by_id = {p["id"]: p for p in plans}
    # Claude speaks only in the live demo; the Evidence runs (hundreds of headless worlds) use the rules,
    # so they're fast, free and give the same numbers every time
    mode = "llm" if use_llm() and getattr(world, "live", True) else "rules"
    parallel = council.remote or mode == "llm"
    # step 0: each agent shares its own evaluation of every plan (scores and vetoes) with the others
    ev = _each(council.evaluate, parallel)
    S = {p["id"]: {a: ev[a][0][p["id"]] for a in AGENTS} for p in plans}
    V = {p["id"]: {a: ev[a][1][p["id"]] for a in AGENTS} for p in plans}
    rounds, history = [], ""
    llm_ok = False
    weights = world.weights
    urgent = d["safe_until"] - world.now < URGENT_MINUTES

    def vetoed(pid):
        return any(V[pid][a] for a in AGENTS)

    def done(outcome, plan, proposed, votes, **extra):
        return dict(_result(outcome, plan, rounds, S, proposed, votes, "llm" if llm_ok else "rules", weights), **extra)

    for r in range(3):
        props = _each(lambda a: council.propose(a, S, V, r, history, mode), parallel)
        proposals = {a: props[a][0] for a in AGENTS}
        reasons = {a: props[a][1] for a in AGENTS}
        llm_ok = llm_ok or any(props[a][2] for a in AGENTS)
        proposed = list(dict.fromkeys(proposals[a] for a in AGENTS))

        messages = []
        for a in AGENTS:
            p = plans_by_id[proposals[a]]
            if r == 0:
                verb = "Proposes"
            elif rounds and rounds[-1]["proposals"][a] == proposals[a]:
                verb = "Stands firm on"
            else:
                verb = "Revises to"
            messages.append({"agent": a, "type": "propose", "text": f"{verb} {short(p)}. " + reasons[a]})
        live = getattr(world, "live_rounds", None)   # the live demo shows each step while the next is still thinking
        if live is not None:
            live.append({"round": r + 1, "messages": list(messages), "voting": True})

        cast = _each(lambda a: council.vote(a, proposed, S, V, r, mode), parallel)
        llm_ok = llm_ok or any(cast[a][1] for a in AGENTS)
        votes = {pid: {a: cast[a][0][pid] for a in AGENTS} for pid in proposed}

        for pid in proposed:
            for a in AGENTS:
                v = votes[pid][a]
                if not v["accept"] and proposals[a] != pid:
                    messages.append({"agent": a, "type": "objection", "text": f"On {short(plans_by_id[pid])}: {v['reason']}"})
        rounds.append({"round": r + 1, "proposals": dict(proposals), "votes": votes, "messages": messages})
        if live is not None:
            live[-1] = {"round": r + 1, "messages": list(messages), "voting": False}
        history += f"Round {r + 1}: " + "; ".join(f"{a} proposed {proposals[a]}" for a in AGENTS) + "\n"

        support = {pid: sum(weights[a] for a in AGENTS if votes[pid][a]["accept"]) for pid in proposed}
        unanimous = [pid for pid in proposed if all(votes[pid][a]["accept"] for a in AGENTS)]
        if unanimous:
            pid = max(unanimous, key=lambda i: sum(S[i].values()))
            return done("consensus", plans_by_id[pid], proposed, votes)
        if urgent:
            # stop and act: prefer plans nobody vetoed, then the most support, then the best for everyone combined
            pid = max(proposed, key=lambda i: (not vetoed(i), support[i], sum(S[i].values())))
            return done("urgent", plans_by_id[pid], proposed, votes)

    support = {pid: sum(weights[a] for a in AGENTS if votes[pid][a]["accept"]) for pid in proposed}
    ranked = sorted(proposed, key=lambda i: (-support[i], -sum(S[i].values())))
    majority = [pid for pid in ranked if support[pid] >= 2.0]
    clean = [pid for pid in majority if not vetoed(pid)]
    if clean:
        return done("majority", plans_by_id[clean[0]], proposed, votes)
    options = [plans_by_id[i] for i in ranked[:2]]
    if majority:
        pid = majority[0]
        who = [a for a in AGENTS if V[pid][a]]
        why = (f"unacceptable compromise: the majority wants {short(plans_by_id[pid])}, "
               f"but {' and '.join(who)} vetoes it ({V[pid][who[0]][6:].strip()})")
        return done("unacceptable", None, proposed, votes, options=options, why=why)
    why = "irreconcilable goals: after 3 rounds no plan has majority support"
    return done("irreconcilable", None, proposed, votes, options=options, why=why)


def _result(outcome, plan, rounds, S, proposed, votes, mode, weights):
    dissent = []
    if plan:
        for a in AGENTS:
            v = votes[plan["id"]][a]
            if not v["accept"]:
                dissent.append({"agent": a, "kind": v["kind"], "reason": v["reason"]})
    return {
        "outcome": outcome,
        "plan": plan,
        "options": [plan] if plan else [],
        "rounds": rounds,
        "scores": {pid: S[pid] for rnd in rounds for pid in rnd["votes"]},
        "dissent": dissent,
        "mode": mode,
        "weights": dict(weights),
    }
