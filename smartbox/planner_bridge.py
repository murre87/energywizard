"""Bryggan mellan Core och planeringen som egen process (steg 4b av uppdelningen, docs/uppdelning/PLAN.md).

Två lägen, valda med miljövariabeln EW_PLANNER_MODE:

  local   (standard)  Planeringen körs i processen precis som förut. Bryggan gör ingenting.
  shadow              Planeringen körs i processen och är fortfarande den som styr. Samma indata skickas dessutom (i bakgrunden) till planerarens egna
                      process (planner_service.py), och de två besluten jämförs. Skillnader loggas. Inget i beslutet eller styrningen påverkas.

Bryggan får aldrig störa huvudloopen: den väntar aldrig på tjänsten, ett fel i den fångas och räknas, och evaluate() returnerar alltid exakt det
beslut den gamla vägen gav. Tjänsten startas som en underprocess och startas om vid behov (högst en gång per 30 s och fem gånger i timmen). Efter
varje start jämförs de första svaren separat (uppvärmning), eftersom den nya motorn börjar utan historik medan den gamla har sin."""
import atexit
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import contracts
import parity

MODES = ("local", "shadow")
SERVICE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "planner_service.py")


def _http_post(port, path, wire, timeout):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(wire, allow_nan=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class Bridge:
    def __init__(self, mode=None, port=None, spawn=True, timeout=3.0, warmup=8, report_every_s=900.0, clock=time.monotonic, popen=subprocess.Popen, post=None,
                 echo=print):
        mode = (mode if mode is not None else os.environ.get("EW_PLANNER_MODE", "local")).strip().lower()
        if mode not in MODES:
            echo(f"⚠️ Planerare: okänt läge '{mode}' (EW_PLANNER_MODE), kör local.")
            mode = "local"
        self.mode = mode
        self.port = int(port if port is not None else os.environ.get("EW_PLANNER_PORT", "8610"))
        self.spawn, self.timeout, self.warmup_n, self.report_every_s = spawn, timeout, warmup, report_every_s
        self._clock, self._popen, self._echo = clock, popen, echo
        self._post = post or (lambda path, wire: _http_post(self.port, path, wire, self.timeout))
        self._proc, self._starts, self._last_start, self._starting_until = None, [], None, 0.0
        self._warm = warmup
        self._pending = None
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ew-planner") if mode == "shadow" else None
        self._lock = threading.Lock()
        self._last_print, self._last_report = {}, clock()
        self.stats = {"mode": mode, "submitted": 0, "identical": 0, "diffs": 0, "warmup_diffs": 0, "errors": 0, "skipped": 0, "restarts": 0,
                      "last_diff": None, "last_error": None}
        if self._pool is not None and spawn:
            atexit.register(self.close)

    # ---- huvudloopen ----
    def evaluate(self, engine, state):
        """Alltid den gamla vägens beslut. I skuggläge skickas samma indata vidare i bakgrunden."""
        actions = engine.evaluate(state)
        if self.mode == "shadow":
            try:
                self._submit(state, actions)
                self._maybe_report()
            except Exception as e:                       # ett fel i bryggan får aldrig nå huvudloopen
                self._error(f"bryggan: {type(e).__name__}: {e}")
        return actions

    def _submit(self, state, actions):
        with self._lock:
            if self._pending is not None and not self._pending.done():
                self.stats["skipped"] += 1               # föregående anrop pågår fortfarande: hopp över, ingen kö
                return
            local = contracts.decision_to_wire(actions)  # ögonblicksbild nu: huvudloopen ändrar beslutet efteråt
            wire = contracts.planner_input_to_wire(dict(state))
            self.stats["submitted"] += 1
            self._pending = self._pool.submit(self._work, wire, local)

    # ---- bakgrund ----
    def _work(self, wire, local):
        try:
            self._ensure_started()
            remote = self._post("/decide", wire)
        except Exception as e:
            if self._clock() < self._starting_until:
                return                                   # tjänsten håller på att starta: inte ett fel än
            self._error(f"{type(e).__name__}: {e}")
            return
        diffs = parity.diff(local, remote)
        with self._lock:
            warm = self._warm > 0
            if warm:
                self._warm -= 1
            if not diffs:
                self.stats["identical"] += 1
                return
            self.stats["warmup_diffs" if warm else "diffs"] += 1
            self.stats["last_diff"] = [(p, a, b) for p, a, b in diffs[:5]]
        if not warm:
            self._log_diff(diffs)

    def _ensure_started(self):
        if not self.spawn:
            return
        if self._proc is not None and self._proc.poll() is None:
            return
        now = self._clock()
        if self._last_start is not None and now - self._last_start < 30:
            return
        self._starts = [t for t in self._starts if now - t < 3600]
        if len(self._starts) >= 5:
            return
        self._last_start = now
        self._starts.append(now)
        had = self._proc is not None
        self._proc = self._popen([sys.executable, "-u", SERVICE_PATH, "--port", str(self.port)], env=dict(os.environ))
        self._warm = self.warmup_n
        self._starting_until = now + 90
        if had:
            with self._lock:
                self.stats["restarts"] += 1
            self._echo("⚠️ Planerare: processen hade stannat, startar om den.")

    def _error(self, text):
        with self._lock:
            self.stats["errors"] += 1
            self.stats["last_error"] = text[:200]
        self._rate_limited("error", f"⚠️ Planerare (skugga): {text[:160]}")

    def _log_diff(self, diffs):
        shown = "; ".join(f"{p}: {a!r} != {b!r}" for p, a, b in diffs[:3])
        key = "|".join(sorted(p for p, _, _ in diffs[:5]))
        self._rate_limited("diff:" + key, f"🧪 Planerare (skugga): beslutet skiljer sig från den gamla vägen ({len(diffs)} fält): {shown}")

    def _rate_limited(self, key, text, every_s=600.0):
        now = self._clock()
        if now - self._last_print.get(key, -1e9) >= every_s:
            self._last_print[key] = now
            self._echo(text)

    def _maybe_report(self):
        now = self._clock()
        if now - self._last_report >= self.report_every_s:
            self._last_report = now
            self._echo(self.summary())

    def summary(self):
        s = self.stats
        return (f"🧪 Planerare (skugga): {s['submitted']} jämförelser, {s['identical']} identiska, {s['diffs']} skillnader "
                f"(+{s['warmup_diffs']} under uppvärmning), {s['errors']} fel, {s['skipped']} hoppade över, {s['restarts']} omstarter")

    def close(self):
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass
        if self._pool is not None:
            self._pool.shutdown(wait=False)
