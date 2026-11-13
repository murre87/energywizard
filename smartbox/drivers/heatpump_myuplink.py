"""MyUplinkHeatPumpDriver: NIBE:s delade MOLNPLATTFORM myUplink - enligt FTW:s
enhetskatalog (https://srcfl.github.io/device-drivers/drivers.json, drivrutin-ID
"myuplink") även använd av Bosch, Atlantic och Daikin. EN drivrutin här täcker
alltså flera värmepumpsmärken - men till priset av en genuint annan, molnbaserad
autentiseringsmodell än resten av EnergyWizard (som annars medvetet prioriterar
lokalt-first, se t.ex. heatpump_nibe_local.py).

KÄLLOR, LÄS INNAN DU LITAR PÅ DEN HÄR:
- Officiell OpenAPI-spec: https://api.myuplink.com/swagger/docs/public-v2/swagger.json
  (bekräftar bas-URL https://api.myuplink.com, GET /v2/systems/me, GET/PATCH
  /v2/devices/{deviceId}/points, token-URL /oauth/token, scopes READSYSTEM/
  WRITESYSTEM, och ParameterData-fälten parameterId/parameterName/value/writable/
  parameterUnit/minValue/maxValue/enumValues - allt bekräftat genom att läsa spec-
  filen direkt).
- VIKTIG DISKREPANS, bekräftad genom en riktig, fungerande klient
  (https://github.com/jaroschek/home-assistant-myuplink): specens säkerhetsschema
  heter "Client Credentials" och anger flow=clientCredentials, men i praktiken
  krävs en INTERAKTIV webbläsarbaserad inloggning + samtycke (OAuth authorization
  code-flödet, /oauth/authorize + /oauth/login + /oauth/consent syns i specens
  egen endpointlista) - precis som en vanlig "logga in med ditt konto"-OAuth-app.
  Alltså: ett engångssteg i en webbläsare krävs för att få en refresh_token, sen
  sköter drivrutinen själv framtida token-förnyelse headless (grant_type=
  refresh_token mot /oauth/token) - se scripts/myuplink_authorize.py.
- PATCH-kroppens form (`{"<parameterId>": "<värde som sträng>"}`, svar ekar
  `{"<parameterId>": "modified"}`) är INTE citerad direkt ur spec-filen (dess
  request/response-scheman för just PATCH syntes aldrig i den delen av filen som
  lästes) - den är bekräftad genom två oberoende, riktiga community-rapporterade
  anrop/svar (en Home Assistant-integrations issue och en openHAB-issue). Rimligt
  säkert, men ETT STEG SVAGARE käll-trovärdighet än allt annat i den här filen.

ALDRIG KÖRD MOT EN RIKTIG myUplink-SERVER - inget hus i det här projektet har ett
konto där. Samma försiktighetsprincip som NibeLocalHeatPumpDriver: read_sensors()
returnerar BARA värden för de punkter husägaren själv konfigurerat i
house_config.yaml (heat_pump.entities, ett parameterId-namn per semantiskt fält -
användaren hittar dem själv via GET /v2/devices/{deviceId}/points, exakt som
myUplink-integrationens egen felsökningsguide beskriver) - vi gissar INTE på vilket
parameterId som betyder vad för ett visst märke/modell. set_*-metoder skriver bara
till punkter som dels är konfigurerade, dels senast lästes med writable=true."""
import hashlib
import json
import os
import time

import requests

from drivers.heatpump import HeatPumpDriver

_TOKEN_URL = "https://api.myuplink.com/oauth/token"
_API_BASE = "https://api.myuplink.com"

_CLIENT_ID = os.environ.get("MYUPLINK_CLIENT_ID", "")
_CLIENT_SECRET = os.environ.get("MYUPLINK_CLIENT_SECRET", "")
_REFRESH_TOKEN = os.environ.get("MYUPLINK_REFRESH_TOKEN", "")
_DEVICE_ID = os.environ.get("MYUPLINK_DEVICE_ID", "")
# Supervisor-proxyn svarar 502/503/504 medan API:t startar om. Samma gräns som mot Home Assistant.
_GATEWAY_STATUS = (502, 503, 504)
# myUplink roterar refresh_token vid varje förnyelse: den nya sparas här (samma datamapp som
# energywizard.json) så att den överlever en omstart. Tillhör den en annan MYUPLINK_REFRESH_TOKEN
# än den som står i miljön nu (användaren har loggat in på nytt) används miljöns.
_TOKEN_STORE = os.environ.get("EW_MYUPLINK_TOKEN_PATH") or os.path.join(
    os.path.dirname(os.environ.get("EW_SETTINGS_PATH", "/data/energywizard.json")), "myuplink-token.json")
_AUTH_RETRY_S = 1800      # nekad inloggning: nytt försök var 30:e minut, inte varje kvart
_AUTH_DENIED = (400, 401)  # invalid_grant / ogiltig klient: användaren måste logga in igen


def _seed(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()[:16]


def _load_refresh_token() -> str:
    try:
        with open(_TOKEN_STORE, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("seed") == _seed(_REFRESH_TOKEN) and d.get("refresh_token"):
            return d["refresh_token"]
    except (OSError, ValueError):
        pass
    return _REFRESH_TOKEN


def _save_refresh_token(token: str) -> bool:
    try:
        tmp = _TOKEN_STORE + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"seed": _seed(_REFRESH_TOKEN), "refresh_token": token, "saved": int(time.time())}, f)
        os.replace(tmp, _TOKEN_STORE)
        return True
    except OSError as e:
        print(f"⚠️ MyUplinkHeatPumpDriver: kunde inte spara den nya inloggningen ({e.__class__.__name__}). "
              "Den gäller tills motorn startas om.")
        return False


def _myuplink_mark(exc) -> str:
    """Timeout, avbrott och gateway-omstart är drift (⚠️). Fel token och oväntade undantag är kvar som ❌,
    så telemetrin inte gör programfel av att api.myuplink.com inte svarar."""
    if isinstance(exc, requests.HTTPError):
        status = getattr(getattr(exc, "response", None), "status_code", None)
        return "⚠️" if status in _GATEWAY_STATUS else "❌"
    if isinstance(exc, (requests.RequestException, TimeoutError, OSError)):
        return "⚠️"
    return "❌"


class MyUplinkHeatPumpDriver(HeatPumpDriver):
    """entities: dict av semantiskt namn -> myUplink parameterId (sträng), t.ex.
    {"indoor_temp": "40033", "room_target": "47398"}. Bara nycklar som motsvarar
    HeatPumpDriver-kontraktets normaliserade fält används av read_sensors()."""

    _SEMANTIC_FIELDS = (
        "indoor_temp", "outdoor_temp", "forward_temp", "return_temp", "water_temp",
        "degree_minutes", "compressor_running", "compressor_power_kw", "operating_mode",
    )
    _WRITE_FIELDS = {
        "room_target": "set_room_temp", "water_stop": "set_water_stop_temp",
        "water_start": "set_water_start_temp", "heating_start": "set_heating_start_temp",
    }

    def __init__(self, entities: dict | None = None):
        self._entities = entities or {}
        self._access_token: str | None = None
        self._token_expiry = 0.0
        self._writable: dict[str, bool] = {}
        self._warned: set[str] = set()
        self._refresh_token: str | None = None   # läses första gången den behövs
        self._auth_denied_at = 0.0

    def _warn_unsupported(self, method: str, reason: str):
        if method not in self._warned:
            print(f"⚠️ MyUplinkHeatPumpDriver: {method} stöds inte - {reason}. Ignoreras.")
            self._warned.add(method)

    def _refresh_access_token(self) -> str | None:
        """grant_type=refresh_token - headless, kräver ingen webbläsare efter den
        allra första engångsauktoriseringen (se scripts/myuplink_authorize.py).
        myUplink roterar refresh_token: den nya används direkt och sparas (_TOKEN_STORE).
        Förut användes alltid den gamla ur miljön, så inloggningen slutade fungera med
        400 Bad Request efter första rotationen. Nekar myUplink ändå (400/401) är det ett
        inloggningsproblem hos användaren, inte ett programfel: en tydlig varning, en
        avisering och nytt försök var 30:e minut."""
        if not (_CLIENT_ID and _CLIENT_SECRET and _REFRESH_TOKEN):
            return None
        if self._auth_denied_at and time.time() - self._auth_denied_at < _AUTH_RETRY_S:
            return None
        if self._refresh_token is None:
            self._refresh_token = _load_refresh_token()
        try:
            r = requests.post(_TOKEN_URL, data={
                "grant_type": "refresh_token", "refresh_token": self._refresh_token,
                "client_id": _CLIENT_ID, "client_secret": _CLIENT_SECRET,
            }, timeout=10)
            if getattr(r, "status_code", 200) in _AUTH_DENIED:
                self._auth_denied(r.status_code)
                return None
            r.raise_for_status()
            d = r.json()
            self._access_token = d["access_token"]
            self._token_expiry = time.time() + float(d.get("expires_in", 3600)) - 60
            new_refresh = d.get("refresh_token")
            if new_refresh and new_refresh != self._refresh_token:
                self._refresh_token = new_refresh
                _save_refresh_token(new_refresh)
            if self._auth_denied_at:
                print("✅ MyUplinkHeatPumpDriver: inloggningen fungerar igen.")
                self._auth_denied_at = 0.0
            return self._access_token
        except Exception as e:
            print(f"{_myuplink_mark(e)} MyUplinkHeatPumpDriver: kunde inte förnya access-token: {e}")
            return None

    def _auth_denied(self, status):
        first = not self._auth_denied_at
        self._auth_denied_at = time.time()
        if not first:
            return
        print(f"⚠️ MyUplinkHeatPumpDriver: myUplink nekar inloggningen, HTTP {status}. Logga in på nytt med "
              "scripts/myuplink_authorize.py och byt MYUPLINK_REFRESH_TOKEN. Värmepumpen styrs inte så länge.")
        try:
            import notifier
            notifier.send_emil("⚠️ myUplink: logga in igen",
                               "myUplink nekar EnergyWizards inloggning, så värmepumpen styrs inte just nu. "
                               "Logga in på nytt och byt MYUPLINK_REFRESH_TOKEN.")
        except Exception:
            pass

    def _headers(self) -> dict | None:
        if not self._access_token or time.time() >= self._token_expiry:
            if not self._refresh_access_token():
                return None
        return {"Authorization": f"Bearer {self._access_token}", "Accept": "application/json"}

    def _points(self) -> list[dict]:
        h = self._headers()
        if not h or not _DEVICE_ID:
            return []
        try:
            r = requests.get(f"{_API_BASE}/v2/devices/{_DEVICE_ID}/points", headers=h, timeout=10)
            r.raise_for_status()
            points = r.json()
            return points if isinstance(points, list) else []
        except Exception as e:
            print(f"{_myuplink_mark(e)} MyUplinkHeatPumpDriver: kunde inte läsa points: {e}")
            return []

    def read_sensors(self) -> dict:
        out = {k: None for k in self._SEMANTIC_FIELDS}
        if not self._entities:
            return out
        points = self._points()
        by_id = {str(p.get("parameterId")): p for p in points if p.get("parameterId") is not None}
        for field in self._SEMANTIC_FIELDS:
            pid = self._entities.get(field)
            if pid and pid in by_id:
                out[field] = by_id[pid].get("value")
        # #184: kompressorns status kan vara NIBE:s kod (43427: 20 stoppad, 40 startar, 60 går, 100 stoppar) eller text
        # ("Kör", "Running"); samma tolkning som HA-vägen. Förut räknades varje kod över 0 (även "stoppad") som att den gick.
        pid = self._entities.get("compressor_running")
        if pid and out.get("compressor_running") is not None:
            from drivers.heatpump_ha_entities import compressor_running
            raw = out["compressor_running"]
            try:
                num = float(raw)
            except (TypeError, ValueError):
                num = None
            name = f"{pid} {by_id.get(str(pid), {}).get('parameterName') or ''}"
            run = compressor_running(name if num is None or "43427" in name or "status" in name.lower() else f"freq {pid}",
                                     num, lambda: raw)
            out["compressor_running"] = None if run is None else int(run)
        for key in self._WRITE_FIELDS:
            pid = self._entities.get(key)
            if pid and pid in by_id:
                self._writable[key] = bool(by_id[pid].get("writable"))
        return out

    def _write_point(self, write_key: str, value) -> bool:
        import shadow
        if shadow.active():
            shadow.record("myUplink", f"{write_key}={value}")
            return True
        return self._write_point_real(write_key, value)

    def _write_point_real(self, write_key: str, value) -> bool:
        pid = self._entities.get(write_key)
        if not pid:
            self._warn_unsupported(self._WRITE_FIELDS[write_key],
                                    f"ingen myUplink-punkt konfigurerad för '{write_key}' i house_config.yaml")
            return False
        if not self._writable.get(write_key, False):
            self._warn_unsupported(self._WRITE_FIELDS[write_key],
                                    f"punkt {pid} var inte markerad skrivbar (writable=false) vid senaste läsning")
            return False
        h = self._headers()
        if not h:
            return False
        try:
            # Kroppens form {"<parameterId>": "<sträng>"} - bekräftad via community-
            # rapporterade riktiga anrop, inte direkt citerad ur spec-filen. Se
            # moduldocstringen.
            r = requests.patch(f"{_API_BASE}/v2/devices/{_DEVICE_ID}/points", headers=h,
                                json={pid: str(value)}, timeout=10)
            r.raise_for_status()
            return True
        except Exception as e:
            print(f"{_myuplink_mark(e)} MyUplinkHeatPumpDriver: kunde inte skriva {write_key} (punkt {pid}): {e}")
            return False

    def set_room_temp(self, target_c: float) -> bool:
        return self._write_point("room_target", target_c)

    def set_water_stop_temp(self, target_c: float) -> bool:
        return self._write_point("water_stop", target_c)

    def set_water_start_temp(self, target_c: float) -> bool:
        return self._write_point("water_start", target_c)

    def set_heating_start_temp(self, target_c: float) -> bool:
        return self._write_point("heating_start", target_c)

    def set_operating_mode(self, mode) -> bool:
        self._warn_unsupported("set_operating_mode",
                                "inget bekräftat, märkesoberoende driftlägesparameter - "
                                "varje märke (NIBE/Bosch/Atlantic/Daikin) kan ha olika "
                                "parameterId/värdemängd för det här")
        return False
