"""Signed/dated reconstruction using the existing physical-quarter integrator."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest
from hot_water_residual import reconstruct, CONTRACT, CHANNELS

T = datetime(2026, 11, 14, 10, tzinfo=timezone.utc)


def sample(seconds, grid=2000, pv=1000, battery=500, water=1000):
    at = T+timedelta(seconds=seconds)
    row = {"timestamp": at.isoformat()}
    for (watts, stamp, basis), value in zip(CHANNELS, (grid, pv, battery, water)):
        row.update({watts: value, stamp: at.timestamp(), basis: "ha_report"})
    return row


def quarter(**changes):
    return [sample(i*60, **changes) for i in range(16)]


def test_signed_balance_exact_energy_coverage_and_inputs_unchanged():
    samples = quarter()
    original = deepcopy(samples)
    result = reconstruct(samples, CONTRACT)
    assert result["rows"] == [{"t": int(T.timestamp()), "kw": 1.5, "coverage": 1., "covered_energy_kwh": .375}]
    assert result["report"]["accepted_intervals"] == 15
    assert result["baseline_contract"] == "hot_water_excluded" and not result["adoption_ready"]
    assert samples == original


@pytest.mark.parametrize("values", [{"grid": -500, "pv": 2000, "battery": 500, "water": 500},
                                   {"grid": 200, "pv": 0, "battery": -500, "water": 200}])
def test_grid_export_and_battery_discharge_signs(values):
    assert reconstruct(quarter(**values), CONTRACT)["rows"][0]["kw"] == .5


def test_zero_is_real_measurement_missing_is_not_zero_and_no_bridging():
    assert reconstruct(quarter(water=0), CONTRACT)["rows"][0]["kw"] == 2.5
    samples = quarter()
    samples[8]["hot_water_power_w"] = None
    result = reconstruct(samples, CONTRACT)
    assert not result["rows"]
    assert result["report"]["rejected_intervals"]["invalid_endpoint"] == 2
    covered = reconstruct(samples, CONTRACT, min_coverage=.8)["rows"][0]
    assert covered["coverage"] == pytest.approx(13/15)
    assert covered["covered_energy_kwh"] == pytest.approx(1.5*13/60)


@pytest.mark.parametrize("value", [None, True, float("nan"), float("inf"), -1])
def test_bad_hot_water_values_never_yield_residual_quarters(value):
    rows = quarter()
    for row in rows:
        row["hot_water_power_w"] = value
    assert not reconstruct(rows, CONTRACT)["rows"]


def test_source_skew_future_and_missing_dates_are_refused():
    for stamp in (None, T.timestamp()+1, T.timestamp()-6):
        rows = [sample(0), sample(60)]
        rows[0]["pv_sample_at"] = stamp
        result = reconstruct(rows, CONTRACT, min_coverage=.01)
        assert not result["rows"]
    naive = quarter()
    for row in naive:
        row["pv_sample_at"] = "2026-11-14T10:00:00"
    assert not reconstruct(naive, CONTRACT)["rows"]


def test_source_must_remain_fresh_until_interval_end():
    rows = [sample(0), sample(60)]
    for _, stamp, _ in CHANNELS:
        rows[0][stamp] = T.timestamp()-60
    result = reconstruct(rows, CONTRACT, min_coverage=.01)
    assert result["report"]["rejected_intervals"] == {"source_expires_within_interval": 1}
    assert not result["rows"]


def test_receipt_evidence_requires_explicit_offline_acceptance():
    rows = quarter()
    for row in rows:
        row["hot_water_power_basis"] = "local_receipt"
    assert not reconstruct(rows, CONTRACT)["rows"]
    result = reconstruct(rows, CONTRACT, allow_receipt=True)
    assert result["rows"][0]["kw"] == 1.5 and not result["adoption_ready"]
    assert result["report"]["source_bases"]["local_receipt"] == 16


def test_long_gap_and_final_sample_are_not_extrapolated():
    result = reconstruct([sample(0), sample(300)], CONTRACT, min_coverage=.01)
    assert not result["rows"] and result["report"]["rejected_intervals"] == {"sample_gap": 1}
    assert not reconstruct([sample(0)], CONTRACT, min_coverage=.01)["rows"]


def test_inconsistent_energy_balance_and_prior_exclusions_refused():
    assert not reconstruct(quarter(grid=0, pv=0, battery=0, water=100), CONTRACT)["rows"]
    rows = quarter()
    rows[0]["controlled_w"] = [1000]
    with pytest.raises(ValueError, match="again"):
        reconstruct(rows, CONTRACT)
    with pytest.raises(ValueError, match="AC boundary"):
        reconstruct(quarter(), {**CONTRACT, "boundary": "energyhub_dc"})


def test_dst_wall_hours_remain_distinct_and_physical_duplicates_refused():
    rows = []
    for hour in (0, 1):
        start = datetime(2026, 10, 25, hour, tzinfo=timezone.utc)
        for minute in range(16):
            row = sample(0)
            at = start+timedelta(minutes=minute)
            row["timestamp"] = at.astimezone(timezone(timedelta(hours=2-hour))).isoformat()
            for _, stamp, _ in CHANNELS:
                row[stamp] = at.timestamp()
            rows.append(row)
    result = reconstruct(rows, CONTRACT)
    assert len(result["rows"]) == 2 and result["rows"][1]["t"]-result["rows"][0]["t"] == 3600
    with pytest.raises(ValueError, match="Duplicate"):
        reconstruct(rows+[deepcopy(rows[0])], CONTRACT)


@pytest.mark.parametrize("policy", [{"max_age_s": 0}, {"max_skew_s": 100}, {"max_gap_s": 301},
                                   {"min_coverage": 0}, {"allow_receipt": "true"}])
def test_invalid_reconstruction_policy(policy):
    with pytest.raises(ValueError):
        reconstruct([], CONTRACT, **policy)


def test_cli_outputs_only_quarters_and_quality_not_raw_capture(tmp_path):
    source = tmp_path / "capture.json"
    source.write_text(json.dumps({"contract": CONTRACT, "samples": quarter(), "credentials": "secret"}))
    script = Path(__file__).resolve().parents[1] / "scripts" / "reconstruct_hot_water_load.py"
    output = subprocess.run([sys.executable, str(script), str(source)], check=True, capture_output=True, text=True).stdout
    assert json.loads(output)["rows"][0]["kw"] == 1.5 and "secret" not in output


def test_reconstructed_week_feeds_existing_frozen_origin_forecaster():
    from load_forecast_evaluation import forecasts_at_origin
    rows = reconstruct([sample(i*60) for i in range(7*24*60+1)], CONTRACT)["rows"]
    assert len(rows) == 672
    origin = (T+timedelta(days=7)).timestamp()
    predictions = forecasts_at_origin(rows, origin, [origin, origin+900], "UTC")
    assert all(p["baseline_kw"] == pytest.approx(1.5) and p["candidate_kw"] == pytest.approx(1.5) for p in predictions)
