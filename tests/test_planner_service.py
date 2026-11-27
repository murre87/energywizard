"""Steg 4b-2 av uppdelningen: planeringen som egen process (planner_service.py) och bryggan i skuggläge (planner_bridge.py).

Tre nivåer: (A) tjänsten över riktig HTTP ger exakt samma beslut som den gamla vägen, (B) bryggans beteende med falska delar (aldrig blockera,
aldrig kasta, räkna och logga rätt, starta om vid behov), (C) en riktig underprocess från start till svar."""
import contextlib
import copy
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import contracts
import gpm_ext_gen as ext
import gpm_golden_gen as base
import parity
import planner_bridge as pb
import planner_service as ps

ROOT = Path(__file__).resolve().parents[1]


@contextlib.contextmanager
def _gpm_patched():
    import gpm
    with patch.object(gpm.GlobalPriorityManager, "_restore_compressor_lock", lambda self: None), patch("gpm.notifier"), patch("gpm.logger"), \
            patch("gpm.learning.get_optimal_pi_params", return_value=(0.5, 0.05)):
        yield


def _http(url, path, obj=None, raw=None, method="POST", headers=None, timeout=10):
    data = raw if raw is not None else (None if obj is None else json.dumps(obj).encode())
    req = urllib.request.Request(url + path, data=data, headers=headers or {"Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


@pytest.fixture
def service():
    with _gpm_patched():
        planner = ps.Planner(silent=False)
        srv = ps.make_server(planner, "127.0.0.1", 0)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        yield f"http://127.0.0.1:{srv.server_address[1]}", planner, srv
        srv.shutdown()
        srv.server_close()


# ---- A: tjänsten ----
def test_the_service_gives_exactly_the_same_decisions_as_the_old_path_over_real_http(service):
    url, planner, srv = service
    import gpm
    def old():
        eng = gpm.GlobalPriorityManager()
        return lambda st: eng.evaluate(st)
    def remote():
        assert _http(url, "/reset", {})[0] == 200
        def step(st):
            code, out = _http(url, "/decide", contracts.planner_input_to_wire(st))
            assert code == 200, out
            return out
        return step
    scen = base.scenarios(n=40) + ext.scenarios(n=40)
    rep = parity.compare(scen, old, remote, normalize=contracts.decision_to_wire)
    assert rep.ok, rep.summary()
    assert rep.steps == 40 * 10 + 40 * 8


def test_health_reset_and_error_paths(service):
    url, planner, srv = service
    assert srv.server_address[0] == "127.0.0.1"                                            # bara loopback
    code, h = _http(url, "/health", method="GET")
    assert code == 200 and h["ok"] and h["api_version"] == contracts.API_VERSION and h["calls"] == 0 and h["pid"] == os.getpid()
    st = contracts.planner_input_to_wire(next(iter(base.scenarios(n=1)[0])))
    assert _http(url, "/decide", st)[0] == 200 and _http(url, "/health", method="GET")[1]["calls"] == 1
    assert _http(url, "/reset", {})[0] == 200 and _http(url, "/health", method="GET")[1]["calls"] == 0
    assert _http(url, "/nej", {})[0] == 404 and _http(url, "/nej", method="GET")[0] == 404
    assert _http(url, "/decide", raw=b"{inte json")[0] == 400
    assert _http(url, "/decide", raw=b"[1,2]")[0] == 400                                   # måste vara ett objekt
    code, out = _http(url, "/decide", raw=b"{}", headers={"Content-Type": "application/json", "Content-Length": str(ps.MAX_BODY + 1)})
    assert code == 413 or code == 400
    with patch.object(planner, "decide", side_effect=RuntimeError("smäll")):
        code, out = _http(url, "/decide", st)
        assert code == 500 and "RuntimeError" in out["error"]
    assert _http(url, "/health", method="GET")[0] == 200                                   # tjänsten lever efter felet


def test_the_silent_notifier_swallows_and_counts_calls():
    n = ps.SilentNotifier()
    assert n.alert_high_net_power(5.0, 10, 15) is None and n.send_emil("x", "y") is None and n.calls == 2


# ---- B: bryggan med falska delar ----
class FakeEngine:
    def __init__(self, out=None):
        self.out, self.calls = out or {"pump_mode": "CHEAP", "log": ["a"]}, 0

    def evaluate(self, state):
        self.calls += 1
        return self.out


def _bridge(**kw):
    kw.setdefault("spawn", False)
    kw.setdefault("echo", lambda *a: None)
    return pb.Bridge(**kw)


def _wait(bridge, field, n=1, t=3.0):
    t0 = time.time()
    while time.time() - t0 < t:
        if bridge.stats[field] >= n:
            return True
        time.sleep(0.01)
    return False


def test_mode_defaults_to_local_and_unknown_modes_fall_back_to_local(monkeypatch):
    monkeypatch.delenv("EW_PLANNER_MODE", raising=False)
    said = []
    assert pb.Bridge(echo=said.append).mode == "local"
    assert pb.Bridge(mode="skugga", echo=said.append).mode == "local" and said and "okänt läge" in said[0]
    monkeypatch.setenv("EW_PLANNER_MODE", "shadow")
    b = pb.Bridge(spawn=False, echo=lambda *a: None)
    assert b.mode == "shadow"
    b.close()


def test_local_mode_does_nothing_but_the_old_call():
    posts = []
    b = pb.Bridge(mode="local", post=lambda p, w: posts.append(p), echo=lambda *a: None)
    eng = FakeEngine()
    out = b.evaluate(eng, {"x": 1})
    assert out is eng.out and eng.calls == 1 and posts == [] and b._pool is None and b.stats["submitted"] == 0


def test_shadow_returns_exactly_the_old_decision_and_counts_identical_and_different_ones():
    eng = FakeEngine()
    got = []
    b = _bridge(mode="shadow", warmup=0, post=lambda p, w: got.append(w) or {"pump_mode": "CHEAP", "log": ["a"]})
    assert b.evaluate(eng, {"car_ids": ["a"]}) is eng.out
    assert _wait(b, "identical") and b.stats["diffs"] == 0 and got == [{"car_ids": ["a"]}]
    b2 = _bridge(mode="shadow", warmup=0, post=lambda p, w: {"pump_mode": "EXPENSIVE", "log": ["a", "b"]})
    b2.evaluate(eng, {})
    assert _wait(b2, "diffs") and b2.stats["last_diff"][0][0] in ("log[len]", "pump_mode") and b2.stats["identical"] == 0
    assert {p for p, _, _ in b2.stats["last_diff"]} == {"pump_mode", "log[len]"}


def test_warmup_differences_are_counted_separately():
    b = _bridge(mode="shadow", warmup=2, post=lambda p, w: {"pump_mode": "EXPENSIVE", "log": ["a"]})
    eng = FakeEngine()
    for _ in range(4):
        b.evaluate(eng, {})
        _wait(b, "submitted", b.stats["submitted"] + 1)
        t0 = time.time()
        while b._pending is not None and not b._pending.done() and time.time() - t0 < 2:
            time.sleep(0.005)
    assert b.stats["warmup_diffs"] == 2 and b.stats["diffs"] == 2


def test_errors_are_counted_never_raised_and_a_slow_service_never_blocks():
    boom = _bridge(mode="shadow", post=lambda p, w: (_ for _ in ()).throw(ConnectionRefusedError("nere")))
    assert boom.evaluate(FakeEngine(), {}) is not None
    assert _wait(boom, "errors") and "ConnectionRefusedError" in boom.stats["last_error"]
    gate = threading.Event()
    slow = _bridge(mode="shadow", post=lambda p, w: gate.wait(5) and {})
    eng = FakeEngine()
    t0 = time.time()
    for _ in range(5):
        slow.evaluate(eng, {})
    assert time.time() - t0 < 0.5, "huvudloopen väntade på planeringstjänsten"
    assert slow.stats["submitted"] == 1 and slow.stats["skipped"] == 4                      # ingen kö: pågående anrop => hoppa över
    gate.set()


def test_a_bug_inside_the_bridge_never_reaches_the_main_loop():
    b = _bridge(mode="shadow", post=lambda p, w: {})
    eng = FakeEngine()
    with patch.object(contracts, "planner_input_to_wire", side_effect=ValueError("bugg")):
        assert b.evaluate(eng, {}) is eng.out
    assert b.stats["errors"] == 1 and "ValueError" in b.stats["last_error"]


def test_service_start_restart_backoff_and_startup_grace():
    t = [1000.0]
    procs = []
    class Proc:
        def __init__(self, *a, **k):
            self.args, self.dead, self.terminated = a, False, False
            procs.append(self)
        def poll(self):
            return 1 if self.dead else None
        def terminate(self):
            self.terminated = True
    b = pb.Bridge(mode="shadow", spawn=True, clock=lambda: t[0], popen=Proc, post=lambda p, w: (_ for _ in ()).throw(ConnectionRefusedError("startar")),
                  echo=lambda *a: None, port=8999)
    b._ensure_started()
    assert len(procs) == 1 and procs[0].args[0][-2:] == ["--port", "8999"] and procs[0].args[0][1] == "-u" and procs[0].args[0][2].endswith("planner_service.py")
    b._ensure_started()
    assert len(procs) == 1                                                                  # lever: ingen ny
    b._work({}, {})                                                                         # tjänsten startar fortfarande: ingen räknas som fel
    assert b.stats["errors"] == 0
    t[0] += 100
    b._work({}, {})
    assert b.stats["errors"] == 1                                                           # efter 90 s är det ett fel
    procs[0].dead = True
    t[0] += 5
    b._ensure_started()                                                                     # senaste start var 105 s sedan: omstart är tillåten
    assert len(procs) == 2 and b.stats["restarts"] == 1
    procs[1].dead = True
    t[0] += 10
    b._ensure_started()
    assert len(procs) == 2                                                                  # backoff: högst en start per 30 s
    t[0] += 25
    b._ensure_started()
    assert len(procs) == 3 and b.stats["restarts"] == 2
    for _ in range(8):                                                                      # ihållande krascher: högst fem starter i timmen
        procs[-1].dead = True
        t[0] += 40
        b._ensure_started()
    assert len(procs) == 5
    t[0] += 4000
    procs[-1].dead = True
    b._ensure_started()
    assert len(procs) == 6                                                                  # en timme senare går det igen
    b.close()


def test_a_failing_spawn_is_recorded_not_raised():
    b = pb.Bridge(mode="shadow", spawn=True, popen=MagicMock(side_effect=OSError("kan inte starta")), post=lambda p, w: {}, echo=lambda *a: None)
    b.evaluate(FakeEngine(), {})
    assert _wait(b, "errors") and "OSError" in b.stats["last_error"]


def test_periodic_report_and_rate_limited_logging():
    said, t = [], [0.0]
    b = pb.Bridge(mode="shadow", spawn=False, clock=lambda: t[0], post=lambda p, w: {"pump_mode": "X", "log": []}, warmup=0, echo=said.append, report_every_s=900)
    eng = FakeEngine()
    for i in range(3):
        b.evaluate(eng, {})
        t0 = time.time()
        while not b._pending.done() and time.time() - t0 < 2:
            time.sleep(0.005)
    skillnad = [s for s in said if "skiljer sig" in s]
    assert len(skillnad) == 1                                                               # samma skillnad loggas bara en gång per tio minuter
    t[0] = 1000.0
    b.evaluate(eng, {})
    assert any("jämförelser" in s for s in said)


# ---- main.py använder bryggan, och standard är den gamla vägen ----
def test_main_uses_the_bridge_and_local_is_the_default():
    src = (ROOT / "smartbox" / "main.py").read_text(encoding="utf-8")
    assert "import planner_bridge" in src and "gpm_engine.evaluate(gpm_state)" not in src and "_planner.evaluate(gpm_engine, gpm_state)" in src
    assert 'os.environ.get("EW_PLANNER_MODE", "local")' in (ROOT / "smartbox" / "planner_bridge.py").read_text(encoding="utf-8")


# ---- C: riktig underprocess ----
def test_a_real_planner_process_starts_answers_and_gives_the_same_decisions(db, smartbox):
    """db och smartbox ger processen en riktig testdatabas med tabellerna (gpm läser några inställningar ur den), som i drift."""
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    env = dict(os.environ, EW_PLANNER_PORT=str(port))
    proc = subprocess.Popen([sys.executable, "-u", str(ROOT / "smartbox" / "planner_service.py"), "--port", str(port)], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=str(ROOT / "smartbox"))
    try:
        url = f"http://127.0.0.1:{port}"
        t0, ok = time.time(), False
        while time.time() - t0 < 120 and proc.poll() is None:
            try:
                ok = _http(url, "/health", method="GET")[0] == 200
                break
            except (urllib.error.URLError, ConnectionError, OSError):
                time.sleep(0.5)
        assert ok, f"tjänsten svarade inte: {proc.stdout.read() if proc.poll() is not None else ''}"
        assert _http(url, "/reset", {})[0] == 200
        import gpm
        with patch("gpm.notifier"):
            eng = gpm.GlobalPriorityManager()
            for st in base.scenarios(n=1, steps=6)[0]:
                code, remote = _http(url, "/decide", contracts.planner_input_to_wire(st), timeout=60)
                assert code == 200, remote
                assert parity.diff(contracts.decision_to_wire(eng.evaluate(dict(st))), remote) == []
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
