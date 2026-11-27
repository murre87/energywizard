"""Easee-laddboxen via Home Assistant (steg 5b av uppdelningen, docs/uppdelning/PLAN.md). Förut låg koden i homeassistant.py.

Bara den generella delen av värden används (läsa state, skicka en HA-tjänst): märkeskunskapen (tjänstenamn, fasströmsattribut, fasläget
som inte går att läsa tillbaka) bor här, hos drivrutinen. homeassistant.py har tunna vidarekopplingar med de gamla namnen."""
import requests

from drivers.host import homeassistant as ha

# Fasläge: HA:s Easee-integration (0.9.74, efter HA-uppdateringen 2026-10-14) har inga select-entiteter längre (select.*_allowed_charging_phases finns inte),
# så fasläget går inte att läsa. Vi minns det senast satta värdet per laddare; utan minne (efter omstart) returneras None (okänt).
_PHASE_STATE: dict = {}


def read_charger(entities: dict, charger_id: str | None = None):
    try:
        result = {}
        for key, entity in entities.items():
            if key in ("status", "reason_no_current"):
                result[key] = ha._get_raw_state(entity)
            else:
                result[key] = ha._get_numeric_state(entity)

        # Fasströmmar: integrationen har en enda ström-sensor; fasernas strömmar ligger som attribut (T3/T4/T5 = L1/L2/L3).
        # Nyare Easee-integration (2026) döper dem state_inCurrentT3 osv. - båda namnen läses (2026-11-07: fasströmmarna
        # blev None för alla med Easee, och bilarnas faser/maxström kunde inte läras in).
        _ce = entities.get("current_a")
        if _ce:
            for _k, _t in (("current_l1", "T3"), ("current_l2", "T4"), ("current_l3", "T5")):
                if result.get(_k) is None:
                    v = ha._get_numeric_attribute(_ce, f"state_inCurrent{_t}")
                    result[_k] = v if v is not None else ha._get_numeric_attribute(_ce, f"inCurrent{_t}")

        raw_power = result.get("power_kw")
        power_kw = (raw_power / 1000.0) if raw_power is not None and raw_power > 100 else raw_power

        # FIX #9 (konservativ, bakåtkompatibel): faktiskt uppmätt fasström.
        # current_l1/l2/l3 lästes tidigare in i result men returnerades aldrig,
        # trots att main.py (rad 953-958) hämtar dem för lastbalansering -> de blev alltid None.
        # Vi inkluderar dem nu i return-dicten (för BÅDA laddarna; saknas entiteten blir den None).
        cur_l1 = result.get("current_l1")
        cur_l2 = result.get("current_l2")
        cur_l3 = result.get("current_l3")

        # current_a pekade på maximum_allowed_charge_current (gränsvärde, ej uppmätt ström).
        # Om en faktisk strömsensor finns (current_l1/l2/l3) använder vi den uppmätta strömmen
        # (max över faserna) så att loggad ev_current_a speglar verkligheten.
        # Saknas mätsensorer behålls det gamla beteendet (gränsvärdet) -> inget bryts.
        measured_phases = [c for c in (cur_l1, cur_l2, cur_l3) if c is not None]
        current_a = max(measured_phases) if measured_phases else result.get("current_a")

        return {
            "power_kw":        power_kw,
            "current_a":       current_a,
            "current_l1":      cur_l1,
            "current_l2":      cur_l2,
            "current_l3":      cur_l3,
            "dynamic_limit_a": result.get("dynamic_limit"),
            "output_limit_a":  result.get("output_limit"),
            "max_limit_a":     result.get("max_limit"),
            "circuit_limit_a": result.get("circuit_limit"),          # #385: lastbalanseringens kretsgräns (Equalizer)
            "circuit_rated_a": ha._get_numeric_attribute(entities["status"], "circuit_ratedCurrent") if entities.get("status") else None,
            "session_kwh":     result.get("session_kwh"),
            "lifetime_kwh":    result.get("lifetime_kwh"),
            "status":          result.get("status"),
            "online":          bool(result.get("online")),
            "reason_no_current": result.get("reason_no_current"),
            "phases":          ha._get_raw_state(entities.get("phases")) or _PHASE_STATE.get(charger_id)   # per laddbox
        }
    except Exception as e:
        ha.report_failure(f"HA: Fel vid läsning av laddare: {e}", e)
        return None


def set_dynamic_limit(charger_id: str, ampere: int, reason: str = None):
    if int(ampere) > 0:
        ampere = max(6, min(int(ampere), 32))
    else:
        ampere = 0
    try:
        ha.post_service("easee/set_charger_dynamic_limit", {"charger_id": charger_id, "current": ampere}, 5)
        if ampere == 0 and reason:
            print(f"⚡ Easee: Dynamisk gräns satt till 0 A. Anledning: {reason}")
        else:
            print(f"⚡ Easee: Dynamisk gräns satt till {ampere} A")
        return True
    except requests.exceptions.HTTPError as e:
        print(f"❌ Easee: Fick 500 Server Error. Är Laddar-ID '{charger_id}' korrekt? Lägg in EASEE_CHARGER_ID=ditt_id i .env filen! Felet var: {e}")
        return False
    except Exception as e:
        ha.report_failure(f"Easee: Fel vid sättning av strömgräns: {e}", e)
        return False


def set_phases(charger_id: str, phases: int):
    """Sätter laddaren till 1-fas eller 3-fas via Easee-integrationens tjänst easee.set_charger_phase_mode (select-entiteten finns inte längre).
    Lyckas bara om HA svarar OK; då sparas det nya läget som 'nuvarande' (det går inte att läsa tillbaka), så att GPM inte begär samma byte varje minut."""
    if phases not in [1, 3]:
        print(f"❌ Easee: Ogiltigt fasval: {phases}. Måste vara 1 eller 3.")
        return False
    mode = "3_phase" if phases == 3 else "1_phase"
    try:
        ha.post_service("easee/set_charger_phase_mode", {"charger_id": charger_id, "phase_mode": mode}, 10)
        _PHASE_STATE[charger_id] = "ThreePhase" if phases == 3 else "SinglePhase"
        print(f"⚡ Easee ({charger_id}): Fasläge satt till {phases}-fas (tjänst, {mode}).")
        return True
    except Exception as e:
        ha.report_failure(f"Easee ({charger_id}): Fel vid sättning av fasläge: {e}", e)
        return False


def turn_on(charger_id: str, entity_id: str | None = None):
    """Tvingar laddaren att starta om den står i awaiting_start eller paused."""
    if not entity_id:                                # påslagsbrytaren kommer ur installationen (charger.enable_switch)
        print(f"ℹ️ Easee ({charger_id}): ingen påslagsbrytare (enable_switch) i installationen - kan inte slå på/av laddboxen.")
        return False
    try:
        ha.post_service("switch/turn_on", {"entity_id": entity_id}, 5)
        print(f"⚡ Easee ({charger_id}): Skickade 'turn_on' för att tvinga igång laddningen.")
        return True
    except Exception as e:
        ha.report_failure(f"Easee ({charger_id}): Fel vid turn_on: {e}", e)
        return False


def turn_off(charger_id: str, entity_id: str | None = None):
    """Tvingar laddaren att stanna."""
    if not entity_id:                                # påslagsbrytaren kommer ur installationen (charger.enable_switch)
        print(f"ℹ️ Easee ({charger_id}): ingen påslagsbrytare (enable_switch) i installationen - kan inte slå på/av laddboxen.")
        return False
    try:
        ha.post_service("switch/turn_off", {"entity_id": entity_id}, 5)
        print(f"⚡ Easee ({charger_id}): Skickade 'turn_off' för att stoppa laddningen.")
        return True
    except Exception as e:
        ha.report_failure(f"Easee ({charger_id}): Fel vid turn_off: {e}", e)
        return False
