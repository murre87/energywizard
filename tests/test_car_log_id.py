"""#293: bil-id med versaler (Volvo_Ex40) ska loggas och synas på översikten.

generic_ev/nissan/tesla är redan giltiga kolumnprefix och får inte byta namn.
"""
import car_log
import live_flow


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
