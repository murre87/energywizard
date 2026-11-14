"""Durable shadow-only cycle evaluation. No transport or actuator methods exist."""
from datetime import datetime
from math import isfinite
from uuid import uuid4

from hot_water_observation import assess

TRANSPORTS = {"nibe_local", "myuplink", "ha_entities"}
TERMINAL = {"complete", "cancelled", "interrupted", "unconfirmed"}
ACK_TIMEOUT_S = 60  # simulation acknowledgement deadline, not a hardware timing claim


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError("Finite cycle value required")
    return float(value)


def _stamp(value):
    stamp = datetime.fromisoformat(value)
    if stamp.utcoffset() is None:
        raise ValueError("Cycle time must include UTC offset")
    return stamp.timestamp()


class ShadowCycle:
    """Single-owner evaluator with caller-supplied durable load/save callbacks.

    A successful save must return normally; exceptions prevent action proposals.
    Callbacks must use private local storage. This is not a hardware controller
    and must never be used to authorize writes, including from persisted state.
    """
    def __init__(self, load, save):
        self._save = save
        self.state = {}
        self.storage_error = False
        try:
            saved = load()
            if not isinstance(saved, dict):
                raise ValueError("Invalid shadow-cycle journal")
            if saved:
                # Persisted simulation has no authority in a new process. Keep
                # only an interrupted marker; never restore pending actions.
                self._store({"schema": 1, "mode": "shadow", "phase": "interrupted",
                             "reason": "restart_requires_reconciliation"})
        except Exception:
            self.storage_error = True

    def _store(self, state):
        try:
            self._save(dict(state))
        except Exception:
            self.storage_error = True
            return False
        self.state = state
        return True

    def _status(self, action=None):
        if self.storage_error:
            return {"state": "storage_error", "action": None, "control_ready": False}
        return {"state": self.state.get("phase", "empty"), "reason": self.state.get("reason"),
                "action": action, "token": self.state.get("token") if action else None,
                "control_ready": False}

    def arm(self, proposal, *, now, target_c, max_runtime_s, max_age_s,
            transport, local_rest_enabled, allow_receipt=False, context_id=None):
        if context_id is not None and (not isinstance(context_id, str) or len(context_id) != 64
                                       or any(c not in "0123456789abcdef" for c in context_id)):
            raise ValueError("Invalid cycle context fingerprint")
        if self.storage_error:
            return self._status()
        if self.state:
            if self.state["phase"] != "interrupted" and context_id != self.state.get("context_id"):
                return self._transition("interrupted", "plan_context_changed")
            return self._status()
        now, target_c, runtime, age = map(_number, (now, target_c, max_runtime_s, max_age_s))
        if (proposal.get("state") != "proposed" or transport not in TRANSPORTS
                or type(local_rest_enabled) is not bool or type(allow_receipt) is not bool
                or not 0 < runtime <= 21600 or age <= 0 or not 0 < target_c <= 65):
            raise ValueError("Explicit bounded shadow-cycle policy required")
        if local_rest_enabled and transport != "nibe_local":
            raise ValueError("Enabled local REST must remain preferred")
        start, end, deadline = (_stamp(proposal[k]) for k in ("start", "end", "deadline"))
        if not now <= start < end <= deadline or deadline - now > 36 * 3600:
            raise ValueError("Invalid or expired cycle window")
        state = {"schema": 1, "mode": "shadow", "phase": "planned", "cycle_id": str(uuid4()),
                     "start": start, "end": end, "deadline": deadline, "target_c": target_c,
                     "max_runtime_s": runtime, "max_age_s": age, "transport": transport,
                     "allow_receipt": allow_receipt, "last_at": now}
        if context_id is not None:
            state["context_id"] = context_id
        self._store(state)
        return self._status()

    def _transition(self, phase, reason, **fields):
        state = {**self.state, "phase": phase, "reason": reason, **fields}
        state.pop("token", None)
        self._store(state)
        return self._status()

    def _proposal(self, phase, reason, now, action):
        token = str(uuid4())
        if self._store({**self.state, "phase": phase, "reason": reason,
                        "token": token, "pending_at": now}):
            return self._status(action)
        return self._status()

    def tick(self, observation, *, now, shadow, permitted, manual=False, away=False,
             hygiene=False, cancel=False):
        now = _number(now)
        if any(type(v) is not bool for v in (shadow, permitted, manual, away, hygiene, cancel)):
            raise ValueError("Explicit boolean cycle guards required")
        if self.storage_error or not self.state or self.state["phase"] in TERMINAL:
            return self._status()
        if now < self.state["last_at"]:
            return self._transition("interrupted", "clock_moved_backwards")
        if not self._store({**self.state, "last_at": now}):
            return self._status()
        if not shadow or manual or away or hygiene:
            # Another authority may now own the heater. Never propose cleanup
            # against its settings or carry simulated authority into real mode.
            return self._transition("interrupted", "precedence_or_shadow_changed")
        phase = self.state["phase"]
        if phase in ("start_pending", "release_pending"):
            limit = self.state["pending_at"] + ACK_TIMEOUT_S
            if phase == "start_pending":
                limit = min(limit, self.state["end"])
            if now >= limit:
                return self._transition("unconfirmed", "pending_attempt_not_reconciled")
            return self._status()  # single proposal, never retry an ambiguous attempt
        evidence = assess(observation, now=now, max_age_s=self.state["max_age_s"],
                          allow_receipt=self.state["allow_receipt"])
        fresh = evidence["state"] == "fresh"
        target = fresh and observation["value_c"] >= self.state["target_c"]
        if phase == "planned":
            if cancel or now >= self.state["end"]:
                return self._transition("cancelled", "cancelled_or_window_expired")
            if target:
                return self._transition("complete", "target_already_observed")
            if now > self.state["start"]:
                return self._transition("cancelled", "reserved_start_missed")
            # Do not shift a late start beyond the original reserved window.
            if now != self.state["start"] or not permitted or not fresh:
                return self._status()
            return self._proposal("start_pending", "simulated_start", now, "would_start")
        if phase == "active":
            post_send = fresh and observation["sample_at"] > self.state["started_at"]
            reason = ("cancelled" if cancel else "guard_lost" if not permitted else
                      "runtime_limit" if now >= min(self.state["end"], self.state["started_at"] + self.state["max_runtime_s"]) else
                      "freshness_lost" if not fresh else "target_observed" if target and post_send else None)
            if reason:
                return self._proposal("release_pending", reason, now, "would_release")
        return self._status()

    def acknowledge(self, token, *, outcome, now):
        """Acknowledge a simulated action only: accepted/rejected/uncertain."""
        now = _number(now)
        if outcome not in ("accepted", "rejected", "uncertain"):
            raise ValueError("Explicit simulated acknowledgement required")
        if (self.storage_error or not token or token != self.state.get("token")
                or self.state.get("phase") not in ("start_pending", "release_pending")):
            return self._status()
        limit = self.state["pending_at"] + ACK_TIMEOUT_S
        if self.state["phase"] == "start_pending":
            limit = min(limit, self.state["end"])
        if now < self.state["last_at"] or now < self.state["pending_at"] or now >= limit:
            return self._transition("unconfirmed", "late_or_invalid_acknowledgement")
        if outcome != "accepted":
            return self._transition("unconfirmed", "simulated_attempt_" + outcome)
        if self.state["phase"] == "start_pending":
            return self._transition("active", "simulated_start_accepted", started_at=now, last_at=now)
        return self._transition("complete" if self.state["reason"] == "target_observed" else "cancelled",
                                self.state["reason"], last_at=now)


def open_journal(path):
    """Open an explicit private, single-owner local simulation journal.

    Not a multi-process actuator lock. No default runtime path or engine hook.
    """
    import json
    import os
    from pathlib import Path
    import tempfile

    path = Path(path)

    def load():
        if not path.exists():
            return {}
        if path.stat().st_size > 16_384:
            raise ValueError("Oversized shadow-cycle journal")
        with path.open(encoding="utf-8") as source:
            return json.load(source)

    def save(state):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".hot-water-shadow-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as target:
                json.dump(state, target, allow_nan=False)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    return ShadowCycle(load, save)
