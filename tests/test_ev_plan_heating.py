"""End-to-end: den riktiga calculate_ev_charge_plan mot stubbad databas/prognos/baslastprofil.
Visar fysiken: kallare väder ändrar INTE energin (kWh) men minskar effekten per ruta, så fler rutor behövs."""
import contextlib
import importlib
import os
import sys
import types
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

SMARTBOX = os.path.join(os.path.dirname(__file__), "..", "smartbox")
NOW = datetime(2026, 11, 8, 18, 0, tzinfo=ZoneInfo("Europe/Stockholm"))          # söndag kväll


def _stubs(forecast_temp):
    learning = types.ModuleType("learning")
    learning.get_base_load_profile = lambda *a, **k: {(d, h): 3.0 for d in range(7) for h in range(24)}
    learning.predict_base_load = lambda dt, profile: max(1.0, min(profile.get((dt.weekday(), dt.hour), 2.5), 6.0)) if profile else 2.5

    @contextlib.contextmanager
    def get_db():
        yield object()
    logger = types.ModuleType("logger")
    logger.get_db = get_db
    logger.get_monthly_power_peaks = lambda: {}
    weather = types.ModuleType("weather")
    weather.get_smart_solar_w = lambda cloud, dt: 0.0
    settings = types.ModuleType("settings")
    settings.is_high_load_time = lambda ts: False
    return {"learning": learning, "logger": logger, "weather": weather, "settings": settings}


def _read_sql_factory(forecast_temp):
    hours = pd.date_range("2026-11-08 18:00", periods=40, freq="h")
    prices = pd.DataFrame({"t": hours, "sek_per_kwh": [0.4 if (h.hour >= 22 or h.hour < 6) else 1.4 for h in hours]})
    weather = pd.DataFrame({"t": hours, "cloud_cover": 90.0, "temp": forecast_temp})

    def read_sql(sql, conn, params=None):
        if "FROM elpriser" in sql:
            return prices.copy()
        if "FROM weather_forecast" in sql:
            return weather.copy()
        raise AssertionError(sql)
    return read_sql


@pytest.fixture
def plan(monkeypatch):
    def run(forecast_temp, model):
        for name, mod in _stubs(forecast_temp).items():
            monkeypatch.setitem(sys.modules, name, mod)
        monkeypatch.syspath_prepend(SMARTBOX)
        sys.modules.pop("decisions", None)
        decisions = importlib.import_module("decisions")
        monkeypatch.setattr(pd, "read_sql", _read_sql_factory(forecast_temp))
        car_data = {
            "car_ids": ["id4"], "id4_soc": 50, "id4_plugged_in": True, "id4_phases": None,
            "car_specs": {"id4": {"name": "ID.4", "max_a": 16, "phases": "auto", "battery_kwh": 77, "max_charge_kw": 7.4}},
            "heating_model": model,
        }
        schedule = {"id4": {0: {"enabled": True, "target_time": "07:00", "target_soc": 80, "panic_mode": False}}}
        cfg = {"fuse_size_a": 20, "power_limit_kw_bas": 8.0, "power_limit_kw_hog": 8.0, "peak_shaving_enabled": True}
        df = decisions.calculate_ev_charge_plan(NOW, schedule, car_data, cfg)
        sys.modules.pop("decisions", None)
        return df
    return run


MODEL = {"k_kw_per_degree": 0.25, "balance_c": 10.0, "hd_ref": 4.0, "cap_kw": 10.0}


def summarize(df):
    used = df[df["id4_kw"] > 0].copy()
    used["hour"] = used["t_slot"].dt.floor("h")
    per_hour = used.groupby("hour")["id4_kw"].sum() / 4.0                    # kWh per klocktimme
    return {"slots": len(used), "kwh": float(used["id4_kw"].sum() / 4.0), "hours_used": int(per_hour.size),
            "max_kwh_per_hour": float(per_hour.max()), "base_kw": float(df["house_load_kw"].iloc[0])}


NEEDED_KWH = 0.30 * 77 * 1.12                      # 50 -> 80 % av 77 kWh, inkl. de 12 % laddförluster planeraren alltid lägger på
ONE_MIN_SLOT_KWH = 6 * (7.4 / 16) / 4.0           # planeraren kan överskjuta med högst en ruta på lägsta effekt


def test_cold_spreads_the_same_energy_over_more_hours(plan):
    warm = summarize(plan(forecast_temp=8.0, model=MODEL))
    cold = summarize(plan(forecast_temp=-4.0, model=MODEL))
    print("warm", warm, "cold", cold)
    for r in (warm, cold):                                       # energin ändras inte med temperaturen
        assert NEEDED_KWH - 0.01 <= r["kwh"] <= NEEDED_KWH + ONE_MIN_SLOT_KWH
    assert cold["base_kw"] > warm["base_kw"]                     # värmelasten syns som högre baslast
    assert cold["max_kwh_per_hour"] < warm["max_kwh_per_hour"]   # mindre utrymme per timme
    assert cold["hours_used"] > warm["hours_used"]               # -> laddningen sprids över fler timmar


def test_without_model_temperature_changes_nothing(plan):
    a = summarize(plan(forecast_temp=8.0, model=None))
    b = summarize(plan(forecast_temp=-4.0, model=None))
    assert a == b


def test_model_at_profile_regime_matches_no_model(plan):
    at_ref = summarize(plan(forecast_temp=6.0, model=MODEL))      # 10-6 = 4 gradtimmar = hd_ref -> ingen justering
    none = summarize(plan(forecast_temp=6.0, model=None))
    assert at_ref == none
