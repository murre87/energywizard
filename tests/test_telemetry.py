"""smartbox/telemetry.py: PÅ som standard - bevisar att det skickas utan att
något måste sättas i .env, att den inte går att stänga av (obligatorisk sedan 2026-11-06), att
rätt (och bara rätt) fält skickas, och att ett sändningsfel aldrig kraschar.
Mockar requests helt - rör aldrig nätverket."""
import importlib
from unittest.mock import MagicMock, patch

import pytest


def _reload(monkeypatch, opt_in=None, endpoint=None):
    """opt_in/endpoint=None -> miljövariabeln är helt osatt (testar det faktiska
    standardläget, inte en tom sträng som betyder något annat i koden)."""
    if opt_in is None:
        monkeypatch.delenv("TELEMETRY_OPT_IN", raising=False)
    else:
        monkeypatch.setenv("TELEMETRY_OPT_IN", opt_in)
    if endpoint is None:
        monkeypatch.delenv("TELEMETRY_ENDPOINT", raising=False)
    else:
        monkeypatch.setenv("TELEMETRY_ENDPOINT", endpoint)
    import telemetry
    return importlib.reload(telemetry)


def test_pa_som_standard_utan_nagon_env_variabel(monkeypatch):
    t = _reload(monkeypatch)
    assert t.OPT_IN is True
    assert t.ENDPOINT == "https://energywizzard.profitalgos.com/telemetry"
    with patch("telemetry.requests.post") as mock_post:
        t.send_driver_snapshot({"house_id": "mitt-hus"})
    mock_post.assert_called_once()


def test_obligatorisk_gar_inte_att_stanga_av(monkeypatch):
    """Emils beslut 2026-11-06: telemetrin är ett villkor för att använda EnergyWizard. Varken TELEMETRY_OPT_IN=false
    eller en egen TELEMETRY_ENDPOINT stänger av eller leder om den."""
    t = _reload(monkeypatch, opt_in="false", endpoint="https://annan.example.com")
    assert t.OPT_IN is True and t.ENDPOINT == "https://energywizzard.profitalgos.com/telemetry"
    assert not hasattr(t, "send_ping")
    with patch("telemetry.requests.post") as mock_post:
        t.send_driver_snapshot({"house_id": "mitt-hus"})
        t.report_error({"house_id": "mitt-hus"}, "main_loop", "ValueError")
    assert mock_post.call_count == 2
    assert all(c.args[0].startswith("https://energywizzard.profitalgos.com/telemetry") for c in mock_post.call_args_list)


def test_tom_endpoint_betyder_standardadressen(monkeypatch):
    """docker-compose skickar TELEMETRY_ENDPOINT= (tom) när .env saknar raden - då ska standarden gälla,
    annars tystnar alla compose-installationer (så var det fram till 2026-11-03). Av = TELEMETRY_OPT_IN=false."""
    t = _reload(monkeypatch, opt_in="", endpoint="")
    assert t.OPT_IN is True and t.ENDPOINT == "https://energywizzard.profitalgos.com/telemetry"
    with patch("telemetry.requests.post") as mock_post:
        t.send_driver_snapshot({"house_id": "mitt-hus"})
    mock_post.assert_called_once()


def _equipment(items):
    """Bara utrustningen - inställningarna (pris, land, läge) testas för sig."""
    return [x for x in items if not x.startswith(("price:", "country:", "mode:"))]


def test_marke_fran_enhetsregistret_men_aldrig_entiteten(monkeypatch):
    t = _reload(monkeypatch)
    cfg = {"battery": {"enabled": True, "driver": "generic", "entities": {"soc": "sensor.foxess_bat_soc"}},
           "heat_pump": {"enabled": True, "driver": "thermia_husdata"},
           "chargers": [{"driver": "generic", "entities": {"switch": "switch.zap_laddning"}}]}
    makers = {"sensor.foxess_bat_soc": "FoxESS", "switch.zap_laddning": "Zaptec <script>"}
    out = _equipment(t._driver_summary(cfg, makers.get))
    assert out == ["heatpump:thermia_husdata", "battery:generic@FoxESS", "charger:generic@Zaptec script"]
    nested = _equipment(t._driver_summary({"evs": [{"driver": "tesla", "charger": {"driver": "easee", "physical": "carport"}},
                                        {"driver": "nissan", "charger": {"driver": "easee", "physical": "lite"}}]}, None))
    assert nested == ["car:tesla", "charger:easee", "car:nissan", "charger:easee"]
    assert not any("sensor." in x or "switch." in x for x in out)
    assert _equipment(t._driver_summary(cfg, lambda e: (_ for _ in ()).throw(RuntimeError()))) == \
        ["heatpump:thermia_husdata", "battery:generic", "charger:generic"]


def test_daglig_signal_en_gang_per_dygn(monkeypatch):
    from datetime import datetime, timedelta, timezone
    t = _reload(monkeypatch)
    started = []
    monkeypatch.setattr(t, "send_driver_snapshot", lambda cfg: started.append(1))
    now = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
    import threading
    monkeypatch.setattr(threading, "Thread", lambda target, args, **k: type("T", (), {"start": lambda self: target(*args)})())
    t.maybe_send_daily({}, now)
    t.maybe_send_daily({}, now + timedelta(hours=23))
    t.maybe_send_daily({}, now + timedelta(hours=24))
    assert len(started) == 2


def test_driver_snapshot_skickar_bara_tillatna_falt(monkeypatch, tmp_path):
    import ew_settings
    t = _reload(monkeypatch, opt_in="true", endpoint="https://telemetri.example.com")
    monkeypatch.setattr(ew_settings, "PATH", str(tmp_path / "s.json"))
    ew_settings._cache.update(mtime=None, data={})
    cfg = {
        "house_id": "mitt-hus",
        "solar": {"enabled": True, "driver": "solaredge"},
        "heat_pump": {"enabled": True, "driver": "husdata"},
        "evs": [{"driver": "tesla"}],
    }
    with patch("telemetry.requests.post") as mock_post:
        t.send_driver_snapshot(cfg)
    assert mock_post.call_count == 1
    url, kwargs = mock_post.call_args[0][0], mock_post.call_args[1]
    assert url == "https://energywizzard.profitalgos.com/telemetry/ingest/drivers"
    payload = kwargs["json"]
    assert set(payload.keys()) == {"house", "version", "drivers", "ts"}
    assert payload["house"] != "mitt-hus"  # hashat, inte klartext
    assert len(payload["house"]) == 16
    assert set(_equipment(payload["drivers"])) == {"solar:solaredge", "heatpump:husdata", "car:tesla"}
    assert not any("mitt-hus" in x for x in payload["drivers"])


def test_samma_hus_ger_samma_hash_olika_hus_ger_olika_hash(monkeypatch):
    t = _reload(monkeypatch, opt_in="true", endpoint="https://telemetri.example.com")
    assert t._hashed_house_id("hus-a") == t._hashed_house_id("hus-a")
    assert t._hashed_house_id("hus-a") != t._hashed_house_id("hus-b")


def test_report_error_skickar_bara_tillatna_falt_inte_feltexten(monkeypatch):
    t = _reload(monkeypatch, opt_in="true", endpoint="https://telemetri.example.com")
    with patch("telemetry.requests.post") as mock_post, \
         patch("support_bundle.build", return_value="module=main_loop\nerror_type=ValueError"):
        t.report_error({"house_id": "mitt-hus"}, "main_loop", "ValueError")
    payload = mock_post.call_args[1]["json"]
    # #227: valfritt sanerat "support"-fält, aldrig rå feltext/entiteter
    assert set(payload.keys()) <= {"house", "version", "module", "error_type", "ts", "support"}
    assert {"house", "version", "module", "error_type", "ts"} <= set(payload.keys())
    assert payload["module"] == "main_loop"
    assert payload["error_type"] == "ValueError"
    assert "ValueError" not in (payload.get("support") or "") or "error_type=ValueError" in payload["support"]
    assert "sensor." not in (payload.get("support") or "")


def test_report_error_avdubblar_inom_timmen(monkeypatch):
    t = _reload(monkeypatch, opt_in="true", endpoint="https://telemetri.example.com")
    with patch("telemetry.requests.post") as mock_post:
        t.report_error({"house_id": "h"}, "main_loop", "ValueError")
        t.report_error({"house_id": "h"}, "main_loop", "ValueError")
    assert mock_post.call_count == 1


def test_natverksfel_kraschar_inte(monkeypatch):
    t = _reload(monkeypatch, opt_in="true", endpoint="https://telemetri.example.com")
    with patch("telemetry.requests.post", side_effect=RuntimeError("timeout")):
        t.send_driver_snapshot({"house_id": "h"})
        t.report_error({"house_id": "h"}, "main_loop", "ValueError")


def test_slumpat_installations_id_inte_house_id(monkeypatch, tmp_path):
    """2026-11-04: startguiden skriver house_id "mitt-hus" åt alla - alla sådana hus blev ett i statistiken."""
    import ew_settings
    t = _reload(monkeypatch)
    monkeypatch.setattr(ew_settings, "PATH", str(tmp_path / "a.json"))
    ew_settings._cache.update(mtime=None, data={})
    assert t.house_hash({"house_id": "mitt-hus"}, create=False) == t._hashed_house_id("mitt-hus")   # webben skapar inget
    a = t.house_hash({"house_id": "mitt-hus"})
    assert a == t.house_hash({"house_id": "mitt-hus"}) == t.house_hash({}, create=False)          # stabilt, delas med webben
    monkeypatch.setattr(ew_settings, "PATH", str(tmp_path / "b.json"))
    ew_settings._cache.update(mtime=None, data={})
    b = t.house_hash({"house_id": "mitt-hus"})
    assert a != b and a != t._hashed_house_id("mitt-hus") and len(a) == 16


def test_matare_priskalla_och_lage_skickas(monkeypatch, tmp_path):
    import ew_settings
    t = _reload(monkeypatch)
    monkeypatch.setattr(ew_settings, "PATH", str(tmp_path / "s.json"))
    ew_settings._cache.update(mtime=None, data={})
    ew_settings.update(shadow_mode=True)
    cfg = {"power_meter": {"entities": {"power_w": "sensor.tibber_power"}},
           "battery": {"enabled": True, "driver": "generic", "control": "styr", "preset": "solis_modbus",
                       "modes": {"auto": "x"}, "entities": {"soc": "sensor.bat"}}}
    out = t._driver_summary(cfg, {"sensor.tibber_power": "Tibber", "sensor.bat": "Solis"}.get)
    assert "meter:ha@Tibber" in out and "battery:generic@Solis" in out
    assert "mode:battery_styr" in out and "mode:preset_solis_modbus" in out and "mode:shadow" in out
    assert any(x.startswith("price:") for x in out) and any(x.startswith("country:") for x in out)
    assert not any("sensor." in x for x in out)


def test_storlekar_avrundas_och_tidstariff(monkeypatch, tmp_path):
    import ew_settings
    t = _reload(monkeypatch)
    monkeypatch.setattr(ew_settings, "PATH", str(tmp_path / "s.json"))
    ew_settings._cache.update(mtime=None, data={})
    ew_settings.update(price_tou_extra=0.4)
    cfg = {"battery": {"enabled": True, "capacity_kwh": 12.8}, "evs": [{"driver": "tesla", "battery_kwh": 75}],
           "fuse": {"main_fuse_a": 25}}
    out = t._driver_summary(cfg, None)
    assert "size:battery_10-15kWh" in out and "size:car_70-90kWh" in out and "size:fuse_25A" in out
    assert "mode:tou_tariff" in out
    assert not any("12.8" in x or "75" in x for x in out)                      # aldrig exakta värden


def test_felkroken_skickar_plats_och_typ_aldrig_texten(monkeypatch):
    import builtins
    t = _reload(monkeypatch, opt_in="true", endpoint="https://telemetri.example.com")
    sent = []
    monkeypatch.setattr(t, "report_error", lambda cfg, mod, kind: sent.append((mod, kind)))
    orig = builtins.print
    try:
        t.install_error_hook({})
        import threading

        def ladda():
            try:
                raise ConnectionError("http://192.168.1.5 sensor.hemlig")
            except ConnectionError as e:
                print(f"❌ Kunde inte nå laddboxen: {e}")
        ladda()
        print("✅ allt väl")
        for th in threading.enumerate():
            if th is not threading.current_thread() and th.daemon:
                th.join(timeout=2)
    finally:
        builtins.print = orig
    assert sent == [("test_telemetry.ladda", "ConnectionError")]
    assert not any("192.168" in m or "hemlig" in m for m, _ in sent)


def test_modell_innegivare_och_avrundade_temperaturer(monkeypatch):
    t = _reload(monkeypatch)
    makers = {"sensor.vp": "NIBE Energy Systems|S1255", "sensor.a": "Aqara|Temp sensor", "sensor.b": "Aqara|T1"}
    assert t._brand({"entities": {"x": "sensor.vp"}}, makers.get) == "@NIBE Energy Systems#S1255"
    assert t._brand({"entities": {"x": "sensor.z"}}, {"sensor.z": "Gecko|"}.get) == "@Gecko"
    t._state.clear()
    t.note_state(indoor=21.64, outdoor=-3.4, indoor_source="ha_sensors", indoor_sensors=2, indoor_entities=["sensor.a", "sensor.b"])
    out = t._state_summary(makers.get)
    assert out[0].startswith("indoor:ha_sensors_2") and "temp:inne_22C" in out and "temp:ute_-3C" in out
    assert not any("21.6" in x or "sensor." in x for x in out)
    t.note_state(indoor=20.0, indoor_source="heatpump")
    assert t._state_summary(None)[0] == "indoor:heatpump"


def test_ftw_drivrutinens_namn_rapporteras():
    import telemetry
    out = telemetry._driver_summary({"battery": {"enabled": True, "driver": "ftw", "ftw": {"driver": "pixii", "host": "10.0.0.5"}}})
    assert "battery:ftw-pixii" in out and not any("10.0.0.5" in x for x in out)


def test_kvarstaende_fel_rapporteras_igen_efter_en_timme(monkeypatch):
    """Installationer visar bara fel som setts senaste 75 min - ett kvarstående fel måste rapporteras varje timme."""
    from datetime import datetime, timedelta, timezone
    t = _reload(monkeypatch, opt_in="true", endpoint="https://telemetri.example.com")
    with patch("telemetry.requests.post") as mock_post:
        t.report_error({"house_id": "h"}, "main_loop", "ValueError")
        t._ERROR_SEEN["main_loop:ValueError"] = datetime.now(timezone.utc) - timedelta(minutes=61)
        t.report_error({"house_id": "h"}, "main_loop", "ValueError")
    assert mock_post.call_count == 2


def test_insamlaren_skiljer_livstecken_fran_hus_utan_enheter(monkeypatch, tmp_path):
    import importlib.util, pathlib
    monkeypatch.setenv("TELEMETRY_DB_PATH", str(tmp_path / "t.sqlite3"))
    monkeypatch.delenv("STATS_TOKEN", raising=False)
    path = pathlib.Path(__file__).resolve().parent.parent / "telemetry-collector" / "app.py"
    spec = importlib.util.spec_from_file_location("collector_app_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    import asyncio

    class Req:                       # utan TestClient: CI saknar httpx-paketet som den kräver
        def __init__(self, body=None):
            self.headers, self._body = {}, body

        async def json(self):
            return self._body

    for body in ({"house": "a" * 16, "version": "1.2.39", "drivers": [], "ping": True},
                 {"house": "b" * 16, "version": "1.2.39", "drivers": []},
                 {"house": "c" * 16, "version": "1.2.39", "drivers": ["meter:ha@Tibber"]}):
        asyncio.run(mod.ingest_drivers(Req(body)))
    s = asyncio.run(mod.stats(Req()))
    assert s["active"] == 3 and s["ping_only"] == 1 and s["without_devices"] == 1
    assert [h["ping_only"] for h in s["houses"]] == [True, False, False]
    assert s["houses"][0]["devices"] == {} and s["equipment"] == {"meter": {"ha@Tibber": 1}}


def _collector(monkeypatch, tmp_path):
    import importlib.util, pathlib
    monkeypatch.setenv("TELEMETRY_DB_PATH", str(tmp_path / "t.sqlite3"))
    monkeypatch.delenv("STATS_TOKEN", raising=False)
    path = pathlib.Path(__file__).resolve().parent.parent / "telemetry-collector" / "app.py"
    spec = importlib.util.spec_from_file_location("collector_app_test2", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ominstallerat_hus_med_samma_utrustning_raknas_en_gang(monkeypatch, tmp_path):
    """2026-11-06: samma hus (NIBE + Solis + Tesla + Garo + Tibber) dök upp som Hus 5 och Hus 6 med nytt ID.
    Ett äldre hus som tystnat före ett nytt med exakt samma utrustning slås ihop; överlappande hus gör det inte."""
    mod = _collector(monkeypatch, tmp_path)
    eq = ["heatpump:nibe_local", "solar:generic_number", "battery:generic@Solis", "car:tesla@Tesla#Model3",
          "charger:generic@Garo#X", "meter:ha@Tibber#Pulse", "size:fuse_16A", "country:SE", "mode:battery_samarbete"]
    eq2 = [d.replace("generic_number", "generic_number@Solis#S6-EH3P") for d in eq if not d.startswith("mode")] + ["mode:battery_styr"]
    latest = {"a" * 16: ("v1", eq, False), "b" * 16: ("v2", eq2, False), "c" * 16: ("v2", eq, False)}
    first = {"a" * 16: "2026-11-05T07:58", "b" * 16: "2026-11-06T20:36", "c" * 16: "2026-11-05T09:00"}
    last = {"a" * 16: "2026-11-06T10:15", "b" * 16: "2026-11-06T20:40", "c" * 16: "2026-11-06T20:40"}
    merged = mod._merge_reinstalls(latest, first, last)
    assert merged == {"b" * 16: ["a" * 16]} and set(latest) == {"b" * 16, "c" * 16}
    small = {"d" * 16: ("v", ["meter:ha", "country:SE"], False), "e" * 16: ("v", ["meter:ha", "country:SE"], False)}
    assert mod._merge_reinstalls(small, {"d" * 16: "1", "e" * 16: "3"}, {"d" * 16: "2", "e" * 16: "4"}) == {}


def test_installations_id_overlever_att_installningsfilen_skrivs_over(monkeypatch, tmp_path):
    import ew_settings
    monkeypatch.setattr(ew_settings, "PATH", str(tmp_path / "energywizard.json"))
    ew_settings._cache.update(mtime=None, data={})
    t = _reload(monkeypatch)
    tid = t.install_id()
    assert tid and (tmp_path / ".energywizard.json.telemetry_id").read_text() == tid
    (tmp_path / "energywizard.json").write_text('{"language": "sv"}')     # annan process skrev över utan ID:t
    ew_settings._cache.update(mtime=None, data={})
    assert t.install_id() == tid and ew_settings.get("telemetry_id") == tid and ew_settings.get("language") == "sv"


def test_installningar_last_las_fran_disk_inte_gammal_cache(monkeypatch, tmp_path):
    """Två processer: den ena har en gammal bild i minnet, den andra har sparat ett värde. update() ska inte
    skriva tillbaka den gamla bilden (så försvann telemetry_id före 1.2.40)."""
    import ew_settings, json
    path = tmp_path / "energywizard.json"
    monkeypatch.setattr(ew_settings, "PATH", str(path))
    ew_settings._cache.update(mtime=None, data={})
    ew_settings.update(language="sv")
    stale = dict(ew_settings._cache)
    path.write_text(json.dumps({"language": "sv", "telemetry_id": "x" * 32}))
    import os
    os.utime(path, ns=(stale["mtime"], stale["mtime"]))                  # samma mtime: cachen tror att inget ändrats
    ew_settings.update(theme="dark")
    assert json.loads(path.read_text()) == {"language": "sv", "telemetry_id": "x" * 32, "theme": "dark"}


def test_batteriets_tomma_falt_blir_inte_noll(monkeypatch):
    """Som FTW 0.158.3: ett tömt fält som sparats som 0 eller "" får inte bli laddtak eller effekt 0."""
    import house_config
    s = house_config.battery_settings({"battery": {"enabled": True, "max_soc": 0, "max_power_w": "", "capacity_kwh": "abc",
                                                   "efficiency": 0, "reserve_soc": 0, "cycle_cost": 0,
                                                   "max_charge_w": 0, "max_discharge_w": ""}})
    assert s["max_soc"] == 100.0 and s["max_power_w"] == 5000.0 and s["capacity_kwh"] is None and s["efficiency"] == 0.9
    assert s["reserve_soc"] == 0 and s["cycle_cost"] == 0                       # 0 är ett giltigt val här
    assert s["max_charge_w"] is None and s["max_discharge_w"] is None           # tomt tak får inte bli 0 W
    capped = house_config.battery_settings({"battery": {"enabled": True, "max_charge_w": 3000, "max_discharge_w": 4000}})
    assert capped["max_charge_w"] == 3000.0 and capped["max_discharge_w"] == 4000.0


def test_kodplats_i_felrapporten_utan_feltext():
    """2026-11-08: Hus 33 rapporterade bara "main_loop: TypeError". Kodplatsen (fil:rad funktion) följer nu med."""
    import telemetry
    def inner():
        return None + 1
    try:
        inner()
    except TypeError as e:
        loc = telemetry.code_location(e.__traceback__)
    assert loc.startswith("test_telemetry.py:") and loc.endswith(" inner") and "None" not in loc
