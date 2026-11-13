"""charge_now.py - "Ladda nu till X %" som avslutas av sig själv (#394).

"Ladda nu" laddade förut tills användaren själv valde Auto igen, även på dyra timmar. Med ett mål avslutas det när
bilen når målet, när kabeln dras ur eller efter MAX_S (24 h). Därefter tar planen över. Utan mål ("Tills jag
stoppar") fungerar det som förut. Säkringsskyddet gäller hela tiden, och bilens vanliga mål och klar-tid ändras
inte. Idé från Darkstars "Charge now" (github.com/ergetie/darkstar), egen implementation.

Överstyrningar (logger.set_override): <bil>_charge_now_target (procent) och <bil>_charge_now_until (unix-tid)."""

MAX_S = 24 * 3600


def target(overrides: dict, car: str):
    try:
        v = int(str(overrides.get(f"{car}_charge_now_target") or "").strip())
    except ValueError:
        return None
    return v if 1 <= v <= 100 else None


def until(overrides: dict, car: str):
    try:
        return float(str(overrides.get(f"{car}_charge_now_until") or "").strip())
    except ValueError:
        return None


def should_end(overrides: dict, car: str, soc, connected: bool, now_ts: float):
    """(True, orsak) när en pågående "Ladda nu till X %" ska avslutas, annars (False, None)."""
    t = target(overrides, car)
    if t is None:
        return False, None
    forced = str(overrides.get(f"{car}_force_amps") or "0").strip()
    if not forced.isdigit() or int(forced) <= 0:
        return True, "stopped"                       # stoppad eller Auto på annat sätt: städa bara upp
    if soc is not None and float(soc) >= t:
        return True, "target"
    if not connected:
        return True, "unplugged"
    u = until(overrides, car)
    if u is not None and now_ts >= u:
        return True, "timeout"
    return False, None


def clear_keys(car: str) -> dict:
    """Överstyrningarna som återställer bilen till planen."""
    return {f"{car}_force_amps": "0", f"{car}_force_phases": "0", f"{car}_charge_now_target": "",
            f"{car}_charge_now_until": "", "force_ev_recalc": "true"}
