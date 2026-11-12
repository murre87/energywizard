"""ev_missed.py - varför missade bilen morgonmålet, och när ska vi larma?

Bakgrund (Emils Leaf natt 11/12 nov 2026, samma klass som 28/29 okt):
  - Schemat/golvet krävde 50 % kl 06–07.
  - Motorn skrev "Laddar enligt schema" men Leaf stod kvar på ~32 %.
  - Delar av natten fick Leaf 0 A (Tesla hade högre prio och tog säkringen).
  - När Leaf fick 8–10 A stod laddaren i awaiting_start och drog 0 kW.
  - Morgongolv-varningen gick kl 04:30, men ingen notis när målet faktiskt missades.

Den här modulen är ren logik (inga DB/HA-anrop) så den kan testas utan motorn.
"""
from __future__ import annotations

MORNING_MIN_SOC = 50


def explain(
    soc,
    target_soc,
    ordered_a=0,
    power_kw=0,
    status=None,
    minutes_zero_order=0,
    minutes_stalled=0,
    sibling_name=None,
    sibling_got_power=False,
) -> str:
    """En mening Emil kan agera på: vad som gick fel inatt."""
    soc_txt = "okänd nivå" if soc is None else f"{soc:.0f} %"
    parts = [f"Målet var {target_soc:.0f} %, bilen hade {soc_txt}."]
    st = (status or "okänd").strip() or "okänd"

    if minutes_zero_order >= 30:
        who = sibling_name or "den andra bilen"
        if sibling_got_power:
            parts.append(
                f"EnergyWizard gav den 0 A i {minutes_zero_order:.0f} min medan {who} "
                f"laddade (lägre prioritet / säkringen räckte inte till båda)."
            )
        else:
            parts.append(
                f"EnergyWizard gav den 0 A i {minutes_zero_order:.0f} min "
                f"(ingen plats i planen / säkringen)."
            )

    if minutes_stalled >= 15 and ordered_a >= 6:
        parts.append(
            f"När den fick {ordered_a:.0f} A stod laddaren i '{st}' och drog ~0 kW i "
            f"{minutes_stalled:.0f} min (kabel, bilens laddgräns eller laddaren svarade inte)."
        )
    elif ordered_a >= 6 and (power_kw or 0) < 0.3:
        parts.append(
            f"Senaste beställningen var {ordered_a:.0f} A men uppmätt effekt ~"
            f"{(power_kw or 0):.1f} kW (status: {st})."
        )
    elif (power_kw or 0) < 0.3:
        parts.append(f"Laddaren drog ingen ström (status: {st}).")

    parts.append("Kolla kabeln, bilens maxladdning och laddaren i Easee/HA.")
    return " ".join(parts)


def due_missed_alert(*, soc, target_soc, plugged_in, now, deadline, already_key) -> bool:
    """True en gång per bil/deadline när tiden passerat och nivån fortfarande är under målet."""
    if not plugged_in or soc is None or deadline is None:
        return False
    if soc >= target_soc:
        return False
    if now < deadline:
        return False
    # Bara första timmen efter deadline (annars spam hela dagen).
    if (now - deadline).total_seconds() > 3600:
        return False
    return already_key != deadline
