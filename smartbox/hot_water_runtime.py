"""Explicitly opted-in local boost runtime; disabled installations perform no I/O."""
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

from hot_water_control import BoostController
from hot_water_demand import derive
from hot_water_monitor import stored_prices
from hot_water_plan import propose


class Journal:
    """Strict private atomic state plus a lifetime process lock (Linux runtime)."""
    def __init__(self, path):
        import fcntl
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.path) + '.lock', os.O_CREAT | os.O_RDWR, 0o600)
        self.lock = os.fdopen(fd, 'a')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            self.lock.close()
            raise

    def load(self):
        try:
            with self.path.open(encoding='utf-8') as source:
                raw = source.read(32769)
        except FileNotFoundError:
            return {}
        if len(raw) > 32768:
            raise ValueError('Oversized control journal')
        state = json.loads(raw)
        if not isinstance(state, dict):
            raise ValueError('Invalid runtime journal')
        return state

    def save(self, state):
        fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix='.hot-water-control-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as target:
                json.dump(state, target, allow_nan=False)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def selected(house):
    hp = house.get('heat_pump') or {}
    return (hp.get('enabled') is True and hp.get('driver') == 'nibe_local'
            and (hp.get('hot_water_control') or {}).get('enabled') is True)


def control_context(house, driver):
    hp = house['heat_pump']
    cfg = hp['hot_water_control']
    return hashlib.sha256(json.dumps(
        {'connection': hp.get('connection'), 'points': hp.get('points'),
         'local_identity': {k: getattr(driver, k, None) for k in
                            ('_host', '_port', '_index', '_expected_product', '_expected_serial')},
         'policy': cfg['comfort_policy'], 'max_runtime_s': cfg['max_runtime_s']},
        sort_keys=True, allow_nan=False).encode()).hexdigest()


def permitted(*, meter_fresh, fuse_fresh, currents, filtered, fuse_a, margin_a,
              peak_ok, additional_kw):
    """Conservative start headroom: all additional load could land on one phase."""
    if meter_fresh is not True or fuse_fresh is not True or peak_ok is not True:
        return False
    values = [*currents, *filtered, fuse_a, margin_a, additional_kw]
    if (len(currents) != 3 or len(filtered) != 3 or any(
            type(v) not in (int, float) or not math.isfinite(v) for v in values)
            or fuse_a <= 0 or margin_a < 0 or additional_kw < 0):
        return False
    return max(max(currents), max(filtered)) + additional_kw * 1000 / 230 <= fuse_a - margin_a


class Runtime:
    def __init__(self, path=None, *, prices=stored_prices, journal_factory=Journal):
        self.path, self.prices, self.journal_factory = path, prices, journal_factory
        self.controller = None
        self.journal = None
        self.state = {}
        self.context = None
        self.failed = False
        self.recovery_blocked = False
        self.retry_at = 0
        self.report = {'state': 'disabled'}

    def _save(self, **changes):
        state = {**self.state, **changes}
        self.journal.save(state)
        self.state = state

    def _cycle_save(self, cycle):
        changes = {'cycle': cycle}
        if cycle['phase'] == 'active':
            changes['last_trigger_at'] = cycle['attempted_at']
        self._save(**changes)

    def _new_controller(self, driver, saved):
        return BoostController(driver, lambda: saved, self._cycle_save, context_id=self.context)

    def tick(self, house, driver, observation, *, now, shadow, manual, away, hygiene, guard_ok):
        """Called serially by main. No implicit ownership takeover or recovery."""
        hp = house.get('heat_pump') or {}
        cfg = hp.get('hot_water_control') or {}
        if not selected(house):
            if self.controller:
                self.controller.tick(observation, now=now, shadow=True,
                                     ownership_confirmed=False, permitted=False)
            self.report = {'state': 'disabled'}
            return self.report
        try:
            if any(type(v) is not bool for v in (shadow, manual, away, hygiene, guard_ok)):
                raise ValueError('Explicit runtime guards required')
            # Persisted configuration acknowledges the one-writer handover, but
            # does not authorize recovery of an old process's active command.
            owner = cfg.get('exclusive_owner_confirmed') is True
            policy = cfg['comfort_policy']
            context = control_context(house, driver)
            if self.context is not None and context != self.context:
                self.failed = True
            if self.failed:
                self.report = {'state': 'unavailable'}
                return self.report
            blocked = (shadow or not owner or hp.get('control_enabled') is not True
                       or cfg.get('temperature_role_verified') is not True
                       or 'hot_water_boost' not in driver.capabilities())
            if blocked:
                if self.controller:
                    self.controller.tick(observation, now=now, shadow=True,
                                         ownership_confirmed=False, permitted=False)
                self.report = {'state': 'control_blocked'}
                return self.report
            if self.controller is None:
                path = self.path
                if path is None:
                    import ew_settings
                    path = Path(ew_settings.PATH).parent / 'hot-water-control.json'
                self.journal = self.journal_factory(path)
                self.state = self.journal.load()
                self.context = context
                if self.state and (self.state.get('schema') != 1 or self.state.get('context_id') != context):
                    raise ValueError('Runtime journal context changed')
                if not self.state:
                    self._save(schema=1, context_id=context, demand={}, cycle={})
                self.controller = self._new_controller(driver, self.state['cycle'])
                self.recovery_blocked = self.controller.recovery
                if self.controller.state.get('reason') == 'restart_before_start':
                    self._save(cycle={})
                    self.controller = self._new_controller(driver, {})
            if self.recovery_blocked:
                self.report = {'state': 'recovery_required'}
                return self.report
            c = self.controller
            if c.storage_error or c.state.get('phase') == 'interrupted':
                self.report = c.status()
                return self.report
            if c.state.get('phase') == 'complete':
                # Completed cycles are safe to replace. Preserve real trigger
                # history and demand anchors across every subsequent schedule.
                self._save(cycle={})
                self.controller = c = self._new_controller(driver, {})
            if not c.state and not (manual or away or hygiene) and guard_ok and now >= self.retry_at:
                demand_state, demand = derive(self.state['demand'], observation, now=now,
                    policy=policy, last_trigger_at=self.state.get('last_trigger_at'))
                self._save(demand=demand_state)
                self.report = {'state': demand['state']}
                if demand['request'] is not None:
                    plan = propose(self.prices(now), **demand['request'])
                    if plan['state'] == 'proposed':
                        stamp = lambda key: datetime.fromisoformat(plan[key]).timestamp()
                        c.arm(now=now, start=stamp('start'), end=stamp('end'), deadline=stamp('deadline'),
                              target_c=policy['target_c'], max_runtime_s=cfg['max_runtime_s'],
                              max_age_s=policy['max_age_s'], allow_receipt=policy['allow_receipt'])
                    else:
                        self.retry_at = now + 60
                        self.report = {'state': 'schedule_unavailable'}
            if c.state:
                self.report = c.tick(observation, now=now, shadow=shadow, ownership_confirmed=owner,
                                     permitted=guard_ok, manual=manual, away=away, hygiene=hygiene)
            elif manual or away or hygiene:
                self.report = {'state': 'precedence_blocked'}
            elif not guard_ok:
                self.report = {'state': 'guard_blocked'}
        except Exception:
            self.failed = True  # No fail-open legacy writer or raw exception data.
            self.report = {'state': 'unavailable'}
        return self.report
