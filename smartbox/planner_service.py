"""Planeringen som egen process (steg 4b av uppdelningen, docs/uppdelning/PLAN.md).

En liten HTTP-tjänst på loopback som håller en egen GlobalPriorityManager och svarar på JSON enligt kontrakten i contracts/:

    POST /decide   planner-input (JSON)  ->  planner-decision (JSON)
    POST /reset    ny motor (tom historik), för tester och omstart
    GET  /health   {"ok": true, "calls": N, "api_version": "1.0.0", "pid": N}

Bara stdlib (ThreadingHTTPServer): inga nya beroenden i imagen, och tjänsten lyssnar bara på 127.0.0.1. Motorn är tillståndsfull (den minns mellan
varven), så ALLA anrop går genom samma instans under lås. I skuggläge är tjänsten tyst: notiser skickas inte (gpm.notifier ersätts), så den kan
köra bredvid den gamla vägen utan att något dubbleras. Starta: python planner_service.py --port 8610"""
import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import contracts

MAX_BODY = 4 * 1024 * 1024        # laddplanen är några hundra rader; 4 MB är gott om marginal


class SilentNotifier:
    """Ersätter gpm.notifier i skuggläge: alla anrop är tomma och räknas."""
    def __init__(self):
        self.calls = 0

    def __getattr__(self, name):
        def noop(*a, **k):
            self.calls += 1
        return noop


class Planner:
    def __init__(self, silent=True):
        import gpm
        self._gpm = gpm
        if silent:
            gpm.notifier = SilentNotifier()
        self._lock = threading.Lock()
        self.engine = gpm.GlobalPriorityManager()
        self.calls = 0

    def reset(self):
        with self._lock:
            self.engine = self._gpm.GlobalPriorityManager()
            self.calls = 0

    def decide(self, wire_state: dict) -> dict:
        state = contracts.planner_input_from_wire(wire_state)
        with self._lock:
            actions = self.engine.evaluate(state)
            self.calls += 1
        return contracts.decision_to_wire(actions)


def make_server(planner, host="127.0.0.1", port=0) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):          # tyst: loggas inte per anrop
            pass

        def _send(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return None, (400, {"error": "invalid Content-Length"})
            if n > MAX_BODY:
                return None, (413, {"error": "payload too large"})
            try:
                return json.loads(self.rfile.read(n).decode("utf-8") or "{}"), None
            except (ValueError, UnicodeDecodeError):
                return None, (400, {"error": "invalid JSON"})

        def do_GET(self):
            if self.path == "/health":
                return self._send(200, {"ok": True, "calls": planner.calls, "api_version": contracts.API_VERSION, "pid": os.getpid()})
            self._send(404, {"error": "unknown path"})

        def do_POST(self):
            if self.path not in ("/decide", "/reset"):
                return self._send(404, {"error": "unknown path"})
            body, err = self._body()
            if err:
                return self._send(*err)
            if self.path == "/reset":
                planner.reset()
                return self._send(200, {"ok": True})
            if not isinstance(body, dict):
                return self._send(400, {"error": "body must be a JSON object"})
            try:
                return self._send(200, planner.decide(body))
            except Exception as e:           # ett fel i ett beslut får aldrig fälla tjänsten
                return self._send(500, {"error": f"{type(e).__name__}: {e}"[:300]})

    return ThreadingHTTPServer((host, port), Handler)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("EW_PLANNER_PORT", "8610")))
    ap.add_argument("--loud", action="store_true", help="skicka notiser (styrande läge); utan den är tjänsten tyst")
    a = ap.parse_args(argv)
    planner = Planner(silent=not a.loud)
    srv = make_server(planner, "127.0.0.1", a.port)
    print(f"🧭 Planerare: lyssnar på 127.0.0.1:{srv.server_address[1]} ({'styrande' if a.loud else 'tyst, skuggläge'})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
