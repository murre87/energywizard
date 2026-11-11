"""Local, bounded planner evidence. No network, database or device dependencies."""
import hashlib
from functools import lru_cache
import json
import math
import os
from pathlib import Path
from queue import Queue
import tempfile
import threading
from datetime import datetime, timezone

SCHEMA = 1
MAX_BYTES = 2_000_000
MAX_FILES = 96
MAX_AGE_S = 7 * 86400
MAX_SLOTS = 192
PARAMS = {
    'soc0_kwh', 'capacity_kwh', 'reserve_kwh', 'max_kwh', 'charge_kw', 'discharge_kw',
    'eff', 'step_kwh', 'switch_cost', 'cycle_cost', 'terminal_pct', 'allow_export',
    'charge_wear_cost_sek_per_kwh', 'discharge_wear_cost_sek_per_kwh',
    'reversal_cost_sek', 'ev_mode', 'allowed',
}
SLOT_NUMBERS = ('buy', 'sell', 'load_kw', 'solar_kw', 'ev_kw')
_queue = Queue(maxsize=1)
_lock = threading.Lock()
_worker = None


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


@lru_cache(maxsize=1)
def planner_hash():
    return hashlib.sha256(Path(__file__).with_name('battery_plan.py').read_bytes()).hexdigest()


def timestamp(value):
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError('Planner timestamps must include a UTC offset')
    return value.isoformat()


def number(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError('Planner numbers must be finite')
    return value


def normalize_inputs(slots, params):
    if not 1 <= len(slots) <= MAX_SLOTS or set(params) - PARAMS:
        raise ValueError('Unsupported planner inputs')
    from battery_plan import ACTIONS
    out = []
    previous = None
    for slot in slots:
        t = timestamp(slot['t'])
        dt = datetime.fromisoformat(t).astimezone(timezone.utc)
        if previous is not None and (dt - previous).total_seconds() != 900:
            raise ValueError('Planner slots must be consecutive physical quarters')
        previous = dt
        out.append({'t': t, **{k: number(slot.get(k, 0.0)) for k in SLOT_NUMBERS}})
    clean = {}
    for k, v in params.items():
        if k == 'allowed':
            if not set(v) <= set(ACTIONS):
                raise ValueError('Unsupported actions')
            clean[k] = sorted(set(v))
        elif k == 'ev_mode':
            if v not in ('block', 'offload', 'free'):
                raise ValueError('Unsupported EV policy')
            clean[k] = v
        elif k == 'allow_export':
            if not isinstance(v, bool):
                raise ValueError('Export policy must be boolean')
            clean[k] = v
        else:
            clean[k] = None if k == 'step_kwh' and v is None else number(v)
    # Bind all defaults, so future changes cannot silently change captured semantics.
    import inspect
    from battery_plan import optimize
    bound = inspect.signature(optimize).bind(slots=out, **clean)
    bound.apply_defaults()
    clean = {k: (sorted(v) if k == 'allowed' else v) for k, v in bound.arguments.items() if k != 'slots'}
    return {'slots': out, 'params': clean}


def normalized_result(result):
    rows = [{'t': timestamp(r['t']), 'action': r['action'],
             **{k: r[k] for k in ('soc_kwh', 'battery_kw', 'grid_kw', 'cost', 'buy',
                                  'wear_cost_sek', 'direction_reversal')}} for r in result['rows']]
    return {'rows': rows, **{k: result[k] for k in ('cost', 'baseline_cost', 'saving_kr',
                                                   'wear_cost_sek', 'reversal_cost_sek')}}


def build(slots, params, result, made_at):
    payload = {'schema_version': SCHEMA, 'planner_hash': planner_hash(),
               'made_at': timestamp(made_at), 'inputs': normalize_inputs(slots, params),
               'output': normalized_result(result)}
    # No environment/config dump: source hash identifies exact planning code.
    payload['plan_id'] = hashlib.sha256(canonical(payload).encode()).hexdigest()
    if len(canonical(payload).encode()) > MAX_BYTES:
        raise ValueError('Snapshot exceeds size limit')
    return payload


def replay(payload):
    from battery_plan import optimize
    if payload.get('schema_version') != SCHEMA or payload.get('planner_hash') != planner_hash():
        raise ValueError('Snapshot schema/planner version does not match')
    content = {k: v for k, v in payload.items() if k != 'plan_id'}
    if hashlib.sha256(canonical(content).encode()).hexdigest() != payload.get('plan_id'):
        raise ValueError('Snapshot identity does not match content')
    inputs = normalize_inputs(**payload['inputs'])
    result = normalized_result(optimize(inputs['slots'], **inputs['params']))
    # Same code and normalized floats: exact action/numeric replay, deterministic action order.
    return {'plan_id': payload['plan_id'], 'matches': result == payload['output'], 'output': result}


def store(payload, directory):
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    raw = canonical(payload).encode()
    if len(raw) > MAX_BYTES:
        raise ValueError('Snapshot exceeds size limit')
    # Atomic owner-only files. Retention is count- and age-bounded (<=192 MB).
    now = datetime.now(timezone.utc).timestamp()
    files = sorted(folder.glob('*.json'), key=lambda f: f.stat().st_mtime, reverse=True)
    for i, f in enumerate(files):
        if i >= MAX_FILES - 1 or now - f.stat().st_mtime > MAX_AGE_S:
            f.unlink()
    fd, name = tempfile.mkstemp(prefix='.plan-', dir=folder)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
        os.replace(name, folder / (payload['plan_id'] + '.json'))
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _run():
    while True:
        item = _queue.get()
        try:
            store(*item)
        except Exception:
            pass  # Evidence must never affect device control; no raw config/error dumps.
        finally:
            _queue.task_done()


def capture(slots, params, result, made_at):
    """Best-effort capture: never wait for disk, queue space or a stuck writer."""
    global _worker
    try:
        if os.environ.get('EW_PLAN_SNAPSHOTS', '1') == '0':
            return None
        payload = build(slots, params, result, made_at)
        with _lock:
            if _worker is None:
                _worker = threading.Thread(target=_run, name='plan-snapshots', daemon=True)
                _worker.start()
        _queue.put_nowait((payload, os.environ.get('EW_PLAN_SNAPSHOT_DIR', '/data/planning-snapshots')))
        return payload['plan_id']
    except Exception:
        return None
