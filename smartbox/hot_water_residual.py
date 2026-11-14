"""Offline signed/dated residual-load reconstruction; no forecast adoption."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import math

from load_forecast_evaluation import aggregate, base_load_w

CONTRACT = {"boundary": "ac_household", "grid_sign": "import_positive",
            "battery_sign": "charge_positive", "excluded_loads": ["hot_water"]}
CHANNELS = (("grid_w", "grid_sample_at", "grid_basis"),
            ("pv_w", "pv_sample_at", "pv_basis"),
            ("battery_w", "battery_sample_at", "battery_basis"),
            ("hot_water_power_w", "hot_water_power_sample_at", "hot_water_power_basis"))


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Finite numeric evidence required")
    return float(value)


def _epoch(value):
    if isinstance(value, (int, float)):
        return _finite(value)
    try:
        stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
    except ValueError:
        raise ValueError("Source dates require a UTC offset or epoch seconds") from None
    if not isinstance(stamp, datetime) or stamp.utcoffset() is None:
        raise ValueError("Source dates require a UTC offset or epoch seconds")
    return stamp.timestamp()


def reconstruct(samples, contract, *, max_age_s=90, max_skew_s=5, max_gap_s=90,
                min_coverage=.9, allow_receipt=False):
    """Use grid + PV - battery_charge - dedicated_hot_water at one AC boundary.

    Contract and provenance labels are supplied evidence declarations, not proof
    of a physical boundary or synchronized device clocks. Missing evidence never
    becomes zero, log time never becomes source time, and bad rows are not bridged.
    """
    if contract != CONTRACT:
        raise ValueError("Explicit AC boundary, signs and hot-water-only exclusion required")
    age, skew, gap, coverage = map(_finite, (max_age_s, max_skew_s, max_gap_s, min_coverage))
    if not (0 < age <= 300 and 0 <= skew <= age and 0 < gap <= 300 and 0 < coverage <= 1) or type(allow_receipt) is not bool:
        raise ValueError("Invalid reconstruction policy")
    if not isinstance(samples, list) or len(samples) > 100000 or any(not isinstance(s, dict) for s in samples):
        raise ValueError("At most 100000 explicit measurement rows")
    if any("controlled_w" in s or "hot_water_kw" in s for s in samples):
        raise ValueError("Already excluded/reserved loads cannot be reconstructed again")
    ordered = sorted((_epoch(s["timestamp"]), i, s) for i, s in enumerate(samples))
    if len({t for t, _, _ in ordered}) != len(ordered):
        raise ValueError("Duplicate physical sample timestamp")
    invalid, rejected, bases = Counter(), Counter(), Counter()
    prepared = []
    for t, _, sample in ordered:
        reason, stamps = None, []
        try:
            values, sample_bases = [], []
            for watts, date, basis in CHANNELS:
                values.append(_finite(sample.get(watts)))
                stamp = _epoch(sample.get(date))
                label = sample.get(basis)
                if label not in {"source", "ha_report", "local_receipt"}:
                    reason = "unknown_provenance"
                    break
                if label == "local_receipt" and not allow_receipt:
                    reason = "receipt_only"
                    break
                if not 0 <= t-stamp <= age:
                    reason = "stale_or_future_source"
                    break
                stamps.append(stamp)
                sample_bases.append(label)
            if reason is None and max(stamps)-min(stamps) > skew:
                reason = "source_alignment"
            if reason is None:
                residual = base_load_w(*values[:3], controlled_w=[values[3]])
                if not math.isfinite(residual):
                    reason = "invalid_energy_balance"
                else:
                    bases.update(sample_bases)
        except (ValueError, TypeError, AttributeError, OverflowError):
            reason = "missing_or_invalid_measurement"
        if reason:
            invalid[reason] += 1
            prepared.append((t, None, None))
        else:
            prepared.append((t, {"timestamp": datetime.fromtimestamp(t, timezone.utc).isoformat(), "grid_w": values[0], "pv_w": values[1],
                                  "battery_w": values[2], "controlled_w": [values[3]]}, min(stamps)))
    sums = defaultdict(lambda: [0., 0.])
    accepted = 0
    for (start, a, oldest), (end, b, _) in zip(prepared, prepared[1:]):
        if a is None or b is None:
            rejected["invalid_endpoint"] += 1
            continue
        if end-start > gap:
            rejected["sample_gap"] += 1
            continue
        if end-oldest > age:
            rejected["source_expires_within_interval"] += 1
            continue
        # Each pair is independent: never filter out a bad row and then connect
        # its neighbours. Reuse the established left-hold UTC-quarter integrator.
        pair, _ = aggregate([a, b], min_coverage=1e-12, max_gap_s=gap)
        if any(not math.isfinite(row["kw"]) for row in pair):
            rejected["numeric_overflow"] += 1
            continue
        for row in pair:
            seconds = row["coverage"] * 900
            sums[row["t"]][0] += row["kw"] * seconds
            sums[row["t"]][1] += seconds
        accepted += 1
    rows = [{"t": t, "kw": energy/seconds, "coverage": min(1., seconds/900),
             "covered_energy_kwh": energy/3600}
            for t, (energy, seconds) in sorted(sums.items()) if seconds/900+1e-12 >= coverage]
    return {"baseline_contract": "hot_water_excluded", "excluded_loads": ["hot_water"],
            "adoption_ready": False, "rows": rows,
            "report": {"input_samples": len(samples), "invalid_samples": dict(invalid),
                       "accepted_intervals": accepted, "rejected_intervals": dict(rejected),
                       "accepted_quarters": len(rows), "source_bases": dict(bases),
                       "max_age_s": age, "max_skew_s": skew, "max_gap_s": gap,
                       "minimum_quarter_coverage": coverage, "receipt_evidence_accepted": allow_receipt}}
