"""ramp_budget.py - elbilen och husbatteriet delar säkringens lediga utrymme vid ökningar (#399).

Effekten mäts med fördröjning och som medelvärde. En ökning som just beviljats syns därför inte direkt, och
utan den här budgeten kunde både bilen och batteriet få klartecken mot samma lediga utrymme. En beviljad
ökning räknas mot den andra lasten tills den hunnit synas i mätningen, högst PENDING_S sekunder.
Minskningar och strypningar registreras inte och fördröjs aldrig.

Idé från Darkstars lastbalanserare ("coordinated ramping", github.com/ergetie/darkstar, AGPL-3.0),
egen implementation. Ren klass utan I/O - testas i tests/test_ramp_budget.py."""
import time

PENDING_S = 90.0          # minutloopen: en ökning hinner synas inom en till två mätningar


class RampBudget:
    def __init__(self, pending_s=PENDING_S):
        self.pending_s = pending_s
        self._grants = []           # (ts, kind, ampere per fas)

    def grant(self, kind, delta_a, ts=None):
        """Registrera en beviljad ökning (A per fas). Minskningar (<= 0) ignoreras."""
        if delta_a and delta_a > 0:
            self._grants.append((time.time() if ts is None else float(ts), kind, float(delta_a)))

    def pending_a(self, exclude_kind=None, ts=None):
        """Summan av andra lasters ökningar som ännu inte hunnit synas (A per fas)."""
        now = time.time() if ts is None else float(ts)
        self._grants = [g for g in self._grants if now - g[0] < self.pending_s]
        return sum(a for t, k, a in self._grants if k != exclude_kind)
