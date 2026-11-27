"""SolarEdge via Home Assistant (steg 5b av uppdelningen). Förut låg koden i homeassistant.py."""
from drivers.host import homeassistant as ha

# Entiteterna kommer ur installationen (solar.entities i house_config.yaml) - inga husspecifika namn här.
# Bara de officiella integrationernas egna standardnamn finns som reserv.
DEFAULT_PV = ["sensor.solaredge_i1_ac_power", "sensor.solaredge_current_power", "sensor.solaredge_ac_power"]
DEFAULT_TODAY = ["sensor.solaredge_energy_today"]
DEFAULT_STATUS = ["sensor.solaredge_i1_status", "sensor.solaredge_status"]
DEFAULT_LIMIT = "number.solaredge_modbus_active_power_limit"   # solaredge_modbus-integrationens namn


def _as_list(v):
    if v in (None, ""):
        return []
    return [x for x in (v if isinstance(v, (list, tuple)) else [v]) if x]


def read(entities=None):
    """Solproduktion från SolarEdge via Home Assistant. entities (solar.entities i installationen):
    pv_power_w, today_kwh, status - var och en en entitet eller en lista (första som har ett värde vinner).
    Lägg den snabba Modbus-entiteten först och moln-integrationen efter (molnet uppdateras bara var 15:e minut och kan
    ligga flera kW fel när det växlar molnigt/soligt, 2026-09-20). De officiella integrationernas standardnamn
    prövas sist."""
    e = entities or {}

    def get_first_numeric(ents):
        for x in ents:
            val = ha._get_numeric_state(x)
            if val is not None:
                return val
        return None

    def get_first_raw(ents):
        for x in ents:
            val = ha._get_raw_state(x)
            if val is not None:
                return val
        return None

    def _chain(own, defaults):
        own = _as_list(own)
        return own + [d for d in defaults if d not in own]

    return {
        "pv_power_w": get_first_numeric(_chain(e.get("pv_power_w"), DEFAULT_PV)),
        "today_kwh": get_first_numeric(_chain(e.get("today_kwh"), DEFAULT_TODAY)),
        "status": get_first_raw(_chain(e.get("status"), DEFAULT_STATUS)),
    }


def get_limit(entity: str | None = None):
    """Hämtar Active Power Limit (%) för SolarEdge (solar.curtailment.entity, annars integrationens standardnamn)."""
    return ha._get_numeric_state(entity or DEFAULT_LIMIT)


def set_limit(limit: int, entity: str | None = None):
    """Sätter Active Power Limit (%) för SolarEdge."""
    try:
        ha.post_service("number/set_value", {"entity_id": entity or DEFAULT_LIMIT, "value": str(limit)}, 5)
        print(f"☀️ SolarEdge: Active Power Limit satt till {limit} %")
        return True
    except Exception as e:
        ha.report_failure(f"SolarEdge: Fel vid sättning av limit: {e}", e)
        return False
