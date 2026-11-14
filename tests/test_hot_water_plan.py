"""Frozen-input scheduling and energy accounting, without live dependencies."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest
from hot_water_plan import propose, reserve_load

T = datetime(2026, 11, 14, tzinfo=timezone.utc)


def prices(values):
    return [{"t": T + timedelta(minutes=15 * i), "buy": v} for i, v in enumerate(values)]


def plan(rows, **changes):
    request = dict(now=T, earliest=T, deadline=T + timedelta(hours=2),
                   duration_min=30, electrical_power_kw=2)
    return propose(rows, **{**request, **changes})


def test_cheapest_contiguous_window_and_exact_energy():
    result = plan(prices([4, 4, 1, 1, 5, 5]))
    assert result["start"] == (T + timedelta(minutes=30)).isoformat()
    assert result["energy_kwh"] == 1
    assert result["estimated_import_cost"] == 1
    assert sum(r["hot_water_kw"] * .25 for r in result["quarters"]) == 1
    assert result["control_ready"] is False


def test_partial_quarter_and_end_boundary_candidate():
    result = plan(prices([5, -2, 5]), duration_min=20)
    assert result["start"] == (T + timedelta(minutes=10)).isoformat()
    assert result["estimated_import_cost"] == pytest.approx(-1 / 6)
    assert sum(r["hot_water_kw"] * .25 for r in result["quarters"]) == pytest.approx(2 / 3)


def test_now_deadline_and_ties():
    result = plan(prices([1] * 8), now=T + timedelta(minutes=7))
    assert result["start"] == (T + timedelta(minutes=7)).isoformat()
    assert plan(prices([1] * 8), deadline=T + timedelta(minutes=29))["state"] == "unavailable"
    assert plan(prices([1] * 8), deadline=T + timedelta(minutes=30))["end"] == (T + timedelta(minutes=30)).isoformat()


def test_gaps_are_not_filled_and_blocked_windows_are_not_selected():
    rows = prices([-10, -10, 3, 3])
    rows[1]["permitted"] = False
    assert plan(rows)["start"] == (T + timedelta(minutes=30)).isoformat()
    assert plan([rows[0], rows[2]])["state"] == "unavailable"


@pytest.mark.parametrize("changes", [
    {"duration_min": 0}, {"duration_min": 361}, {"duration_min": True},
    {"electrical_power_kw": float("nan")}, {"electrical_power_kw": -1},
    {"now": T.replace(tzinfo=None)}, {"deadline": T + timedelta(hours=37)},
])
def test_invalid_requests_rejected(changes):
    with pytest.raises(ValueError):
        plan(prices([1] * 8), **changes)


@pytest.mark.parametrize("rows", [
    prices([1]) * 2, [{"t": T, "buy": float("inf")}],
    [{"t": T + timedelta(minutes=1), "buy": 1}],
    [{"t": T, "buy": 1, "permitted": "false"}],
])
def test_invalid_prices_rejected(rows):
    with pytest.raises(ValueError):
        plan(rows)


def test_dst_offsets_are_distinct_physical_quarters():
    rows = [{"t": f"2026-10-25T02:{minute:02d}:00{offset}", "buy": price}
            for offset, price in [("+02:00", 5), ("+01:00", 1)] for minute in (0, 15, 30, 45)]
    result = plan(rows, now="2026-10-25T02:00:00+02:00", earliest="2026-10-25T02:00:00+02:00",
                  deadline="2026-10-25T03:00:00+01:00")
    assert result["start"] == "2026-10-25T01:00:00+00:00"


def test_residual_load_contract_no_mutation_and_no_double_reservation():
    proposal = plan(prices([1] * 8))
    forecast = [{**r, "load_kw": .5, "solar_kw": 0, "ev_kw": .3} for r in prices([1] * 8)]
    reserved = reserve_load(forecast, proposal, baseline_contract="hot_water_excluded")
    assert reserved[0]["load_kw"] == 2.5 and reserved[0]["ev_kw"] == .3
    assert forecast[0]["load_kw"] == .5 and "hot_water_kw" not in forecast[0]
    assert sum((r["load_kw"] - .5) * .25 for r in reserved) == proposal["energy_kwh"]
    for bad in (None, "whole_house"):
        with pytest.raises(ValueError):
            reserve_load(forecast, proposal, baseline_contract=bad)
    with pytest.raises(ValueError):
        reserve_load(reserved, proposal, baseline_contract="hot_water_excluded")
    with pytest.raises(ValueError):
        reserve_load([], proposal, baseline_contract="hot_water_excluded")


def test_cli_frozen_input(tmp_path):
    source = tmp_path / "proposal.json"
    source.write_text(json.dumps({"prices": prices([4, 4, 1, 1]), "request": {
        "now": T, "earliest": T, "deadline": T + timedelta(hours=1),
        "duration_min": 30, "electrical_power_kw": 2}}, default=lambda v: v.isoformat()))
    script = Path(__file__).resolve().parents[1] / "scripts" / "propose_hot_water.py"
    result = subprocess.run([sys.executable, str(script), str(source)], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["proposal"]["estimated_import_cost"] == 1


@pytest.mark.parametrize("values,duration", [([4, -2, 3, 1, -1, 5], 20), ([1, 3, -4, 2, 0, 1], 37)])
def test_boundary_search_matches_independent_minute_grid(values, duration):
    result = plan(prices(values), duration_min=duration, deadline=T + timedelta(minutes=90))
    costs = []
    for start in range(91 - duration):
        cost = sum(values[minute // 15] * 2 / 60 for minute in range(start, start + duration))
        costs.append((cost, start))
    expected, _ = min(costs)
    assert result["estimated_import_cost"] == pytest.approx(expected)


def test_reservation_is_consumed_by_existing_battery_optimizer():
    from battery_plan import optimize
    rows = [{**r, "load_kw": .5, "solar_kw": 0, "ev_kw": 0, "sell": 0} for r in prices([1] * 8)]
    reserved = reserve_load(rows, plan(prices([1] * 8)), baseline_contract="hot_water_excluded")
    params = dict(soc0_kwh=0, capacity_kwh=2, reserve_kwh=0, max_kwh=2,
                  charge_kw=1, discharge_kw=1, allowed=("idle",), terminal_pct=0)
    before, after = optimize(rows, **params), optimize(reserved, **params)
    assert after["cost"] - before["cost"] == pytest.approx(1)
