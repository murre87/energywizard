"""NibeLocalHeatPumpDriver: NIBE S-seriens (S735/S1255/S1155/S320 m.fl.) INBYGGDA lokala
REST-API, aktiveras i installatörsmeny 7.5 - HTTPS-port 8443, Basic-auth med det
användarnamn/lösenord pumpen själv genererar, självsignerat certifikat (pinnas med
SHA-256-fingeravtryck istället för att TLS-verifiering stängs av).

VIKTIGT, LÄS INNAN DU LITAR PÅ DEN HÄR: byggd uteslutande mot dokumentationen i
https://github.com/srcfl/ftw/blob/master/docs/nibe-local.md och den faktiska
drivrutinskällan (srcfl/device-drivers, drivers/lua/nibe_local.lua) - ALDRIG körd mot en
riktig pump (inget hus i det här projektet har en NIBE S-serie-pump). De anrop/fält som
används här (GET /api/v1/devices, GET .../points, PATCH .../points, fälten title/
metadata.divisor/metadata.modbusRegisterID/value.integerValue) är bekräftade i KÄLLAN -
men vi har INGEN bekräftad karta mellan EnergyWizards normaliserade fält
(indoor_temp/outdoor_temp/water_temp/degree_minutes) och NIBE:s faktiska register-ID:n
för just de värdena. De enda registren som faktiskt är dokumenterade i vår källa är
2107 (aktivera solöverskott-input) och 2109 (tillgänglig soleffekt) - en SOLÖVERSKOTT-
funktion, inte rumstemperatur/driftläge. Därför: read_sensors() returnerar bara det vi
kan hämta generiskt (pumpens modell/firmware), och alla set_*-metoder returnerar
MEDVETET False tills någon med en riktig pump hjälper till att identifiera de rätta
registren för resten - exakt samma försiktighetsprincip som GenericClimateHeatPumpDriver
redan använder för Husdatas registernivå-funktioner."""
import base64
import os

import requests

from drivers.heatpump import HeatPumpDriver

_HOST = os.environ.get("NIBE_LOCAL_HOST", "")
_PORT = os.environ.get("NIBE_LOCAL_PORT", "8443")
_USERNAME = os.environ.get("NIBE_LOCAL_USERNAME", "")
_PASSWORD = os.environ.get("NIBE_LOCAL_PASSWORD", "")
# SHA-256-fingeravtryck av pumpens självsignerade certifikat (openssl s_client,
# samma metod som FTW:s egen dokumentation beskriver) - vi stänger ALDRIG av
# TLS-verifiering, vi pinnar den specifika leaf-certifikatet istället.
_TLS_PIN_SHA256 = os.environ.get("NIBE_LOCAL_TLS_PIN_SHA256", "")

# Dokumenterade register (FTW:s nibe_local.lua) - solöverskott-funktionen, inte
# rumstemperatur/driftläge. Enda registren vi faktiskt vet numret på.
_REG_SOLAR_PV_ENABLE = 2107
_REG_SOLAR_PV_AVAILABLE = 2109


class _PinnedCertAdapter(requests.adapters.HTTPAdapter):
    """Verifierar att serverns certifikat matchar _TLS_PIN_SHA256 istället för att
    lita på ett CA-kedjeförtroende (pumpen har ett självsignerat certifikat) - och
    istället för att tyst stänga av verifieringen helt (`verify=False`), vilket
    öppnar för en man-in-the-middle mot vem som helst på samma nät."""
    def __init__(self, pin_sha256: str, *args, **kwargs):
        self._pin = pin_sha256.lower().replace(":", "")
        super().__init__(*args, **kwargs)

    def cert_verify(self, conn, url, verify, cert):
        super().cert_verify(conn, url, verify=False, cert=cert)
        conn.assert_fingerprint = self._pin


def _session() -> requests.Session:
    s = requests.Session()
    if _TLS_PIN_SHA256:
        s.mount("https://", _PinnedCertAdapter(_TLS_PIN_SHA256))
    auth = base64.b64encode(f"{_USERNAME}:{_PASSWORD}".encode()).decode()
    s.headers.update({"Authorization": f"Basic {auth}", "Accept": "application/json"})
    return s


def _base_url() -> str:
    return f"https://{_HOST}:{_PORT}"


class NibeLocalHeatPumpDriver(HeatPumpDriver):
    """Pratar med NIBE S-seriens lokala REST-API. Se modulens docstring - bara
    anslutnings-/läslagret är verifierat mot dokumentationen, styrning är
    medvetet inte implementerad (overifierade register)."""

    def __init__(self):
        self._serial: str | None = None
        self._warned: set[str] = set()

    def _warn_unsupported(self, method: str):
        if method not in self._warned:
            print(f"⚠️ NibeLocalHeatPumpDriver: {method} stöds inte än - registret för "
                  f"det är inte bekräftat mot NIBE:s dokumentation eller en riktig pump, "
                  f"och vi gissar inte på registernummer. Ignoreras.")
            self._warned.add(method)

    def _detect_serial(self) -> str | None:
        if self._serial:
            return self._serial
        if not (_HOST and _USERNAME and _PASSWORD):
            return None
        try:
            r = _session().get(f"{_base_url()}/api/v1/devices", timeout=5)
            r.raise_for_status()
            devices = r.json().get("data", {}).get("devices", [])
            if not devices:
                return None
            self._serial = devices[0]["product"]["serialNumber"]
            return self._serial
        except Exception as e:
            print(f"❌ NibeLocalHeatPumpDriver: kunde inte läsa /api/v1/devices: {e}")
            return None

    def read_sensors(self) -> dict:
        """Returnerar bara det vi faktiskt kan utvinna generiskt ur pumpens
        enhetsinfo - INTE rumstemperatur/driftläge m.m. (overifierade register,
        se modulens docstring). Alla overifierade fält är medvetet None, inte
        gissade värden."""
        serial = self._detect_serial()
        if not serial:
            return {}
        try:
            r = _session().get(f"{_base_url()}/api/v1/devices/{serial}/points", timeout=10)
            r.raise_for_status()
            points = r.json()
        except Exception as e:
            print(f"❌ NibeLocalHeatPumpDriver: kunde inte läsa points: {e}")
            return {}
        return {
            "indoor_temp": None,
            "outdoor_temp": None,
            "forward_temp": None,
            "return_temp": None,
            "water_temp": None,
            "degree_minutes": None,
            "compressor_running": None,
            "compressor_power_kw": None,
            "operating_mode": None,
            # Informativt, inte en del av HeatPumpDriver-kontraktet - antal
            # datapunkter pumpen faktiskt exponerade, användbart för felsökning.
            "_raw_point_count": len(points) if isinstance(points, dict) else 0,
        }

    def set_room_temp(self, target_c: float) -> bool:
        self._warn_unsupported("set_room_temp")
        return False

    def set_water_stop_temp(self, target_c: float) -> bool:
        self._warn_unsupported("set_water_stop_temp")
        return False

    def set_water_start_temp(self, target_c: float) -> bool:
        self._warn_unsupported("set_water_start_temp")
        return False

    def set_heating_start_temp(self, target_c: float) -> bool:
        self._warn_unsupported("set_heating_start_temp")
        return False

    def set_operating_mode(self, mode) -> bool:
        self._warn_unsupported("set_operating_mode")
        return False
