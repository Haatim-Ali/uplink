"""Three agents with competing goals negotiate a plan. No agent has the final say.

Protocol (Level 3, no central decision-maker):
  0. Safety rules (code, in world.py) have already removed every unsafe plan.
  1. Each round, every agent proposes a plan. Round 1 = its own favourite; in later
     rounds it concedes toward plans the others can live with.
  2. Every agent votes accept/object on every proposed plan, with a reason.
  3. A plan everyone accepts wins (consensus). If time is short, act on the plan
     with the most support ("stop and act"). After 3 rounds, a weighted majority
     wins and the dissent is recorded. Otherwise, ask a human.

Adaptation: an agent whose objection later proves right gets more vote weight
(world.weights), and drivers who cancel lose reliability, which every agent sees.

Set LLM_AGENTS=1 (plus an API key) to have each agent's proposal, votes and
reasons come from the model; rules are the fallback for any failed call.
"""
import os
from concurrent.futures import ThreadPoolExecutor

import llm

AGENTS = ["Speed", "Cost", "Need"]
GOALS = {
    "Speed": "get the food there fast and reliably, with a big safety margin before it spoils",
    "Cost": "spend as little money as possible (volunteers and nonprofit vans are free; paid couriers cost money)",
    "Need": "send food where it helps most: shelters that have waited longest for a donation and have room",
}
THRESHOLDS = [0.9, 0.78, 0.65]  # accept if a plan scores at least this share of the agent's best
CONCESSION = [0.0, 0.45, 0.75]  # how much an agent weighs the least-happy other agent when revising
URGENT_MINUTES = 30


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


def all_scores(world, d, plans):
    return {p["id"]: {a: round(score(a, world, d, p), 3) for a in AGENTS} for p in plans}


def short(p):
    return f"{p['np_name']} via {p['driver_name']}"


def propose_reason(agent, p, world):
    if agent == "Speed":
        return f"Arrives in {p['dur']} min with {p['slack']} min to spare ({p['reliability']:.0%} reliable)."
    if agent == "Cost":
        return "Costs nothing." if p["cost"] == 0 else f"${p['cost']:.2f} is the lowest cost I can find."
    n = world.nonprofits[p["np"]]
    room = n["capacity_servings"] - n["received"] - world.committed(n["id"])
    if world.committed(n["id"]):
        return f"Food already heading there, but it still has room for {room} servings."
    return f"Last donation {n['last_donation_days']} days ago; room for {room} more servings."


def object_reason(agent, p, best, world):
    """Return (text, kind). kind is used later to check whether the objection proved right."""
    if agent == "Speed":
        if p["reliability"] < 0.75:
            return f"Object: {p['driver_name']} is only {p['reliability']:.0%} reliable; a no-show could spoil this food.", "reliability"
        return f"Object: only {p['slack']} min margin; {short(best)} leaves {best['slack']}.", "time"
    if agent == "Cost":
        return f"Object: ${p['cost']:.2f} when {short(best)} costs ${best['cost']:.2f} and is also safe.", "cost"
    n, bn = world.nonprofits[p["np"]], world.nonprofits[best["np"]]
    return (f"Object: {p['np_name']} got food {n['last_donation_days']} days ago; "
            f"{bn['name']} has waited {bn['last_donation_days']} days."), "need"


def _rules_round(world, d, plans, S, best, r):
    proposals = {}
    lam = CONCESSION[r]
    for a in AGENTS:
        others = [o for o in AGENTS if o != a]
        proposals[a] = max(
            plans,
            key=lambda p: (1 - lam) * S[p["id"]][a] + lam * min(S[p["id"]][o] for o in others) + 1e-3 * S[p["id"]]["Speed"],
        )["id"]
    return proposals


def _rules_vote(agent, pid, S, best_score, r):
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
    best_score = {a: max(S[p["id"]][a] for p in plans) for a in AGENTS}
    best_plan = {a: max(plans, key=lambda p: S[p["id"]][a]) for a in AGENTS}
    mode = "llm" if use_llm() else "rules"
    rounds, history = [], ""
    llm_ok = False
    weights = world.weights
    urgent = d["safe_until"] - world.now < URGENT_MINUTES

    for r in range(3):
        proposals = _rules_round(world, d, plans, S, best_score, r)
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
                if a in llm_votes and pid in llm_votes[a]:
                    acc, why = llm_votes[a][pid]
                    kind = object_reason(a, p, best_plan[a], world)[1]
                    why = ("Accept: " if acc else "Object: ") + why if why else ("Accept." if acc else "Object.")
                else:
                    acc = _rules_vote(a, pid, S, best_score, r)
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
                             "text": f"{verb} {short(p)}. " + (reasons.get(a) or propose_reason(a, p, world))})
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
            return _result("consensus", plans_by_id[pid], rounds, S, proposed, votes, "llm" if llm_ok else "rules", weights)
        if urgent:
            pid = max(proposed, key=lambda i: (support[i], S[i]["Speed"]))
            return _result("urgent", plans_by_id[pid], rounds, S, proposed, votes, "llm" if llm_ok else "rules", weights)

    support = {pid: sum(weights[a] for a in AGENTS if votes[pid][a]["accept"]) for pid in proposed}
    ranked = sorted(proposed, key=lambda i: (-support[i], -sum(S[i].values())))
    top = ranked[0]
    if support[top] >= 2.0:
        return _result("majority", plans_by_id[top], rounds, S, proposed, votes, "llm" if llm_ok else "rules", weights)
    res = _result("escalate", None, rounds, S, proposed, votes, "llm" if llm_ok else "rules", weights)
    res["options"] = [plans_by_id[i] for i in ranked[:2]]
    return res


def _result(outcome, plan, rounds, S, proposed, votes, mode, weights, llm_ok=None):
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
