"""Sanitized expiring owner status. No driver access or control endpoints."""
import json
import math
import time
from queue import Empty, Full, Queue
import threading

DEVICE = 'hot_water_control_status'
STATES = {'disabled', 'control_blocked', 'unavailable', 'recovery_required', 'storage_error',
          'interrupted', 'complete', 'planned', 'start_pending', 'active', 'release_pending',
          'policy_changed', 'clock_moved_backwards', 'observation_unavailable', 'target_already_observed',
          'deadline_missed', 'interval_conflict', 'comfort_due', 'age_window', 'schedule_unavailable',
          'precedence_blocked', 'guard_blocked'}


def decode(raw, now):
    unknown = {'state': 'unknown', 'fresh': False}
    try:
        if not isinstance(raw, str) or len(raw) > 2048:
            return unknown
        report = json.loads(raw)
        stamp = report['reported_at']
        if (type(report.get('schema')) is not int or report['schema'] != 1
                or report['state'] not in STATES or type(stamp) not in (int, float)
                or not math.isfinite(stamp) or not 0 <= now-stamp <= 90):
            return unknown
        result = {'schema': 1, 'state': report['state'], 'reported_at': stamp, 'fresh': True}
        if report['state'] in {'planned', 'active', 'start_pending', 'release_pending'}:
            values = [report[k] for k in ('start', 'end', 'deadline')]
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in values) or not values[0] < values[1] <= values[2]:
                return unknown
            result.update(zip(('start', 'end', 'deadline'), values))
        return result
    except (ValueError, KeyError, TypeError):
        return unknown


def snapshot(runtime, now):
    report = {'schema': 1, 'reported_at': now, 'state': runtime.report.get('state')}
    if runtime.controller and report['state'] in {'planned', 'active', 'start_pending', 'release_pending'}:
        report.update({k: runtime.controller.state[k] for k in ('start', 'end', 'deadline')})
    # Validate and strip everything else before storing, including raw reasons.
    safe = decode(json.dumps(report, allow_nan=False), now)
    if not safe['fresh']:
        return None
    safe.pop('fresh')
    return safe


def publish(report):
    import logger
    safe = decode(json.dumps(report, allow_nan=False), report['reported_at'])
    if not safe['fresh']:
        return
    safe.pop('fresh')
    with logger.get_db() as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL statement_timeout = '2s'")
        cur.execute('INSERT INTO overrides(device,mode,updated_at) VALUES (%s,%s,NOW()) '
                    'ON CONFLICT(device) DO UPDATE SET mode=EXCLUDED.mode,updated_at=NOW()',
                    (DEVICE, json.dumps(safe, allow_nan=False)))


class Publisher:
    """One waiting report; database failure/latency never blocks the engine."""
    def __init__(self, writer=publish):
        self.writer = writer
        self.queue = Queue(maxsize=1)
        self.thread = None

    def _run(self):
        while True:
            report = self.queue.get()
            try:
                self.writer(report)
            except Exception:
                pass
            finally:
                self.queue.task_done()

    def submit(self, runtime, now):
        try:
            report = snapshot(runtime, now)
            if report is None:
                return False
            if self.thread is None:
                self.thread = threading.Thread(target=self._run, name='hot-water-status', daemon=True)
                self.thread.start()
            try:
                self.queue.put_nowait(report)
            except Full:
                try:
                    self.queue.get_nowait()
                    self.queue.task_done()
                except Empty:
                    pass
                self.queue.put_nowait(report)
            return True
        except Exception:
            return False


def read(connection, now=None):
    from sqlalchemy import text
    row = connection.execute(text('SELECT mode FROM overrides WHERE device=:device'), {'device': DEVICE}).first()
    return decode(row[0] if row else None, time.time() if now is None else now)
