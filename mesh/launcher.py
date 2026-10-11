"""Starts the agent directory and one process per agent, and can stop or restart any of them.

    python -m mesh.launcher           # the whole mesh on its own, Ctrl+C to stop (app.py does this for you)
"""
import atexit
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

import requests
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
LOGS = os.path.join(tempfile.gettempdir(), "uplink-mesh")
NEGOTIATORS = ["Speed", "Cost", "Need"]


def _free(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _load(name):
    with open(os.path.join(DATA, name)) as f:
        return json.load(f)


def agntcy_available():
    """True when the AGNTCY app-sdk is installed (pip install -r requirements-agntcy.txt)."""
    try:
        import agntcy_app_sdk  # noqa: F401
        import nats  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


class Launcher:
    def __init__(self, base_port=7300, nats_url=None):
        self.base = base_port
        self.nats_url = nats_url    # set: every agent is also an AGNTCY A2A agent over NATS
        self.nats_proc = None
        self.directory_port = None
        self.procs = {}      # record id ("shelter:grace-kitchen") -> {"proc", "kind", "agent", "port"}
        self._next = base_port + 1
        os.makedirs(LOGS, exist_ok=True)
        atexit.register(self.shutdown)

    @property
    def directory_url(self):
        return f"http://127.0.0.1:{self.directory_port}"

    def _port(self):
        while not _free(self._next):
            self._next += 1
        p, self._next = self._next, self._next + 1
        return p

    def _popen(self, args, log):
        return subprocess.Popen([sys.executable, *args], cwd=HERE, stdout=subprocess.DEVNULL,
                                stderr=open(os.path.join(LOGS, log), "w"), start_new_session=True)

    def ensure_nats(self):
        """Use the NATS server at nats_url, or start one (nats-server) if none is running. False if neither."""
        u = urlparse(self.nats_url)
        host, port = u.hostname or "localhost", u.port or 4222
        if host not in ("localhost", "127.0.0.1"):
            return True            # a remote NATS server: assume it's up
        if not _free(port):
            return True            # something is already listening there: use it
        exe = shutil.which("nats-server")
        if not exe:
            return False
        self.nats_proc = subprocess.Popen([exe, "-p", str(port)], stdout=subprocess.DEVNULL,
                                          stderr=open(os.path.join(LOGS, "nats.log"), "w"), start_new_session=True)
        for _ in range(40):
            if not _free(port):
                return True
            time.sleep(0.1)
        return False

    def start(self, wait=8.0):
        """Directory first, then every shelter, driver and negotiator. Returns once they're all listed."""
        if self.nats_url and not self.ensure_nats():
            print(f"No NATS server at {self.nats_url} and nats-server isn't installed; agents talk over HTTP.")
            self.nats_url = None
        port = self.base
        while not _free(port):
            port += 1
        self.directory_port = port
        self._next = max(self._next, port + 1)
        self.dir_proc = self._popen(["-m", "mesh.directory", "--port", str(port)], "directory.log")
        for n in _load("nonprofits.json"):
            self.spawn("shelter", n["id"], wait=0)
        for dr in _load("drivers.json"):
            self.spawn("driver", dr["id"], wait=0)
        for a in NEGOTIATORS:
            self.spawn("negotiator", a, wait=0)
        self.base_ids = set(self.procs)
        return self.wait_listed(list(self.procs), wait)

    def reset_extras(self):
        """Stop agents that joined during a run (not in the data files), e.g. on a world reset."""
        for rid in set(self.procs) - getattr(self, "base_ids", set(self.procs)):
            self.stop(rid)
            self.procs.pop(rid, None)

    def spawn(self, kind, agent, wait=4.0, name=None):
        rid = f"{kind}:{agent}"
        old = self.procs.get(rid)
        if old and old["proc"].poll() is None:
            return True
        port = old["port"] if old and _free(old["port"]) else self._port()
        name = name or (old or {}).get("name")
        proc = self._popen(["-m", "mesh.agent", "--kind", kind, "--id", agent, "--port", str(port),
                            "--directory", self.directory_url] + (["--name", name] if name else [])
                           + (["--nats", self.nats_url] if self.nats_url else []), f"{kind}-{agent}.log")
        self.procs[rid] = {"proc": proc, "kind": kind, "agent": agent, "port": port, "name": name}
        return self.wait_listed([rid], wait) if wait else True

    def stop(self, rid):
        p = self.procs.get(rid)
        if not p or p["proc"].poll() is not None:
            return False
        p["proc"].terminate()   # the agent deregisters itself on the way out
        try:
            p["proc"].wait(2)
        except subprocess.TimeoutExpired:
            p["proc"].kill()
        return True

    def restart(self, rid):
        p = self.procs.get(rid)
        return bool(p) and self.spawn(p["kind"], p["agent"])

    def wait_listed(self, rids, timeout):
        """Wait until the directory lists all of these agents."""
        end = time.time() + timeout
        want = set(rids)
        while time.time() < end:
            try:
                got = {a["id"] for a in requests.get(f"{self.directory_url}/agents", timeout=1).json()["agents"]}
                if want <= got:
                    return True
            except requests.RequestException:
                pass
            time.sleep(0.15)
        return False

    def processes(self):
        return {rid: {"kind": p["kind"], "agent": p["agent"], "port": p["port"], "pid": p["proc"].pid,
                      "running": p["proc"].poll() is None} for rid, p in self.procs.items()}

    def shutdown(self):
        for p in self.procs.values():
            if p["proc"].poll() is None:
                p["proc"].terminate()
        if getattr(self, "dir_proc", None) and self.dir_proc.poll() is None:
            self.dir_proc.terminate()
        if self.nats_proc and self.nats_proc.poll() is None:   # only the server we started ourselves
            self.nats_proc.terminate()
        for p in self.procs.values():
            try:
                p["proc"].wait(2)
            except subprocess.TimeoutExpired:
                p["proc"].kill()


if __name__ == "__main__":
    L = Launcher()
    ok = L.start()
    print(f"Directory {L.directory_url} · {len(L.procs)} agents · all listed: {ok}. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        L.shutdown()
