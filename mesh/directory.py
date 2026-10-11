"""Agent directory: where agents announce themselves and find each other.

Each agent publishes a record modeled on an OASF agent record (name, version, skills, where to reach
it, what it can do) and sends a heartbeat every couple of seconds. A record that stops heartbeating
drops out after TTL seconds, so a crashed or stopped agent is no longer discovered.

    python -m mesh.directory --port 7300

HTTP + JSON:  POST /register {record}   POST /heartbeat {"id"}   POST /deregister {"id"}
              GET /agents?kind=shelter&skill=food.receive   GET /health
"""
import argparse
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

TTL = 6.0   # seconds without a heartbeat before an agent is considered gone


class Directory:
    def __init__(self, ttl=TTL):
        self.ttl = ttl
        self.records = {}   # id -> {"record": {...}, "seen": t, "since": t}
        self.lock = threading.Lock()

    def register(self, record):
        now = time.time()
        with self.lock:
            old = self.records.get(record["id"])
            self.records[record["id"]] = {"record": record, "seen": now, "since": old["since"] if old else now}

    def heartbeat(self, agent_id):
        with self.lock:
            if agent_id not in self.records:
                return False   # unknown: the agent should register again
            self.records[agent_id]["seen"] = time.time()
            return True

    def deregister(self, agent_id):
        with self.lock:
            self.records.pop(agent_id, None)

    def find(self, kind=None, skill=None):
        now = time.time()
        with self.lock:
            out = []
            for r in self.records.values():
                rec = r["record"]
                if now - r["seen"] > self.ttl:
                    continue
                if kind and rec.get("kind") != kind:
                    continue
                if skill and skill not in rec.get("skills", []):
                    continue
                out.append(dict(rec, last_seen=round(now - r["seen"], 1), up_for=round(now - r["since"])))
            return sorted(out, key=lambda x: x["id"])


def make_handler(directory):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):   # quiet
            pass

        def _send(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/health":
                return self._send(200, {"ok": True})
            if u.path == "/agents":
                q = parse_qs(u.query)
                return self._send(200, {"agents": directory.find(q.get("kind", [None])[0], q.get("skill", [None])[0])})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/register":
                directory.register(body)
                return self._send(200, {"ok": True})
            if self.path == "/heartbeat":
                return self._send(200, {"ok": directory.heartbeat(body.get("id"))})
            if self.path == "/deregister":
                directory.deregister(body.get("id"))
                return self._send(200, {"ok": True})
            self._send(404, {"error": "not found"})
    return Handler


def serve(port, ttl=TTL, background=False):
    """Start the directory. background=True runs it in a thread (tests) and returns the server."""
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(Directory(ttl)))
    srv.daemon_threads = True
    if background:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv
    parent = os.getppid()

    def watch():   # exit once the app that started us is gone
        while os.getppid() == parent:
            time.sleep(1)
        os._exit(0)
    threading.Thread(target=watch, daemon=True).start()
    srv.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Uplink agent directory")
    ap.add_argument("--port", type=int, default=7300)
    serve(ap.parse_args().port)
