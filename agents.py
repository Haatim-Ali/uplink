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
from config import CONCESSION, THRESHOLDS, TIGHT_SLACK, URGENT_MINUTES

AGENTS = ["Speed", "Cost", "Need"]
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
    if agent == "Speed":
        return clamp(p["slack"] / remaining) * (0.6 + 0.4 * p["reliability"])
    if agent == "Cost":
        return (1 - min(p["cost"], 30) / 30) * (0.55 + 0.45 * p["reliability"])
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
    if agent == "Speed":
        return f"Arrives in {p['dur']} min with {p['slack']} min to spare ({p['reliability']:.0%} reliable)."
    if agent == "Cost":
        return "Costs nothing." if p["cost"] == 0 else f"Costs ${p['cost']:.2f}."
    n = world.nonprofits[p["np"]]
    room = n["capacity_servings"] - n["received"] - world.committed(n["id"])
    if world.committed(n["id"]):
        return f"Food already heading there, but it still has room for {room} servings."
    return f"Last donation {n['last_donation_days']} days ago; room for {room} more servings."


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
    return (f"Object: {p['np_name']} got food {n['last_donation_days']} days ago; "
            f"{bn['name']} has waited {bn['last_donation_days']} days."), "need"


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

def _table(world, d, plans, S, agent):
    lines = []
    for p in plans:
        lines.append(
            f"{p['id']}: {p['np_name']} via {p['driver_name']} ({p['driver_type']}), {p['dur']} min, "
            f"slack {p['slack']} min, ${p['cost']:.2f}, reliability {p['reliability']:.0%}, "
            f"shelter last fed {world.nonprofits[p['np']]['last_donation_days']}d ago, your score {S[p['id']][agent]:.2f}"
        )
    return "\n".join(lines)


def _llm_shortlist(plans, S, limit=8):
    keep = {max(plans, key=lambda p: S[p["id"]][a])["id"] for a in AGENTS}
    ranked = sorted(plans, key=lambda p: -sum(S[p["id"]].values()))
    for p in ranked:
        if len(keep) >= limit:
            break
        keep.add(p["id"])
    return [p for p in plans if p["id"] in keep]


def _llm_propose(agent, world, d, plans, S, r, history):
    sysmsg = (f"You are the {agent} agent in a food-rescue negotiation. Your goal: {GOALS[agent]}. "
              f"Your red line, which you never cross: {RED_LINES[agent]}. "
              "There is no boss: a plan passes only when every agent accepts. In round 1 propose your favourite. "
              "In later rounds you may move toward a compromise if others objected, but defend your goal. "
              'Reply with JSON only: {"propose": "<plan id>", "reason": "<one sentence, under 25 words>"}')
    user = (f"Food: {', '.join(d['food']['items'])}, {d['food']['servings']} servings, {d['food']['category']}, "
            f"{d['safe_until'] - world.now} minutes until unsafe.\nRound {r + 1} of 3.\n"
            f"Safe candidate plans:\n{_table(world, d, plans, S, agent)}\n\nEarlier rounds:\n{history or 'none'}")
    out = llm.chat_json(sysmsg, user, max_tokens=200, model=os.getenv("AGENT_MODEL"))
    pid = out["propose"]
    if pid not in S:
        raise ValueError("unknown plan")
    return pid, out.get("reason", "")


def _llm_vote(agent, world, d, proposed, plans_by_id, S, r):
    sysmsg = (f"You are the {agent} agent in a food-rescue negotiation. Your goal: {GOALS[agent]}. "
              f"Your red line, which you never cross: {RED_LINES[agent]}. "
              "Vote on each proposed plan. Accept plans you can live with; object only when it really hurts your goal, "
              "and remember that objecting forever means a human has to decide and the food may spoil. "
              'Reply with JSON only: {"votes": {"<plan id>": {"accept": true|false, "reason": "<under 20 words>"}}}')
    user = (f"Round {r + 1} of 3. {d['safe_until'] - world.now} minutes until the food is unsafe.\n"
            f"Proposed plans:\n{_table(world, d, [plans_by_id[i] for i in proposed], S, agent)}")
    out = llm.chat_json(sysmsg, user, max_tokens=300, model=os.getenv("AGENT_MODEL"))
    return {pid: (bool(out["votes"][pid]["accept"]), out["votes"][pid].get("reason", "")) for pid in proposed}


def use_llm():
    return os.getenv("LLM_AGENTS") == "1" and llm.available()


# ---------- the negotiation ----------

def negotiate(world, d, plans):
    plans_by_id = {p["id"]: p for p in plans}
    S = all_scores(world, d, plans)
    V = {p["id"]: {a: red_line(a, world, d, p, plans) for a in AGENTS} for p in plans}
    best_score = {a: max(S[p["id"]][a] for p in plans) for a in AGENTS}
    best_plan = {a: max(plans, key=lambda p: S[p["id"]][a]) for a in AGENTS}
    mode = "llm" if use_llm() else "rules"
    rounds, history = [], ""
    llm_ok = False
    weights = world.weights
    urgent = d["safe_until"] - world.now < URGENT_MINUTES

    def vetoed(pid):
        return any(V[pid][a] for a in AGENTS)

    def done(outcome, plan, proposed, votes, **extra):
        return dict(_result(outcome, plan, rounds, S, proposed, votes, "llm" if llm_ok else "rules", weights), **extra)

    for r in range(3):
        proposals = _rules_round(world, d, plans, S, V, r)
        reasons = {}
        if mode == "llm":
            with ThreadPoolExecutor(3) as ex:
                futs = {a: ex.submit(_llm_propose, a, world, d, plans, S, r, history) for a in AGENTS}
            for a, f in futs.items():
                try:
                    proposals[a], reasons[a] = f.result()
                    llm_ok = True
                except Exception:  # noqa: BLE001 - fall back to rules for this agent
                    pass
        proposed = list(dict.fromkeys(proposals[a] for a in AGENTS))

        votes = {pid: {} for pid in proposed}
        llm_votes = {}
        if mode == "llm":
            with ThreadPoolExecutor(3) as ex:
                futs = {a: ex.submit(_llm_vote, a, world, d, proposed, plans_by_id, S, r) for a in AGENTS}
            for a, f in futs.items():
                try:
                    llm_votes[a] = f.result()
                    llm_ok = True
                except Exception:  # noqa: BLE001
                    pass
        for pid in proposed:
            p = plans_by_id[pid]
            for a in AGENTS:
                if V[pid][a]:  # red lines hold in every round, whatever the model says
                    acc, why, kind = False, V[pid][a], ("reliability" if "reliable" in V[pid][a] else "veto")
                elif a in llm_votes and pid in llm_votes[a]:
                    acc, why = llm_votes[a][pid]
                    kind = object_reason(a, p, best_plan[a], world)[1]
                    why = ("Accept: " if acc else "Object: ") + why if why else ("Accept." if acc else "Object.")
                else:
                    acc = _rules_vote(a, pid, S, best_score, r, p)
                    if acc:
                        why, kind = "Accept: good enough for my goal.", None
                    else:
                        why, kind = object_reason(a, p, best_plan[a], world)
                votes[pid][a] = {"accept": acc, "reason": why, "kind": None if acc else kind}

        messages = []
        for a in AGENTS:
            p = plans_by_id[proposals[a]]
            if r == 0:
                verb = "Proposes"
            elif rounds and rounds[-1]["proposals"][a] == proposals[a]:
                verb = "Stands firm on"
            else:
                verb = "Revises to"
            messages.append({"agent": a, "type": "propose",
                             "text": f"{verb} {short(p)}. " + (reasons.get(a) or propose_reason(a, p, world, S[p["id"]][a] < best_score[a] - 1e-9))})
        for pid in proposed:
            for a in AGENTS:
                v = votes[pid][a]
                if not v["accept"] and proposals[a] != pid:
                    messages.append({"agent": a, "type": "objection", "text": f"On {short(plans_by_id[pid])}: {v['reason']}"})
        rounds.append({"round": r + 1, "proposals": dict(proposals), "votes": votes, "messages": messages})
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
