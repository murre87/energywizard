import os, sys
from datetime import datetime, timedelta
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "smartbox"))
import ev_heating as h

MODEL = {"k_kw_per_degree": 0.2, "balance_c": 10.0, "hd_ref": 4.0, "cap_kw": 10.0}


def test_heating_degrees():
    assert h.heating_degrees(10, 10) == 0 and h.heating_degrees(15, 10) == 0
    assert h.heating_degrees(-5, 10) == 15


def test_colder_than_profile_regime_adds_load_warmer_removes_it():
    base = 3.0
    assert abs(h.adjust_base_load(base, -6, MODEL) - (3.0 + 0.2 * (16 - 4))) < 1e-9     # -6 C: 16 degrees below balance
    assert abs(h.adjust_base_load(base, 12, MODEL) - (3.0 + 0.2 * (0 - 4))) < 1e-9      # warm: heating goes away
    assert h.adjust_base_load(base, 6, MODEL) == base                                  # exactly the profile regime


def test_floor_and_cap():
    assert h.adjust_base_load(1.2, 15, MODEL) == 1.0                                   # would be 0.4 -> floor
    assert h.adjust_base_load(6.0, -30, MODEL) == 10.0                                 # capped
    assert h.adjust_base_load(6.0, -30, MODEL, cap_kw=7.0) == 7.0


def test_unknown_temperature_or_model_leaves_base_unchanged():
    for t in (None, float("nan")):
        assert h.adjust_base_load(3.0, t, MODEL) == 3.0
    assert h.adjust_base_load(3.0, -10, None) == 3.0


def make_history(k_true, days=30, seed=1, flat=False):
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2026-10-01", periods=days * 24, freq="h")
    day = np.arange(len(ts)) // 24
    temp = np.full(len(ts), 8.0) if flat else 8.0 + 9.0 * np.sin(day / 4.0) + 2.0 * np.sin(2 * np.pi * (np.arange(len(ts)) % 24) / 24)
    gd = np.clip(10.0 - temp, 0, None)
    daily = 1.2 + 0.8 * np.sin(2 * np.pi * (np.arange(len(ts)) % 24 - 6) / 24).clip(0)      # normal daily pattern
    load = daily + k_true * gd + rng.normal(0, 0.1, len(ts))
    return pd.DataFrame({"ts": ts, "other_kw": load, "temp": temp})


def test_fit_recovers_the_true_slope_despite_daily_pattern():
    model = h.fit_heating_model(make_history(0.18), balance_c=10.0)
    assert model is not None
    assert abs(model["k_kw_per_degree"] - 0.18) < 0.02
    assert model["n"] == 30 * 24
    assert 0 < model["hd_ref"] < 20


def test_fit_none_when_temperature_is_flat_or_data_thin():
    assert h.fit_heating_model(make_history(0.18, flat=True), 10.0) is None
    assert h.fit_heating_model(make_history(0.18, days=5), 10.0) is None
    assert h.fit_heating_model(None, 10.0) is None


def test_fit_never_returns_negative_slope():
    df = make_history(-0.3)                               # load falls when it gets colder (nonsense for heating)
    assert h.fit_heating_model(df, 10.0)["k_kw_per_degree"] == 0.0


def test_model_from_slope_uses_history_for_reference():
    m = h.model_from_slope(make_history(0.1), 10.0, 0.25)
    assert m["k_kw_per_degree"] == 0.25 and m["hd_ref"] > 0
    assert h.model_from_slope(make_history(0.1, days=0), 10.0, 0.25) is None


def test_hourly_frame_joins_and_averages():
    loads = pd.DataFrame({"ts": pd.date_range("2026-11-01 00:00", periods=120, freq="min"), "other_kw": 2.0})
    temps = pd.DataFrame({"ts": pd.date_range("2026-11-01 00:00", periods=2, freq="h"), "temp": [1.0, 3.0]})
    out = h.hourly_frame(loads, temps)
    assert list(out["temp"]) == [1.0, 3.0] and list(out["other_kw"]) == [2.0, 2.0]
    assert len(h.hourly_frame(loads, temps.iloc[0:0])) == 0
    assert len(h.hourly_frame(None, temps)) == 0
