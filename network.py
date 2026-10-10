"""The agent network: every shelter and driver has its own agent with its own goals.

Protocol for one donation (no central decision-maker):
  1. The business agent announces the surplus.
  2. The directory finds shelters that can safely take it (safety rules, in world.py).
  3. Each shelter agent answers from its own point of view: accept, counter-offer
     (take only part of it), or decline, with a reason.
  4. Each driver agent bids on getting the food to each shelter that said yes:
     arrival time, price, how sure it is, or "no" if the trip is too far for it.
  5. Speed, Cost and Need (agents.py) negotiate over the resulting offer x bid plans.
  6. If the winning plan is a counter-offer, the rest of the food is split off and
     announced again, so nothing is left behind.
"""
from config import MIN_LOT, VOLUNTEER_MAX_KM


# ---------------- shelter agents ----------------

def shelter_offer(world, n, d):
    """How this shelter answers a donation request, from its own point of view.
    Returns {"kind": accept|counter|decline, "servings": int, "reason": str}."""
    f = d["food"]
    want = f["servings"]
    room = n["capacity_servings"] - n["received"] - world.committed(n["id"], exclude=d)
    limits = n.get("category_limits", {})
    if f["category"] in limits:
        already = n.get("received_by_category", {}).get(f["category"], 0) + world.committed_category(n["id"], f["category"], exclude=d)
        room = min(room, limits[f["category"]] - already)
        limit_reason = f"we can only use {limits[f['category']]} servings of {f['category']} food a day"
    else:
        limit_reason = None
    if room < MIN_LOT:
        why = limit_reason or "we're out of room"
        return {"kind": "decline", "servings": 0, "reason": f"Sorry, {why}."}
    if room < want:
        why = limit_reason or f"we only have room for {room} more"
        return {"kind": "counter", "servings": room, "reason": f"We'll take {room} of the {want} servings; {why}."}
    return {"kind": "accept", "servings": want, "reason": f"Yes, we can take all {want} servings."}


# ---------------- driver agents ----------------

def driver_bid(world, dr, d, n, plan):
    """A driver's bid for one (pickup -> shelter) trip, or a refusal. `plan` has the trip's numbers."""
    max_km = dr.get("max_km", VOLUNTEER_MAX_KM if dr["type"] == "volunteer" else None)
    if max_km is not None and plan["km"] > max_km:
        return {"willing": False, "reason": f"{plan['km']} km is farther than I drive ({max_km} km max)."}
    if dr["type"] == "paid":
        why = f"${plan['cost']:.2f}, there in {plan['dur']} min."
    elif dr["type"] == "volunteer":
        why = f"Free, there in {plan['dur']} min."
    else:
        why = f"Our own van, free, there in {plan['dur']} min."
    return {"willing": True, "reason": why}


# ---------------- message log helpers ----------------

def summarize_offers(offers):
    yes = [o for o in offers if o["kind"] == "accept"]
    counter = [o for o in offers if o["kind"] == "counter"]
    no = [o for o in offers if o["kind"] == "decline"]
    return f"{len(yes)} accept, {len(counter)} counter-offer, {len(no)} decline"
