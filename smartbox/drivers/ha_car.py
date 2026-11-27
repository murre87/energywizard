"""Bilens klimat via Home Assistant (steg 5b av uppdelningen). Förut låg koden i homeassistant.py."""
import requests

from drivers.host import homeassistant as ha

CLIMATE_TIMEOUT_S = 60       # #190: HA väcker bilen och svarar först när den tagit emot kommandot (15-40 s)


def refresh_entity(entity_id: str, button: str | None = None) -> bool:
    """Ber Home Assistant läsa om en entitet nu (homeassistant.update_entity), eller trycker bilens uppdateringsknapp.
    Används när ett läge kan vara gammalt, t.ex. en sovande Teslas klimat (2026-11-07)."""
    try:
        if button:
            ha.post_service("button/press", {"entity_id": button}, CLIMATE_TIMEOUT_S)
        else:
            ha.post_service("homeassistant/update_entity", {"entity_id": entity_id}, CLIMATE_TIMEOUT_S)
        return True
    except Exception as e:
        print(f"ℹ️ Kunde inte läsa om {entity_id}: {e}")
        return False


def set_climate(entity_id: str, hvac_mode: str, temperature: float = None):
    """Startar eller stoppar klimatanläggningen i bilen. #190 (Lars): HA svarar först när bilen vaknat och tagit emot
    kommandot - tidsgränsen är 60 s, och blir det ändå tidsgräns räknas kommandot som lyckat om entiteten står på
    önskat läge (förut ett falskt fel fast värmen startade)."""
    try:
        try:
            ha.post_service("climate/set_hvac_mode", {"entity_id": entity_id, "hvac_mode": hvac_mode}, CLIMATE_TIMEOUT_S)
        except requests.exceptions.Timeout:
            if ha._climate_now(entity_id) != hvac_mode:
                raise
            print(f"ℹ️ Klimat: {entity_id} svarade sent men står på {hvac_mode}.")
        if temperature is not None and hvac_mode != "off":
            try:
                ha.post_service("climate/set_temperature", {"entity_id": entity_id, "temperature": temperature}, CLIMATE_TIMEOUT_S)
            except requests.exceptions.Timeout:
                print(f"ℹ️ Klimat: {entity_id} svarade inte på temperaturen i tid - läget är satt.")
        print(f"🚗 Klimat: {entity_id} satt till {hvac_mode} ({temperature}°C)")
        return True
    except Exception as e:
        ha.report_failure(f"Fel vid inställning av bilklimat: {e}", e)
        return False
