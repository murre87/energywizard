"""
lawnmower.py – Beslutslogik för Robotgräsklippare (Husqvarna)

Hanterar status, säkerhet och väderstyrning baserat på effektmätning från en smart plug.
Filen är skriven för att vara helt "stateless" mellan körningar, all tillståndsinformation
skickas in och returneras, för att passa EnergyWizards huvudloop.
"""

from datetime import datetime, timedelta

# --- Tillståndsvariabler (globala för denna modul) ---

# Håller nuvarande status, t.ex. "Klipper", "Laddar", "Vilar", "Okänd"
# Debounce-tid i sekunder. En status måste vara stabil så här länge innan den bekräftas.
DEBOUNCE_SECONDS = 30

# Säkerhetsregler
POWER_OFF_AUTO_ON_MINUTES = 5
POWER_OFF_ALARM_MINUTES = 15

# Laddcykel-detektor: hur länge låg effekt (~0W) efter en laddning får tolkas som "ute och klipper"
# innan vi drar slutsatsen att klipparen i själva verket bara vilar fulladdad i dockan.
# (En klippare som är ute kommer tillbaka och laddar inom en rimlig klipp-session.)
MAX_MOW_SESSION_MINUTES = 120

def update_status_and_decide_action(mower_state, power_w, is_on, is_raining, is_thunder, settings, now):
    """
    Huvudfunktionen som analyserar data och returnerar en action-lista.

    Args:
        mower_state (dict): Klipparens nuvarande tillstånd från main.py.
        power_w (float): Aktuell effektförbrukning från smart plug.
        is_on (bool): Om pluggen är påslagen.
        is_raining (bool): Om det regnar.
        is_thunder (bool): Om det åskar.
        settings (dict): Systeminställningar med gränsvärden.
        now (datetime): Aktuell tidpunkt.

    Returns:
        (dict, dict): En tuple med det uppdaterade state-objektet och en dictionary med actions.
    """
    # Läs in tillstånd från föregående körning
    current_status = mower_state.get('status', 'Okänd')
    status_candidate = mower_state.get('status_candidate')
    status_candidate_since = mower_state.get('status_candidate_since')
    power_off_by_weather = mower_state.get('power_off_by_weather', False)
    power_off_since = mower_state.get('power_off_since')
    weather_recovery_notified = mower_state.get('weather_recovery_notified', False)
    low_power_since = mower_state.get('low_power_since')

    actions = {}

    # Hämta gränsvärden från inställningarna
    clipping_threshold = settings.get("mower_mowing_threshold_w", 3.2)
    charging_threshold = settings.get("mower_charging_threshold_w", 10.0)

    # 1. Bestäm rå-status baserat på effekt + LADDCYKEL-KONTEXT.
    #    Problemet: en klippare som är UTE (dockan tom, ~0W) och en som VILAR fulladdad utan
    #    trickle (~0W) ser identiska ut i watt. Vi skiljer dem via laddcykeln:
    #    låg effekt DIREKT EFTER en laddning = klipparen lämnade dockan (Klipper);
    #    låg effekt som varat längre än en rimlig klipp-session utan återladdning = den vilar.
    raw_status = "Okänd"
    if is_on and power_w is not None:
        if power_w > charging_threshold:
            raw_status = "Laddar"
            low_power_since = None
        elif power_w >= clipping_threshold:
            raw_status = "Vilar"            # drar trickle (3.2–10W) → står kvar i dockan
            low_power_since = None
        else:
            # <clipping_threshold: dockan drar ~0 → ute ELLER vilar fulladdad. Kontext avgör.
            if low_power_since is None:
                low_power_since = now
            low_minutes = (now - low_power_since).total_seconds() / 60.0
            if current_status == "Laddar":
                raw_status = "Klipper"      # lämnade precis dockan efter laddning → klipper
            elif current_status == "Klipper" and low_minutes < MAX_MOW_SESSION_MINUTES:
                raw_status = "Klipper"      # fortfarande ute inom en rimlig klipp-session
            else:
                raw_status = "Vilar"        # för länge ute utan återladdning, eller vilade redan
    elif not is_on:
        raw_status = "Avstängd"
        low_power_since = None

    # 2. Debounce-logik
    if raw_status != status_candidate:
        # En ny potentiell status har dykt upp, starta timern
        status_candidate = raw_status
        status_candidate_since = now
    elif status_candidate_since and (now - status_candidate_since).total_seconds() >= DEBOUNCE_SECONDS:
        # Kandidaten har varit stabil tillräckligt länge, bekräfta den som ny status
        if current_status != status_candidate:
            print(f"🤖 Gräsklippare: Status ändrad från '{current_status}' till '{status_candidate}'")
            current_status = status_candidate
            actions['new_lawnmower_status'] = current_status

    # 3. Säkerhets- och väderregler för strömstyrning
    is_bad_weather = is_raining or is_thunder

    # "Klipper just nu" enligt LIVE-effekten (inte den fördröjda statusen). Skyddar mot
    # glipan precis efter att klipparen lämnat stationen, innan debouncen hunnit bekräfta
    # "Klipper" – annars skulle väderregeln kunna kapa strömmen till en klippare som är ute.
    live_mowing = is_on and power_w is not None and power_w < clipping_threshold

    # Regel: Stäng av vid dåligt väder – ENDAST om klipparen står i stationen (Laddar/Vilar)
    # och definitivt INTE klipper just nu (live-effekt). Status "Klipper"/"Okänd"/"Avstängd"
    # rör vi inte, eftersom vi då inte säkert vet att klipparen är dockad.
    if is_on and is_bad_weather and current_status in ("Laddar", "Vilar") and not live_mowing:
        actions['power'] = 'off'                 # (åter)utfärdas tills pluggen faktiskt är av
        if not power_off_by_weather:             # notis bara vid övergången → max 1/händelse
            actions['notify_weather_off'] = True
        power_off_by_weather = True

    # Regel: Slå på strömmen igen när vädret är bra. Behåll väderflaggan tills pluggen
    # bekräftat är på, så att återhämtningen retas om HA-kommandot missar (och inte
    # felaktigt klassas som en 5-min-failsafe).
    elif power_off_by_weather and not is_bad_weather:
        if not is_on:
            actions['power'] = 'on'              # (åter)utfärdas tills pluggen är på
        if not weather_recovery_notified:
            actions['notify_weather_on'] = True
            weather_recovery_notified = True

    # Väderflaggan nollställs först när strömmen verkligen är på igen.
    if power_off_by_weather and is_on and not is_bad_weather:
        power_off_by_weather = False
        weather_recovery_notified = False

    # Hantera power_off_since-tidsstämpeln
    if not is_on and power_off_since is None:
        power_off_since = now
    elif is_on:
        power_off_since = None

    # Regel: 5-minuters failsafe om strömmen är av utan väderanledning
    if not is_on and power_off_since and not power_off_by_weather and (now - power_off_since).total_seconds() >= POWER_OFF_AUTO_ON_MINUTES * 60:
        actions['power'] = 'on'
        actions['notify_failsafe_on'] = True

    # Regel: 15-minuterslarm
    if not is_on and power_off_since and (now - power_off_since).total_seconds() >= POWER_OFF_ALARM_MINUTES * 60:
        actions['notify_long_offline'] = True

    # Absolut förbud: Stäng aldrig av om klipparen är ute – varken enligt bekräftad status
    # ELLER enligt live-effekten (skyddar även i debounce-glipan).
    if actions.get('power') == 'off' and (current_status == "Klipper" or live_mowing):
        print("🚨 SÄKERHETSSTOPP: Försökte stänga av strömmen medan klipparen är ute. Blockerar åtgärd.")
        del actions['power']

    # Uppdatera och returnera det nya tillståndet
    new_state = {
        'status': current_status,
        'status_candidate': status_candidate,
        'status_candidate_since': status_candidate_since,
        'power_off_by_weather': power_off_by_weather,
        'power_off_since': power_off_since,
        'weather_recovery_notified': weather_recovery_notified,
        'low_power_since': low_power_since,
    }

    return new_state, actions