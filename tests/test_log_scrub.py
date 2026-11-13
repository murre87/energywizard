"""#227: inget känsligt följer med supportutdraget till ett offentligt ärende."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "smartbox"))
import log_scrub as L  # noqa: E402

W = [("Emils Tesla", "<namn>"), ("Esther", "<namn>"), ("Hem", "<plats>"), ("abc123.ui.nabu.casa", "<adress>")]

KANSLIGT = {
    "🔔 Notis → mobile_app_emils_telefon: Tesla laddar": ["mobile_app_emils_telefon"],
    "Fönsterlampa - Esther har varit onåbar": ["Esther"],
    "HTTPSConnectionPool(host='192.168.1.146', port=443): Read timed out": ["192.168.1.146"],
    "GET https://abc123.ui.nabu.casa/api/states 401": ["nabu.casa", "abc123"],
    "token=abcDEF1234567890xyz password: hemligt123": ["abcDEF1234567890xyz", "hemligt123"],
    "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc": ["eyJhbG"],
    "Easee EHLS9NVL: Dynamisk gräns satt till 16 A": ["EHLS9NVL"],
    "climate.tesla_model_y_hvac_climate_system satt till off": ["tesla_model_y"],
    "plats 59.33459, 18.068532": ["59.33459", "18.068532"],
    "kontakta emil@example.com": ["emil@example.com"],
    "fe80::1ff:fe23:4567:890a och aa:bb:cc:dd:ee:ff": ["fe80", "aa:bb:cc"],
    "ghp_ABCdef1234567890ABCdef1234567890abcd läckte": ["ghp_"],
    "nyckel 3f9a1c2b4d5e6f708192a3b4c5d6e7f8091a2b3c": ["3f9a1c2b4d5e"],
    "Emils Tesla är hemma": ["Emils Tesla"],
}


def test_kansligt_forsvinner():
    for rad, bort in KANSLIGT.items():
        ut = L.scrub_line(rad, W)
        for b in bort:
            assert b.lower() not in ut.lower(), (rad, ut)


def test_felsokning_finns_kvar():
    for rad in ["⚠️ HA svarade inte (ReadTimeout) - försöker igen",
                "Prio 3 (EV Plan): Laddar enligt schema. Husets säkring tillåter 16A.",
                'File "/smartbox/decisions.py", line 122, in check_spa_schedule_plan',
                "pris 0.62675 kr/kWh kl 17:05:32", "Hemma: 21.5 °C"]:
        assert L.scrub_line(rad, W) == rad, rad
    assert L.scrub_line("sensor.easee_lite_strom = 0.01") == "sensor.<…> = 0.01"


def test_slutkontroll_tar_bort_raden():
    assert L.scrub_line("konstigt :// kvar", []) == L.REMOVED
    assert "://" not in L.scrub_line("ftp://user:pw@host/x")


def test_samlarens_kopia_ar_identisk():
    root = Path(__file__).resolve().parents[1]
    assert (root / "telemetry-collector/log_scrub.py").read_text() == (root / "smartbox/log_scrub.py").read_text()
