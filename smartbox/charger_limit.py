"""charger_limit.py - förklara när laddboxen ger bilen mindre ström än EnergyWizard bad om (#385).

Förut syntes bara att bilen laddade långsammare än planen. Nu förklaras skillnaden när laddboxens egna värden
förklarar den: erbjuden ström (output_limit), lastbalanseringens kretsgräns (Easee Equalizer, dynamisk
kretsbegränsning) eller kretsens märkström. Annars sägs bara att orsaken är okänd - ingen gissning, och inget
här ändrar styrningen eller säkringsgränserna. Ren funktion, testas i tests/test_issue_385_charger_limit.py."""

RUNNING_A = 1.0         # bilen räknas som laddande
SHORTFALL_A = 1.5       # så mycket under beställningen innan det förklaras
EASEE_REASON = {        # Easees reasonForNoCurrent (som text i HA) -> orsak
    "circuit": "lastbalansering",
    "dynamic": "lastbalansering",
    "charger": "laddboxens maxgräns",
    "schedule": "laddboxens schema",
    "car": "bilen",
}


def _reason(text):
    t = str(text or "").lower()
    return next((v for k, v in EASEE_REASON.items() if k in t), None)


def explain(requested_a, data: dict):
    """Kort förklaring (sträng) eller None. data = laddboxens avläsning (read_raw)."""
    try:
        req = float(requested_a or 0)
        meas = float(data.get("current_a") or 0)
    except (TypeError, ValueError):
        return None
    if req <= 0 or meas < RUNNING_A or meas > req - SHORTFALL_A:
        return None
    out = data.get("output_limit_a")
    circuit = data.get("circuit_limit_a")
    rated = data.get("circuit_rated_a")
    cause = _reason(data.get("reason_no_current"))
    if out is not None and float(out) < req - 0.5:
        why = cause or ("lastbalansering" if circuit is not None and float(circuit) <= float(out) + 0.5 else "laddboxens gräns")
        return f"Laddboxen begränsar till {float(out):.0f} A: {why}. EnergyWizard bad om {req:.0f} A."
    if circuit is not None and float(circuit) < req - 0.5:
        return f"Lastbalanseringen tillåter {float(circuit):.0f} A. EnergyWizard bad om {req:.0f} A."
    if rated is not None and float(rated) < req - 0.5:
        return f"Laddboxens krets är på {float(rated):.0f} A. EnergyWizard bad om {req:.0f} A."
    return f"Laddboxen ger bilen {meas:.0f} A av {req:.0f} A, orsaken är okänd."
