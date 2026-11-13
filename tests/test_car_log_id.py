"""#293: bil-id med versaler (Volvo_Ex40) ska loggas och synas på översikten.

generic_ev/nissan/tesla är redan giltiga kolumnprefix och får inte byta namn.
"""
import car_log
import live_flow
from contextlib import contextmanager
from psycopg.rows import dict_row
from datetime import datetime, timezone
from unittest.mock import Mock


def test_befintliga_id_ar_oforandrade():
    assert car_log.car_log_id("generic_ev") == "generic_ev"
    assert car_log.car_log_id("nissan") == "nissan"
    assert car_log.car_log_id("tesla") == "tesla"
    assert car_log.car_log_column("nissan", "soc") == "nissan_soc"
    assert car_log.car_log_column("tesla", "soc_stale") == "tesla_soc_stale"


def test_versal_id_blir_giltig_loggkolumn():
    assert car_log.car_log_id("Volvo_Ex40") == "volvo_ex40"
    fields = car_log.car_log_fields({
        "Volvo_Ex40_soc": 42,
        "Volvo_Ex40_soc_stale": 0,
        "Volvo_Ex40_charge_completed": True,
        "Volvo_Ex40_climate_temp": 21.5,
        "inte_en_kolumn": 1,
    })
    assert fields["volvo_ex40_soc"] == ("soc", 42)
    assert fields["volvo_ex40_soc_stale"] == ("soc_stale", 0)
    assert fields["volvo_ex40_charge_completed"] == ("charge_completed", 1)
    assert fields["volvo_ex40_climate_temp"] == ("climate_temp", 21.5)
    assert all(not k.startswith("inte") for k in fields)
    assert car_log.car_log_column("Volvo'; DROP TABLE sensor_log", "soc") == "volvo___drop_table_sensor_log_soc"


def test_siffra_forst_far_prefix_sa_sql_namnet_ar_giltigt():
    assert car_log.car_log_column("40ex", "soc") == "c40ex_soc"
    assert car_log.car_log_id("!!!") == "___"
    assert car_log.car_log_id("   ") == ""
    assert car_log.car_id_ok("Volvo_Ex40")
    assert car_log.car_id_ok("generic_ev")
    assert not car_log.car_id_ok("Volvo/Ex40")
    assert not car_log.car_id_ok("")


def test_oversikten_laser_gemen_kolumn_for_versal_id():
    d = live_flow.nodes(
        {"net_power": 100, "pv_power_w": 0, "house_consumption_w": 100, "volvo_ex40_soc": 42},
        cars=[("Volvo_Ex40", "Volvo EX40", None)],
        has_spa=False,
    )
    node = next(n for n in d["nodes"] if n["key"] == "ev_Volvo_Ex40")
    assert node["label"] == "Volvo EX40"
    assert "42 %" in node["detail"]
    assert "Laddar inte" in node["detail"]


def test_oversikten_utan_logg_och_effekt_visar_inte_tom_bil():
    d = live_flow.nodes(
        {"net_power": 100, "pv_power_w": 0, "house_consumption_w": 100},
        cars=[("Volvo_Ex40", "Volvo EX40", None)],
        has_spa=False,
    )
    assert all(n["key"] != "ev_Volvo_Ex40" for n in d["nodes"])


def test_renamed_car_survives_database_logging_and_overview(smartbox, db, monkeypatch, capsys):
    """#287/#293: exercise the writer and reader together, beyond column-name helpers."""
    # The session-local copy shadows the test database table without changing its rows.
    db.execute("CREATE TEMP TABLE sensor_log (LIKE public.sensor_log INCLUDING ALL)")

    @contextmanager
    def connection():
        yield db

    monkeypatch.setattr(smartbox, "get_db", connection)
    monkeypatch.setattr(smartbox, "_car_columns_ok", set())
    monkeypatch.setattr(smartbox, "_bool_columns", None)
    clock = Mock()
    clock.now.side_effect = [datetime(2026, 11, 12, 10, minute, tzinfo=timezone.utc) for minute in (0, 1)]
    monkeypatch.setattr(smartbox, "datetime", clock)
    try:
        common = dict(price=1.0, indoor=20, water=40, target_room=21, water_mode=0,
                      forward=30, retur=25, calc_forward=30, outdoor=5,
                      avg_l1=0, avg_l2=0, avg_l3=0, avg_tot=0, consumed_kwh=0, total_kwh=0,
                      cloud_cover=0, wind_speed=0, net_power=100, wind_dir=0,
                      solar_forecast_w=0, pump={}, house_consumption_w=100)
        for car_id, soc in [("Volvo_Ex40", 42), ("volvo_ex40", 55)]:
            smartbox.log_status(**common, car_data={f"{car_id}_soc": soc,
                               f"{car_id}_charge_completed": True})
        assert "❌" not in capsys.readouterr().out
        with db.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM sensor_log ORDER BY timestamp")
            rows = cur.fetchall()
        assert [row["volvo_ex40_soc"] for row in rows] == [42, 55]
        assert all(row["volvo_ex40_charge_completed"] == 1 for row in rows)
        overview = live_flow.nodes(rows[-1], cars=[("Volvo_Ex40", "Volvo EX40", None)], has_spa=False)
        car = next(n for n in overview["nodes"] if n["key"] == "ev_Volvo_Ex40")
        assert car["label"] == "Volvo EX40" and "55 %" in car["detail"]
    finally:
        db.execute("DROP TABLE pg_temp.sensor_log")
