"""SAJ H2 som skuggrecept (#395).

Registerbilden är översatt för hand från evcc-io/evcc
``templates/definition/meter/saj-h2.yaml`` (MIT, Copyright evcc-io) @ 6b1f958.
Ingen kod är kopierad. Samma karta gäller Ampere.StoragePro i den mallen.

Det här är en loggrad: inga register skrivs och inget nät anropas.
Receptet kan uttrycka självförbrukning, håll utan urladdning, och laddning
på 100 %. Urladdning, en delad effekt och vila tigs.
"""
import math


def _watts(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    watts = int(round(value))
    if abs(watts - value) > 0.5 or not 1 <= watts <= 100_000:
        return None
    return watts


def _percent(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    percent = int(round(value))
    if abs(percent - value) > 0.05 or not 0 <= percent <= 100:
        return None
    return percent


def _limit(cfg, key):
    raw = cfg.get(key)
    if raw in (None, ""):
        raw = cfg.get("max_power_w")
    return _watts(raw)


def describe(intent, power_w, cfg):
    """En mening om läget, eller None när receptet inte täcker just det här."""
    if not isinstance(cfg, dict):
        return None
    floor = _percent(cfg.get("reserve_soc"))
    ceiling = _percent(cfg.get("max_soc"))
    if intent == "auto" and power_w is None and floor is not None:
        return (f"SAJ skugga: självförbrukning, register 13895 = 2 och 13905 = {floor} %. "
                "Skriver inte.")
    if intent == "hold" and power_w is None and ceiling is not None:
        return (f"SAJ skugga: håller utan urladdning, register 13895 = 2 och 13905 = {ceiling} %. "
                "Skriver inte.")
    charge = _limit(cfg, "max_charge_w")
    asked = _watts(power_w)
    if intent == "charge" and asked is not None and asked == charge:
        return ("SAJ skugga: laddar, register 13895 = 1, 13828 = 1, 13830 = 0, "
                "13831 = 0x173B (23:59) och 13832 = 0x7F64 (hela veckan, 100 %). Skriver inte.")
    return None


def observation(recipe, state, cfg):
    """Vad samarbetsläget skulle ha valt. Styrläge och andra recept ger ingen rad."""
    try:
        if recipe != "saj_h2" or not isinstance(cfg, dict) or cfg.get("control") != "samarbete":
            return None
        if not isinstance(state, dict):
            return None
        import battery_control
        preview = dict(cfg)
        preview["control"] = "styr"
        preview["standby_for_hold"] = False
        decision = battery_control.decide(
            state, preview, frozenset({"auto", "hold", "idle", "charge", "discharge"}))
        return describe(decision.get("intent"), decision.get("power_w"), preview)
    except Exception:
        return None
