"""What an agent is told: a snapshot of the facts it needs, and a small stand-in for the world.

The coordinator's simulated world knows what physically happened (deliveries, food on the way, the
clock). It sends those facts with each request; the agent combines them with what it knows about
itself and decides with the same functions it would use in-process.
"""
import json


def _plain(x):
    return json.loads(json.dumps(x, default=str))


def donation_facts(d):
    keep = ("id", "food", "safe_until", "business_name", "created")
    return _plain({k: d[k] for k in keep if k in d})


def world_facts(world, d, np_ids):
    """The parts of the world an agent's decision reads: the clock, the shelters involved and the food
    already heading to each (with and without this donation)."""
    nps = {i: _plain(world.nonprofits[i]) for i in np_ids if i in world.nonprofits}
    cats = {i: {c: world.committed_category(i, c, exclude=d) for c in ("hot prepared", "cold prepared", "packaged", "produce")}
            for i in nps}
    return {
        "now": world.now,
        "nonprofits": nps,
        "committed": {i: world.committed(i) for i in nps},
        "committed_ex": {i: world.committed(i, exclude=d) for i in nps},
        "committed_cat_ex": cats,
    }


class WorldView:
    """Answers the questions agents.py and network.py ask of the world, from a snapshot."""

    def __init__(self, facts):
        self.now = facts["now"]
        self.nonprofits = facts["nonprofits"]
        self._c = facts["committed"]
        self._cx = facts["committed_ex"]
        self._cc = facts["committed_cat_ex"]

    def committed(self, np_id, exclude=None):
        return (self._cx if exclude is not None else self._c).get(np_id, 0)

    def committed_category(self, np_id, category, exclude=None):
        return self._cc.get(np_id, {}).get(category, 0)
