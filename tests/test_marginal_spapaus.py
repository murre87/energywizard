"""2026-10-27: Tesla stod på 91 % kl 05:45 trots schema 100 %. Två åtgärder: en timmes marginal när schemat kräver 100 %, och badets uppvärmning pausas under bilens laddfönster."""
import zoneinfo
from datetime import datetime, timedelta

SWE = zoneinfo.ZoneInfo("Europe/Stockholm")


def test_full_charge_gets_one_hour_margin():
    import decisions

    nu = datetime(2026, 10, 26, 22, 0, tzinfo=SWE)
    avresa = datetime(2026, 10, 27, 5, 45, tzinfo=SWE)
    assert decisions.full_charge_deadline(nu, avresa, 100) == avresa - timedelta(hours=1)       # 100 %: klart en timme före avresan
    assert decisions.full_charge_deadline(nu, avresa, 80) == avresa                              # lägre mål: oförändrat
    assert decisions.full_charge_deadline(nu, avresa, None) == avresa
    assert decisions.full_charge_deadline(nu, None, 100) is None
    sent = datetime(2026, 10, 27, 5, 10, tzinfo=SWE)
    assert decisions.full_charge_deadline(sent, avresa, 100) == avresa                           # mindre än en timme kvar: marginalen ligger redan bakom oss


def _state(nu, **over):
    st = {
        "now": nu, "current_price": 0.8, "all_prices": [0.8] * 96, "pv_power_w": 0.0, "avg_net_w": 6000.0,
        "house_consumption_w": 3000.0, "predicted_base_load_kw": 1.0, "grid_import_w": 6000.0,
        "consumed_kwh_this_hour": 1.0, "power_limit_kw": 11.0, "predicted_cooling_rate": 0.05, "base_load_profile": {},
        "peak_shaving_enabled": False, "solar_is_shaky": False, "indoor_temp": 21.0, "indoor_min": 19.0, "indoor_max": 22.5,
        "water_temp": 50.0, "water_target_normal": 50.0, "spa_temp": 38.0, "spa_normal_temp": 38.5, "days_since_legionella": 1,
        "last_heartbeat": nu, "legionella_max_days": 7, "spa_max_temp": 40.0, "spa_low_temp": 15.0,
        "hysteresis": 0.10, "dynamic_limit": 0.6, "max_fuse_a": 20, "house_load_a": 3.0, "ev_actual_a": 10,
        "current_solar_limit_pct": 100, "current_target_limit": 100,
        "nissan_soc": 60.0, "tesla_soc": 80.0, "nissan_connected": False, "tesla_connected": True,
        "ev_min_charge_a": 6, "ev_max_charge_a": 16, "nissan_charge_completed": True, "tesla_charge_completed": False,
        "nissan_phases": "SinglePhase", "tesla_phases": "ThreePhase", "ev_plan": None, "nissan_prio": 2, "tesla_prio": 1,
        "outdoor_temp": 5.0, "outdoor_avg_5d": 5.0,
    }
    st.update(over)
    return st


def _kor(**over):
    from gpm import GlobalPriorityManager

    nu = datetime(2026, 10, 27, 3, 0, tzinfo=SWE)
    return GlobalPriorityManager().evaluate(_state(nu, **over))


def test_spa_heating_is_paused_while_the_car_charges():
    ak = _kor()
    assert ak["spa_eco"] is True and ak["spa_target"] == 15.0                                    # bilen laddar (10 A): badet i Economy
    assert any("Pausar badets uppvärmning" in rad for rad in ak["log"]), ak["log"]


def test_spa_is_not_paused_when_nothing_charges_or_the_price_is_negative_or_the_spa_is_cold():
    assert _kor(ev_actual_a=0)["spa_eco"] is False                                               # ingen laddning: normaldrift
    assert _kor(current_price=-0.2)["spa_eco"] is False                                          # minuspris: badet värms på gratis el
    ak = _kor(spa_temp=30.0)
    assert not any("Pausar badets uppvärmning" in rad for rad in ak["log"])                      # badet har redan svalnat mer än 5 grader: värms
