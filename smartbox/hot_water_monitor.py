"""Default-off asynchronous advisory monitor. Never imports or calls a driver."""
from datetime import datetime, timedelta, timezone
import json
import math
from queue import Empty, Full, Queue
import threading

from hot_water_demand import derive, FIELDS
from hot_water_observation import temperature
from hot_water_plan import propose

DEVICE = "hot_water_shadow_status"
DEMAND_KEY = "hot_water_shadow_demand"
STATES = {"disabled", "requires_shadow", "precedence_blocked", "unsupported_driver",
          "sensor_role_unqualified", "observation_unavailable", "policy_changed", "clock_moved_backwards",
          "target_already_observed", "deadline_missed", "interval_conflict", "proposed",
          "schedule_unavailable", "unavailable"}


def decode(raw, now):
    """Validate owner status; failed/blocked publication becomes unknown after 90s."""
    unknown = {"state": "unknown", "fresh": False, "control_ready": False}
    try:
        if not isinstance(raw, str) or len(raw) > 2048:
            return unknown
        report = json.loads(raw)
        if (type(report["schema"]) is not int or report["schema"] != 1 or report["state"] not in STATES
                or report["simulation_only"] is not True or report["control_ready"] is not False
                or report["reservation_applied"] is not False or report["guard_qualified"] is not False):
            return unknown
        stamp = report["reported_at"]
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not math.isfinite(stamp) or not 0 <= now-stamp <= 90:
            return unknown
        result = {k: report[k] for k in ("schema", "state", "simulation_only", "control_ready",
                                       "reservation_applied", "guard_qualified", "reported_at")}
        if report["state"] == "proposed":
            start, end, deadline = (datetime.fromisoformat(report[k]) for k in ("start", "end", "deadline"))
            if any(t.utcoffset() is None for t in (start, end, deadline)) or not start < end <= deadline:
                return unknown
            for key in ("energy_kwh", "estimated_import_cost"):
                value = report[key]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    return unknown
            if report["energy_kwh"] <= 0:
                return unknown
            result.update({k: report[k] for k in ("start", "end", "deadline", "energy_kwh", "estimated_import_cost")})
        result["fresh"] = True
        return result
    except (ValueError, KeyError, TypeError, AttributeError):
        return unknown


def stored_prices(now):
    """Complete physical quarters from stored intervals; no fetch or filling."""
    import logger
    import nordpool
    start = datetime.fromtimestamp(now, timezone.utc).replace(second=0, microsecond=0)
    start = start.replace(minute=start.minute // 15 * 15)
    end = start + timedelta(hours=36)
    with logger.get_db() as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL statement_timeout = '2s'")
        cur.execute("SELECT time_start,time_end,sek_per_kwh FROM elpriser "
                    "WHERE time_end > %s AND time_start < %s ORDER BY time_start LIMIT 1001", (start, end))
        rows = cur.fetchall()
    if len(rows) > 1000:
        raise ValueError("Too many price intervals")
    intervals = []
    previous_end = None
    for a, b, price in rows:
        if a.utcoffset() is None or b.utcoffset() is None or b <= a:
            raise ValueError("Invalid price dates")
        if previous_end is not None and a < previous_end:
            raise ValueError("Overlapping price intervals")
        previous_end = b
        price = float(price)
        if not math.isfinite(price):
            raise ValueError("Invalid price")
        intervals.append((a, b, price))
    result = []
    for i in range(144):
        t = start + timedelta(minutes=15*i)
        cost, covered = 0.0, 0.0
        for a, b, price in intervals:
            seconds = max(0, (min(t+timedelta(minutes=15), b)-max(t, a)).total_seconds())
            if seconds:
                buy = nordpool.full_buy_cost(price, t)
                if not math.isfinite(buy):
                    raise ValueError("Invalid import cost")
                cost += buy * seconds
                covered += seconds
        if covered == 900:
            result.append({"t": t.isoformat(), "buy": cost/900})
    return result


def read(connection, now=None):
    import time
    from sqlalchemy import text
    row = connection.execute(text("SELECT mode FROM overrides WHERE device=:device"), {"device": DEVICE}).first()
    return decode(row[0] if row else None, time.time() if now is None else now)


def load_state():
    import ew_settings
    return ew_settings.get(DEMAND_KEY, {})


def save_state(state):
    import ew_settings
    ew_settings.update(**{DEMAND_KEY: state})


def publish(report):
    import logger
    with logger.get_db() as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL statement_timeout = '2s'")
        cur.execute("INSERT INTO overrides(device,mode,updated_at) VALUES (%s,%s,NOW()) "
                    "ON CONFLICT(device) DO UPDATE SET mode=EXCLUDED.mode,updated_at=NOW()",
                    (DEVICE, json.dumps(report, allow_nan=False)))


class Evaluator:
    def __init__(self, load=load_state, save=save_state, prices=stored_prices, sink=publish):
        self.load, self.save, self.prices, self.sink = load, save, prices, sink

    def process(self, event):
        report = {"schema": 1, "simulation_only": True, "control_ready": False,
                  "reservation_applied": False, "guard_qualified": False, "reported_at": event["now"]}
        try:
            if not event["enabled"]:
                report["state"] = "disabled"
            elif not event["shadow"]:
                report["state"] = "requires_shadow"
            elif event["manual"] or event["away"] or event["hygiene"]:
                report["state"] = "precedence_blocked"
            elif event["driver"] not in {"nibe_local", "myuplink", "ha_entities"}:
                report["state"] = "unsupported_driver"
            elif event["temperature_role_verified"] is not True:
                report["state"] = "sensor_role_unqualified"
            else:
                state, demand = derive(self.load(), event["observation"], now=event["now"], policy=event["policy"])
                # Persist the fixed demand anchor before publishing any proposal.
                self.save(state)
                basis = event["observation"].get("timestamp_basis")
                report.update(state=demand["state"], timestamp_basis=basis if basis in {
                    "source", "ha_report", "local_receipt"} else "unknown")
                if demand["request"] is not None:
                    proposal = propose(self.prices(event["now"]), **demand["request"])
                    report["demand_state"] = demand["state"]
                    report["state"] = "proposed" if proposal["state"] == "proposed" else "schedule_unavailable"
                    if proposal["state"] == "proposed":
                        report.update({k: proposal[k] for k in ("start", "end", "deadline", "energy_kwh", "estimated_import_cost")})
        except Exception:
            # No raw exception/config/endpoint data in owner status. No proposal
            # survives an unavailable state store, invalid policy or failed read.
            report = {k: v for k, v in report.items() if k in {
                "schema", "simulation_only", "control_ready", "reservation_applied", "guard_qualified", "reported_at"}}
            report["state"] = "unavailable"
        try:
            self.sink(report)
        except Exception:
            pass  # Readers must reject stale status; never block control.
        return report


class Monitor:
    """At most one worker and one waiting sample. submit() performs no I/O."""
    def __init__(self, process=None):
        self._process = process
        self._queue = Queue(maxsize=1)
        self._lock = threading.Lock()
        self._thread = None

    def _run(self):
        process = self._process or Evaluator().process
        while True:
            event = self._queue.get()
            try:
                process(event)
            except Exception:
                pass
            finally:
                self._queue.task_done()

    def submit(self, house, sensors, *, now, shadow, manual, away, hygiene):
        try:
            hp = house.get("heat_pump") or {}
            cfg = hp.get("hot_water_shadow") or {}
            enabled = hp.get("enabled") is True and cfg.get("enabled") is True
            if not enabled and self._thread is None:
                return False
            raw = (sensors or {}).get("water_temp_observation") or temperature(None)
            policy = cfg.get("comfort_policy") or {}
            event = {"enabled": enabled, "driver": hp.get("driver"), "now": now,
                     "shadow": shadow is True, "manual": manual is not False, "away": away is not False,
                     "hygiene": hygiene is not False, "temperature_role_verified": cfg.get("temperature_role_verified") is True,
                     "observation": {k: raw.get(k) for k in ("value_c", "sample_at", "timestamp_basis")},
                     "policy": {k: policy[k] for k in FIELDS if k in policy}}
            with self._lock:
                if self._thread is None:
                    self._thread = threading.Thread(target=self._run, daemon=True, name="hot-water-shadow")
                    self._thread.start()
            try:
                self._queue.put_nowait(event)
            except Full:
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                except Empty:
                    pass
                self._queue.put_nowait(event)
            return True
        except Exception:
            return False
