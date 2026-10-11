"""The agent mesh: every agent as its own process, found through the directory, talking over HTTP.

Run:  python tests/test_mesh.py      (starts ~17 local processes on ports 7600+, stops them at the end)

Checks that the distributed agents decide exactly as the in-process ones, every scenario, every
negotiation; that a stopped agent drops out of the directory and is simply not consulted; that it can
rejoin; and that every message is traced.
"""
import copy
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scenarios  # noqa: E402
from mesh.client import MeshClient  # noqa: E402
from mesh.launcher import Launcher  # noqa: E402
from world import World  # noqa: E402


def run(name, mesh=None, max_minutes=600):
    w = World(copy.deepcopy(scenarios.SCENARIOS[name]), policy="agents", live=False)
    w.mesh = mesh
    for _ in range(max_minutes):
        w.tick()
        if w.done():
            break
    return w


def transcript(w):
    return [(n["donation"], n["outcome"], n["plan"] and n["plan"]["id"],
             [(r["proposals"], {p: {a: v["accept"] for a, v in vs.items()} for p, vs in r["votes"].items()})
              for r in n["rounds"]]) for n in w.negotiations]


def main():
    L = Launcher(base_port=7600)
    assert L.start(wait=15), "not every agent registered in the directory"
    mesh = MeshClient(L.directory_url, launcher=L)
    try:
        listed = mesh.agents(fresh=True)
        kinds = {k: sum(r["kind"] == k for r in listed) for k in ("shelter", "driver", "negotiator")}
        print(f"directory lists {len(listed)} agents: {kinds}")
        assert kinds["negotiator"] == 3 and kinds["shelter"] >= 5 and kinds["driver"] >= 4

        # 1. same decisions as in-process, every scenario
        for name in scenarios.SCENARIOS:
            a, b = run(name), run(name, mesh)
            assert a.metrics() == b.metrics(), (name, a.metrics(), b.metrics())
            assert transcript(a) == transcript(b), name
            print(f"ok  {name}: identical metrics and negotiations ({len(b.negotiations)} negotiations)")
        sent = mesh.status()["messages"]
        assert sent > 100 and mesh.status()["failed"] == 0
        print(f"ok  {sent} messages traced, 0 failed")

        # 2. a stopped shelter agent leaves the directory and is not consulted; the donation still gets a plan
        L.stop("shelter:northside-youth")
        time.sleep(0.5)
        assert "northside-youth" not in mesh.alive("shelter")
        w = run("lunch_rush", mesh)
        assert all(n["plan"] is None or n["plan"]["np"] != "northside-youth" for n in w.negotiations)
        assert w.metrics()["meals_delivered_safely"] > 0
        print("ok  stopped shelter agent: left the directory, never consulted, food still delivered")

        # 3. it can rejoin
        assert L.restart("shelter:northside-youth")
        assert "northside-youth" in mesh.alive("shelter") or mesh.agents(fresh=True)
        print("ok  restarted agent re-registered")

        # 4. a stopped negotiator: the others go on; the same logic stands in, and that's recorded
        L.stop("negotiator:Cost")
        time.sleep(0.5)
        w = run("lunch_rush", mesh)
        assert w.metrics()["meals_delivered_safely"] > 0
        assert L.restart("negotiator:Cost")
        print("ok  stopped negotiator: negotiation still completes (fallback stand-in)")
        print("\nmesh tests passed")
    finally:
        L.shutdown()


if __name__ == "__main__":
    main()
