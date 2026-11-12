import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- Mottagare ---
# Telefonen som får aviseringarna: NOTIFY_TARGET (miljövariabel) eller "notify_target" i /data/energywizard.json,
# t.ex. "mobile_app_pixel_8". Saknas båda väljs den första mobile_app_*-tjänsten i Home Assistant (issue #104:
# ett hårdkodat namn gav 400-fel varje gång hos alla andra installationer).
_auto_target = {"t": 0.0, "name": None}


def target():
    import os, time
    name = os.environ.get("NOTIFY_TARGET", "").strip()
    if not name:
        try:
            import ew_settings
            name = (ew_settings.get("notify_target") or "").strip()
        except Exception:
            name = ""
    if name:
        return name if name.startswith("script.") else name.removeprefix("notify.")
    if time.time() - _auto_target["t"] > 3600:
        _auto_target["t"] = time.time()
        _auto_target["name"] = _find_mobile_app()
    return _auto_target["name"]


def _find_mobile_app():
    _init()
    try:
        r = requests.get(f"{_ha_base}/services", headers=_ha_headers, timeout=5, verify=False)
        r.raise_for_status()
        for dom in r.json():
            if dom.get("domain") == "notify":
                names = sorted(n for n in (dom.get("services") or {}) if n.startswith("mobile_app_"))
                if names:
                    print(f"🔔 Aviseringar går till notify.{names[0]} (ändra med NOTIFY_TARGET)")
                    return names[0]
    except Exception as e:
        print(f"⚠️ Kunde inte hitta någon telefon för aviseringar: {e}")
    return None

# Mappning för värmepumpens driftläge (register 2201)
PUMP_MODE_MAP = {
    0: "All off",
    1: "Auto (Värme + Varmvatten)",
    2: "Normal (Endast värme)",
    3: "Endast tillsatsvärme",
    4: "Endast varmvatten",
}

# Importeras sent för att undvika cirkulär import
_ha_base    = None
_ha_headers = None

def _init():
    global _ha_base, _ha_headers
    if _ha_base is None:
        import homeassistant as ha
        _ha_base    = ha._BASE
        _ha_headers = ha._HEADERS


def _localized_payload(title, message, data):
    """Translate presentation without changing notification routing or opaque action data (#202)."""
    original = {"title": title, "message": message}
    if data:
        original["data"] = data
    try:
        from copy import deepcopy
        import i18n_py
        lang = i18n_py.language()
        def text(value):
            return "\n".join(i18n_py.tr(line, lang) for line in value.split("\n"))
        payload = {"title": text(title), "message": text(message)}
        if data:
            payload["data"] = deepcopy(data)
            actions = payload["data"].get("actions")
            for action in actions if isinstance(actions, list) else []:
                if isinstance(action, dict) and isinstance(action.get("title"), str):
                    action["title"] = text(action["title"])
        return payload
    except Exception:
        # A missing/broken translation must never stop an operational notification.
        return original


def _send(target: str, title: str, message: str, data: dict = None, key: str | None = None):
    """Skickar en notis (eventuellt med action-knappar) till en specifik HA-mottagare: en notify-tjänst (t.ex.
    mobile_app_pixel_8) eller ett skript ("script.mitt_skript", #170) som får variablerna title, message (och data)."""
    _init()
    payload = _localized_payload(title, message, data)
    domain, svc = ("script", target.split(".", 1)[1]) if target.startswith("script.") else ("notify", target)
    try:
        # #188: 5 s räckte inte alltid (HA:s push via molnet eller ett skript som tar tid). Inget nytt försök: en sen
        # men levererad notis skulle då komma två gånger.
        r = requests.post(f"{_ha_base}/services/{domain}/{svc}", headers=_ha_headers, json=payload, timeout=20, verify=False)
        r.raise_for_status()
        print(f"🔔 Notis → {target}: {title}")
        _hist(title, message, "sent", target, key)
        return True
    except Exception as e:
        # HA nere, timeout eller HTTP-svar från notify-tjänsten är drift (#249), inte programfel.
        # Telemetrin gör GitHub-ärenden av ❌. Historiken sparar ändå "failed".
        mark = "⚠️" if isinstance(e, requests.RequestException) else "❌"
        print(f"{mark} Notis misslyckades ({target}): {e}")
        try:
            import notify_log
            _hist(title, message, "failed", target, key, notify_log.short_error(e))
        except Exception:
            pass
        return False


def _hist(title, message, status, target=None, key=None, detail=None):
    """Aviseringshistoriken (notify_log.py) - får aldrig stoppa själva aviseringen."""
    try:
        import notify_log
        notify_log.add(title, message, status, target, key, detail)
    except Exception:
        pass


_phones_cache = {"t": 0.0, "list": []}


def _all_phones() -> list:
    """Alla mobilappar i Home Assistant (notify.mobile_app_*), läses om högst en gång i timmen."""
    import time
    if time.time() - _phones_cache["t"] < 3600 and _phones_cache["list"]:
        return _phones_cache["list"]
    _init()
    try:
        r = requests.get(f"{_ha_base}/services", headers=_ha_headers, timeout=10, verify=False)
        r.raise_for_status()
        svcs = next((d.get("services") or {} for d in r.json() if d.get("domain") == "notify"), {})
        _phones_cache.update(t=time.time(), list=sorted(n for n in svcs if n.startswith("mobile_app_")))
    except Exception:
        pass
    return _phones_cache["list"]


def home_only() -> bool:
    try:
        import ew_settings
        return bool(ew_settings.get("notify_home_only"))
    except Exception:
        return False


def _persons() -> dict:
    """device_tracker -> personens läge ("home"/"not_home"/zon) för alla person.* i Home Assistant."""
    _init()
    out = {}
    try:
        r = requests.get(f"{_ha_base}/states", headers=_ha_headers, timeout=10, verify=False)
        r.raise_for_status()
        for s in r.json():
            if str(s.get("entity_id", "")).startswith("person."):
                for trk in (s.get("attributes") or {}).get("device_trackers") or []:
                    out[trk] = (s.get("state") or "").lower()
    except Exception:
        pass
    return out


def phone_home(service: str, persons: dict | None = None):
    """True/False om telefonens person (person.* som har telefonens device_tracker) är hemma/borta. None = telefonen hör
    inte till någon person (t.ex. en surfplatta på väggen, som alltid är "hemma") eller platsen är okänd."""
    persons = _persons() if persons is None else persons
    st = persons.get("device_tracker." + service.removeprefix("notify.").removeprefix("mobile_app_"))
    if st in (None, "", "unknown", "unavailable"):
        return None
    return st == "home"


def pick_home(services: list) -> list:
    """Martins jämförelse 2026-11-07 (Familjetavlans hemlarm): bara till de vuxna som är hemma. Ingen hemma men platsen
    känd -> alla (en husavisering är viktigast när huset är tomt). Ingen plats känd -> listan som den är."""
    persons = _persons()
    states = {s: phone_home(s, persons) for s in services}
    known = [s for s, v in states.items() if v is not None]
    if not known:
        return services
    home = [s for s in known if states[s]]
    return home or known                     # ingen hemma: alla personers telefoner (inte väggplattor)


def recipients() -> list:
    """Mottagarna för en avisering om huset - samma regel i motorn och mobilappen. Utan "bara den som är hemma": den
    valda mottagaren (eller den första telefonen). Med: telefonerna som är hemma (se pick_home)."""
    t = target()
    if not home_only() or (t or "").startswith("script."):
        return [t] if t else []
    phones = _all_phones() or ([t] if t else [])
    return pick_home(phones)


def send_emil(title: str, message: str, data: dict = None, key: str | None = None):
    """Avisering till husets ägare (namnet är historiskt). key = notiskategori (notify_prefs.py); utan den härleds
    kategorin ur rubriken. Avstängda kategorier skickas inte."""
    try:
        import notify_prefs
        if not notify_prefs.enabled(key, title):
            print(f"🔕 Notis avstängd ({key or notify_prefs.category_for(title)}): {title}")
            _hist(title, message, "muted", None, key)
            return False
    except Exception:
        pass
    ok = False
    rcpt = recipients()
    if not rcpt:
        _hist(title, message, "none", None, key, "Ingen telefon vald eller hittad i Home Assistant")
    for t in rcpt:
        ok = _send(t, title, message, data, key) or ok
    return ok






def morning_price_tip(all_prices: list, cheap_hours_count: int, weekday: int):
    """
    Skickar morgonnotis med dagens billigaste timmar.
    all_prices  – lista med 96 kvartispriser (kr/kWh)
    cheap_hours_count – antal billiga timmar per dag
    weekday     – 0=måndag ... 6=söndag
    """
    if not all_prices:
        return
    import nordpool
    symbol = nordpool.cost_settings()["symbol"]

    # Hitta de billigaste timmarna (4 kvartar per timme)
    # Gruppera kvartar till timmar och räkna snittpris per timme
    hour_prices = []
    for h in range(24):
        quarter_slice = all_prices[h*4:(h+1)*4]
        if quarter_slice:
            hour_prices.append((h, sum(quarter_slice) / len(quarter_slice)))

    # Sortera på pris och ta de billigaste timmarna
    sorted_hours = sorted(hour_prices, key=lambda x: x[1])
    cheap_hours  = sorted(sorted_hours[:cheap_hours_count], key=lambda x: x[0])  # Sortera på tid

    # Bygg ihop sammanhängande block för läsbarhet
    if not cheap_hours:
        return

    blocks = []
    start_h, price_sum, count = cheap_hours[0][0], cheap_hours[0][1], 1
    prev_h = cheap_hours[0][0]

    for h, p in cheap_hours[1:]:
        if h == prev_h + 1:
            price_sum += p
            count += 1
        else:
            avg = price_sum / count
            end_h = prev_h + 1
            blocks.append(f"  {start_h:02d}:00–{end_h:02d}:00 ({avg:.2f} {symbol}/kWh)")
            start_h, price_sum, count = h, p, 1
        prev_h = h

    avg = price_sum / count
    end_h = prev_h + 1
    blocks.append(f"  {start_h:02d}:00–{end_h:02d}:00 ({avg:.2f} {symbol}/kWh)")

    day_name = ["måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag"][weekday]
    message  = "Bra tider att köra disk eller tvätt:\n" + "\n".join(blocks)
    send_emil(f"⚡ Eltips {day_name}", message)




def alert_high_price(price: float, limit: float):
    """Notis vid extremt högt elpris."""
    import nordpool
    symbol = nordpool.cost_settings()["symbol"]
    send_emil("🚨 Extremt högt elpris!", f"Priset är nu {price:.3f} {symbol}/kWh (>{limit:.2f} {symbol}). Undvik tunga maskiner!")


def alert_low_price(price: float):
    """Notis vid extremt lågt elpris (eller negativt)."""
    import nordpool
    symbol = nordpool.cost_settings()["symbol"]
    send_emil("🎉 Extremt lågt elpris!", f"Priset är nu {price:.3f} {symbol}/kWh – perfekt att köra energikrävande saker!")


def alert_pump_alarm(alarm_code: int):
    """Notis vid värmepumplarm."""
    send_emil("🔧 Värmepumplarm!", f"Larmkod: {alarm_code}. Kontrollera värmepumpen.")


def alert_solar_error(status: int):
    """Notis vid fel på växelriktaren."""
    send_emil("☀️ Solcellsfel!", f"Växelriktaren rapporterar status {status}. Kontrollera anläggningen.")


def alert_offline(device_name: str):
    """Notis när en viktig enhet tappar kontakt."""
    send_emil(f"📡 {device_name} offline", f"{device_name} svarar inte. Kontrollera anslutningen.")

def notify_spa_ready(temp: float):
    """Notis till Emil när spabadet nått måltemperaturen."""
    send_emil("🛁 Spabadet är redo!", f"Temperaturen är nu {temp:.1f} °C.")

def notify_ev_charging(car_name: str, power_kw: float):
    """Notis till Emil när elbilen börjar ladda."""
    send_emil("🚗 Bilen laddar", f"Laddningen av {car_name} har startat med {power_kw:.1f} kW.")

def notify_ev_full(car_name: str, soc: float):
    """Notis när elbilen är färdigladdad."""
    send_emil("✅ Bilen är färdigladdad", f"Laddningen av {car_name} har avslutats. Batterinivån är nu {soc:.0f} %.")

def notify_washing_machine():
    """Notis till Emil när tvättmaskinen startar."""
    send_emil("🧺 Tvättmaskinen startad", "Tvättmaskinen (Miele) är igång.")


def alert_disk_warning(disk_pct: float, disk_free_gb: float, db_total_gb: float, sensor_log_gb: float):
    """Notis när disken börjar bli full (>80%)."""
    send_emil(
        "💾 Diskvarning – energyWiz",
        f"Disk {disk_pct:.0f}% full – {disk_free_gb:.1f} GB kvar.\n"
        f"Databas totalt: {db_total_gb:.2f} GB, sensor_log: {sensor_log_gb:.2f} GB.\n"
        "Överväg att utöka LXC-volymen."
    )

def notify_solar_limit_start(limit_pct: int):
    """Notis till Emil när solcellerna begränsas."""
    send_emil("📉 Solceller begränsas", f"Produktionen stryps nu till {limit_pct}% på grund av lågt elpris.")

def notify_solar_limit_stop():
    """Notis till Emil när begränsningen av solceller upphör."""
    send_emil("✅ Solceller åter normala", "Produktionsbegränsningen har avslutats. Kör 100% igen.")

def alert_spa_cover(actual_drop: float, expected_drop: float):
    """Notis till Emil när spabadet tappar onormalt mycket värme."""
    send_emil(
        "🛁 Varning: Spabadet tappar värme!",
        f"Temperaturen har sjunkit {actual_drop:.1f} °C senaste timmen (förväntat var ca {expected_drop:.1f} °C/h vid denna utetemp). Har locket glömts öppet?"
    )

def notify_spa_solar_boost_start():
    """Notis till Emil när spabadet laddas gratis (sol eller minuspris)."""
    send_emil(
        "☀️ Spabad Sol-boost!",
        "Elen är gratis (solöverskott/minuspris). Spabadet laddas nu som ett stort termiskt batteri. Det blir ett varmt bad ikväll! 🛁"
    )



def notify_spa_solar_boost_stop(temp: float):
    """Notis till Emil när spabadets sol-boost avaktiveras."""
    send_emil(
        "🛑 Spabad Sol-boost Avslutad",
        f"Gratis-laddningen är nu pausad eller färdig. Spabadets temperatur är {temp:.1f} °C."
    )






def notify_away_recovery_started(start_time, target_time):
    """Notis när återgång från bortaläge startar."""
    start_str = start_time.strftime("%H:%M")
    target_str = target_time.strftime("%H:%M")
    send_emil(
        "🏠 Återgång till komfortläge",
        f"EnergyWizard: Återgång till komfortläge startad. Beräknad starttid fastställd till {start_str} baserat på ΔT och vindförhållanden vid Torsvik. Måltemperatur nås kl. {target_str}. Spabadet förblir i viloläge."
    )


def alert_indoor_temp_sensor_offline():
    """Notis när innetemperatursensorerna från Home Assistant slutar fungera."""
    send_emil(
        "🌡️ Varning: Innegivare Offline!",
        "EnergyWizard har inte fått några giltiga temperaturvärden (>0°C) från innegivarna (Home Assistant) på över 15 minuter. Värmepumpen använder nu sin egen inbyggda givare som tillfällig backup."
    )

def alert_price_fallback():
    """Notis när dagens elpriser saknas och systemet kör på gårdagens prisprofil."""
    send_emil(
        "⚠️ Elpriser saknas",
        "Kunde inte hämta dagens elpriser (elprisetjustnu.se kanske är nere). Systemet använder "
        "gårdagens prisprofil som approximation tills riktiga priser finns igen."
    )

def alert_indoor_cold(indoor_temp: float, floor: float, pump_is_manual: bool = False):
    """Säkerhetslarm när det blir kallt inne. Slår INTE på värmen – bara varnar."""
    extra = ""
    if pump_is_manual:
        extra = " Värmepumpen står i MANUELLT läge och värmer inte huset automatiskt – växla tillbaka till auto om du vill ha värme."
    send_emil(
        "🥶 Kallt inomhus!",
        f"Inomhustemperaturen har sjunkit till {indoor_temp:.1f}°C (under {floor:.0f}°C).{extra}"
    )

def alert_peak_shaving_warning(consumed_kwh, current_limit):
    """Notis när tim-medeleffekten riskerar att slå aktuellt effekttak."""
    send_emil(
        "⚠️ Varning: Effekttak hotat!",
        f"Denna timme har du hittills förbrukat {consumed_kwh:.2f} kWh. Systemet bromsar nu ner tunga laster för att inte överskrida ditt tak på {current_limit:.2f} kW."
    )

def alert_high_net_power(current_kw: float, limit_kw: float, duration_mins: int):
    """Notis när huset drar mycket el från nätet oavbrutet under en längre tid."""
    send_emil(
        "⚠️ Hög nettoförbrukning!",
        f"Huset drar just nu {current_kw:.1f} kW från nätet, och har legat över din gräns ({limit_kw:.1f} kW) oavbrutet i över {duration_mins} minuter."
    )

def alert_unexplained_load(unexplained_kw: float, total_kw: float, ev_kw: float, pump_kw: float, spa_kw: float,
                           phases=None, gross_import_kw: float = None, grid_lb_kw: float = None, pv_frozen: bool = False):
    """Notis: stor OFÖRKLARAD last (utöver elbil/värmepump/spa) som hållit i sig en stund.
    Talar om exakt hur mycket som är känt och hur mycket som är oförklarat, och bekräftas av fasströmmarna."""
    extra = ""
    if phases and gross_import_kw is not None:
        _fmt = lambda a: "–" if a is None else f"{a:.1f}"
        extra = (f"\n\n⚡ Fasströmmar (nät): L1 {_fmt(phases[0])} A · L2 {_fmt(phases[1])} A · L3 {_fmt(phases[2])} A. "
                 f"Nätimport {gross_import_kw:.1f} kW mot känt {ev_kw + pump_kw + spa_kw:.1f} kW → minst {grid_lb_kw:.1f} kW oförklarat enligt fasströmmarna.")
        if pv_frozen:
            extra += "\n(Solvärdet var oförändrat i 5 min och räknades inte med.)"
    send_emil(
        "🔍⚠️ Oförklarad hög last",
        f"Huset drar ~{total_kw:.1f} kW, varav **{unexplained_kw:.1f} kW är OFÖRKLARAT** "
        f"(inte elbil, värmepump eller spa).\n\n"
        f"Känt just nu: 🚗 Elbil {ev_kw:.1f} kW · ♨️ Värmepump {pump_kw:.1f} kW · 🛁 Spa {spa_kw:.1f} kW.\n"
        f"Kolla t.ex. ugn, bastu, tvätt/tork, laddare eller element." + extra
    )
