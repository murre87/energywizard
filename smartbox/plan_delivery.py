"""Read-only battery plan/measurement reporting. Positive grid=import, battery=charge."""
from datetime import datetime, timezone
import math


def utc(value):
    t = datetime.fromisoformat(value) if isinstance(value, str) else value
    if t.utcoffset() is None:
        raise ValueError('Timestamps need an offset')
    return t.astimezone(timezone.utc).timestamp()


def finite(value):
    return value is not None and not isinstance(value, bool) and math.isfinite(float(value))


def report(snapshots, samples, start, end, max_gap_s=90):
    """Zero-order hold between adjacent samples <=max_gap_s; never bridge larger gaps.

    Explicit logged plan IDs prevent guessing which retained snapshot was active.
    If IDs change, only a captured activation timestamp can split that interval.
    Costs use captured full import/export tariffs; they are not audited bills.
    """
    start, end = utc(start), utc(end)
    if end <= start or not 0 < max_gap_s <= 300:
        raise ValueError('Invalid report window/gap threshold')
    plans = {}
    for p in snapshots:
        pid = p['plan_id']
        if pid in plans:
            raise ValueError('Duplicate plan identity')
        slots = p['inputs']['slots'];rows = p['output']['rows']
        if len(slots) != len(rows):
            raise ValueError('Plan/result length mismatch')
        plans[pid] = (p, [(utc(s['t']), s, r) for s, r in zip(slots, rows)])
    samples = sorted(samples, key=lambda s: utc(s['timestamp']))
    times = [utc(s['timestamp']) for s in samples]
    if len(set(times)) != len(times):
        raise ValueError('Duplicate measurement timestamp')
    result = {'duration_seconds': end-start, 'coverage_seconds': 0.0,
              'measured_import_kwh': 0.0, 'measured_export_kwh': 0.0,
              'measured_battery_charge_kwh': 0.0, 'measured_battery_discharge_kwh': 0.0,
              'measured_energy_cost': 0.0, 'planned_energy_cost_on_covered_intervals': 0.0,
              'planned_battery_net_kwh_on_covered_intervals': 0.0,
              'planned_load_kwh_on_covered_intervals': 0.0, 'planned_solar_kwh_on_covered_intervals': 0.0,
              'forecast_coverage_seconds': 0.0, 'measured_household_kwh': 0.0,
              'household_forecast_error_kwh': 0.0, 'solar_forecast_error_kwh': 0.0,
              'control_rule_seconds': {}, 'plan_ids': [],
              'counterfactual_savings': None,
              'cost_basis': 'Captured full buy/sell tariffs; measured energy, excludes modeled wear/terminal value',
              'attribution': 'Differences do not establish a cause; no counterfactual baseline evaluated'}
    used = set()
    for left, right, a, b in zip(samples, samples[1:], times, times[1:]):
        if b-a > max_gap_s or b <= start or a >= end:
            continue
        if not all(finite(left.get(k)) and finite(right.get(k)) for k in ('grid_w','battery_w')):
            continue
        pid, next_pid = left.get('plan_id'), right.get('plan_id')
        transitions = [(max(a, start), min(b, end), pid)]
        if pid != next_pid:
            newer = plans.get(next_pid)
            changed = utc(newer[0]['made_at']) if newer else None
            if changed is None or not a <= changed <= b:
                continue  # no evidence for the time of replacement
            transitions = [(max(a,start), min(changed,end), pid),
                           (max(changed,start), min(b,end), next_pid)]
        for lo, hi, active_id in transitions:
            if hi <= lo or active_id not in plans:
                continue
            p, intervals = plans[active_id]
            lo = max(lo, utc(p['made_at']))
            for t, slot, row in intervals:
                seconds = max(0, min(hi, t+900)-max(lo, t))
                if not seconds:
                    continue
                h = seconds/3600
                grid, battery = float(left['grid_w'])/1000, float(left['battery_w'])/1000
                planned_grid = float(row['grid_kw'])
                result['coverage_seconds'] += seconds
                result['measured_import_kwh'] += max(0, grid)*h
                result['measured_export_kwh'] += max(0, -grid)*h
                result['measured_battery_charge_kwh'] += max(0, battery)*h
                result['measured_battery_discharge_kwh'] += max(0, -battery)*h
                result['measured_energy_cost'] += grid*h*slot['buy' if grid >= 0 else 'sell']
                result['planned_energy_cost_on_covered_intervals'] += planned_grid*h*slot['buy' if planned_grid >= 0 else 'sell']
                result['planned_battery_net_kwh_on_covered_intervals'] += row['battery_kw']*h
                result['planned_load_kwh_on_covered_intervals'] += slot['load_kw']*h
                result['planned_solar_kwh_on_covered_intervals'] += slot['solar_kw']*h
                if finite(left.get('pv_w')) and finite(right.get('pv_w')):
                    pv = float(left['pv_w'])/1000
                    household = grid-battery+pv
                    result['forecast_coverage_seconds'] += seconds
                    result['measured_household_kwh'] += household*h
                    result['household_forecast_error_kwh'] += (household-slot['load_kw']-slot.get('ev_kw',0))*h
                    result['solar_forecast_error_kwh'] += (pv-slot.get('solar_kw',0))*h
                rule = (left.get('rule') if left.get('rule') == right.get('rule') else None) or 'unknown'
                result['control_rule_seconds'][rule] = result['control_rule_seconds'].get(rule, 0)+seconds
                used.add(active_id)
    result['plan_ids'] = sorted(used)
    result['coverage_fraction'] = result['coverage_seconds']/(end-start)
    result['complete'] = abs(result['coverage_seconds']-(end-start)) < 1e-6
    delta = result['measured_energy_cost']-result['planned_energy_cost_on_covered_intervals']
    result['cost_difference_on_covered_intervals'] = delta
    result['full_window_cost_difference'] = delta if result['complete'] else None
    return result
