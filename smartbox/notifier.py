import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- Mottagare ---
EMIL = "mobile_app_emils_telefon"

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


def _send(target: str, title: str, message: str, data: dict = None):
    """Skickar en notis (eventuellt med action-knappar) till en specifik HA-mottagare."""
    _init()
    payload = {"title": title, "message": message}
    if data:
        payload["data"] = data
    try:
        r = requests.post(
            f"{_ha_base}/services/notify/{target}",
            headers=_ha_headers,
            json=payload,
            timeout=5,
            verify=False,
        )
        r.raise_for_status()
        print(f"🔔 Notis → {target}: {title}")
        return True
    except Exception as e:
        print(f"❌ Notis misslyckades ({target}): {e}")
        return False


def send_emil(title: str, message: str, data: dict = None):
    return _send(EMIL, title, message, data)






def morning_price_tip(all_prices: list, cheap_hours_count: int, weekday: int):
    """
    Skickar morgonnotis med dagens billigaste timmar.
    all_prices  – lista med 96 kvartispriser (kr/kWh)
    cheap_hours_count – antal billiga timmar per dag
    weekday     – 0=måndag ... 6=söndag
    """
    if not all_prices:
        return

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
            blocks.append(f"  {start_h:02d}:00–{end_h:02d}:00 ({avg:.2f} kr/kWh)")
            start_h, price_sum, count = h, p, 1
        prev_h = h

    avg = price_sum / count
    end_h = prev_h + 1
    blocks.append(f"  {start_h:02d}:00–{end_h:02d}:00 ({avg:.2f} kr/kWh)")

    day_name = ["måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag"][weekday]
    message  = "Bra tider att köra disk eller tvätt:\n" + "\n".join(blocks)
    send_emil(f"⚡ Eltips {day_name}", message)




def alert_high_price(price: float, limit: float):
    """Notis vid extremt högt elpris."""
    send_emil("🚨 Extremt högt elpris!", f"Priset är nu {price:.3f} kr/kWh (>{limit:.2f} kr). Undvik tunga maskiner!")


def alert_low_price(price: float):
    """Notis vid extremt lågt elpris (eller negativt)."""
    send_emil("🎉 Extremt lågt elpris!", f"Priset är nu {price:.3f} kr/kWh – perfekt att köra energikrävande saker!")


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

def notify_mower_status_change(new_status: str, power_w: float):
    """Notis när robotgräsklipparen byter status."""
    status_map = { # Mappning från status i lawnmower.py till notistext
        'Klipper': ("✅ Roboten klipper", f"Klipparen har lämnat stationen (förbrukning: {power_w:.1f}W)."),
        'Laddar': ("🔌 Roboten laddar", f"Klipparen har återvänt till stationen och laddar nu ({power_w:.1f}W)."),
        'Vilar': ("💤 Roboten vilar", f"Klipparen är fulladdad och vilar i stationen ({power_w:.1f}W).")
    } # Avstängd hanteras av andra notiser
    title, message = status_map.get(new_status, (None, None))
    if title:
        send_emil(title, message)

def notify_mower_weather_change(is_on: bool):
    """Notis när väderstyrningen slår av/på klipparen."""
    if is_on:
        send_emil("☀️ Roboten återaktiverad", "Regnet har upphört. Strömmen till klipparen är nu påslagen igen.")
    else:
        send_emil("🌧️ Roboten parkerad", "Regn/åska detekterat. Strömmen till klipparen stängs av för att skydda den.")

def notify_mower_failsafe_reboot():
    send_emil("🤖 Roboten Failsafe", "Strömmen till klipparen var avstängd utan anledning i över 5 minuter. Systemet har automatiskt slagit på den igen.")

def notify_mower_long_offline():
    send_emil("🚨 Roboten Offline?", "Strömmen till klipparen har varit avstängd i över 15 minuter. Kontrollera att allt är OK.")

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

def notify_mower_manual_toggle(is_on: bool):
    """Notis när strömmen till klipparen slås av/på manuellt (utanför systemets egna regler)."""
    if is_on:
        send_emil("🔌 Klippare: Ström PÅ (manuellt)", "Strömmen till robotgräsklipparens laddstation har slagits PÅ manuellt.")
    else:
        send_emil("⚫ Klippare: Ström AV (manuellt)", "Strömmen till robotgräsklipparens laddstation har stängts AV manuellt.")
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
