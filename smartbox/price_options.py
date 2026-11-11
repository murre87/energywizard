"""Validated optional fixed-price and HDO settings; absent fields preserve old clients."""
import math
import re


def extended_price_options(body):
    result = {}
    for field in ("buy_mode", "sell_mode"):
        if field in body:
            if body[field] not in (("spot", "fixed", "hdo") if field == "buy_mode" else ("spot", "fixed")):
                raise ValueError(f"Ogiltigt värde: {field}")
            result["price_" + field] = body[field]
    for field in ("buy_fixed", "sell_fixed", "distribution_nt", "distribution_vt", "buy_nt", "buy_vt"):
        if field in body:
            if body[field] in (None, ""):
                result["price_" + field] = None
                continue
            try:
                value = float(str(body[field]).replace(",", "."))
            except (ValueError, TypeError):
                raise ValueError(f"Ogiltigt värde: {field}") from None
            if not math.isfinite(value) or not (-100 <= value <= 1000):
                raise ValueError(f"Ogiltigt värde: {field}")
            if field.startswith("distribution_") and value < 0:
                raise ValueError(f"Ogiltigt värde: {field}")
            result["price_" + field] = value
    if "hdo_entity" in body:
        entity = str(body["hdo_entity"] or "").strip()
        if entity and not re.fullmatch(r"sensor\.[a-z0-9_]+", entity):
            raise ValueError("Ogiltig entitet för HDO-schema")
        result["price_hdo_entity"] = entity or None
    for side in ("buy", "sell"):
        if body.get(side + "_mode") == "fixed" and result.get("price_" + side + "_fixed") is None:
            raise ValueError("Ange ett fast pris när fast avtal är valt")
    if "hdo_price_source" in body:
        if body["hdo_price_source"] not in ("manual", "ha"):
            raise ValueError("Ogiltig priskälla för HDO")
        result["price_hdo_price_source"] = body["hdo_price_source"]
    if body.get("buy_mode") == "hdo":
        if body.get("country") != "CZ" or not result.get("price_hdo_entity"):
            raise ValueError("Välj Tjeckien och ett HDO-schema för NT/VT-priser")
        if body.get("hdo_price_source", "manual") == "manual" and any(result.get("price_buy_" + tariff) is None for tariff in ("nt", "vt")):
            raise ValueError("Ange båda slutpriserna för NT och VT")
    elif body.get("country") in (None, "CZ") and result.get("price_hdo_entity") and any(result.get("price_distribution_" + tariff) is None for tariff in ("nt", "vt")):
        raise ValueError("Ange båda distributionsavgifterna när HDO används")
    return result


def validate_result(current, updates):
    """Validate the complete effective configuration after a partial update."""
    c = dict(current)
    c.update({key.removeprefix("price_"): value for key, value in updates.items() if key.startswith("price_")})
    for side in ("buy", "sell"):
        if c.get(side + "_mode") == "fixed" and c.get(side + "_fixed") is None:
            raise ValueError("Ange ett fast pris när fast avtal är valt")
    if c.get("country") == "CZ" and c.get("buy_mode") == "hdo":
        if not c.get("hdo_entity") or any(c.get("buy_" + tariff) is None for tariff in ("nt", "vt")):
            raise ValueError("Ange båda slutpriserna för NT och VT")
    elif c.get("country") == "CZ" and c.get("hdo_entity"):
        if any(c.get("distribution_" + tariff) is None for tariff in ("nt", "vt")):
            raise ValueError("Ange båda distributionsavgifterna när HDO används")
