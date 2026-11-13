"""control_alerts.py - enheter som inte gör som EnergyWizard säger, för appen och webben (samma text i båda).

Motorn skriver lägena i overrides-tabellen:
  battery_follow   "ok" eller {"status": "not_following", "text": ...}            (battery_follow.py)
  ev_hold          "ok" eller {"<bil>": "förklaring", ...}                         (ev_hold.py)
  ev_in_meter      "ok" eller {"text": ...}                                       (ev_in_meter.py)
"""
import json


def _j(raw):
    if not raw or raw == "ok":
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def build(ov: dict, car_names: dict | None = None) -> list:
    out = []
    balance = _j(ov.get("battery_balance"))
    if isinstance(balance, dict) and balance.get("text"):
        out.append({"device": "Husbatteriet", "title": "Balansering", "text": balance["text"], "hint": "", "level": "info"})
    d = _j(ov.get("battery_follow"))
    if isinstance(d, dict) and d.get("status") == "not_following":
        out.append({"device": "Husbatteriet", "title": "Följer inte", "text": d.get("text") or "",
                    "hint": "Batteriet har inte sagt varför. Kolla dess app eller display."})
    d = _j(ov.get("ev_in_meter"))
    if isinstance(d, dict) and d.get("text"):
        out.append({"device": "Elmätaren", "title": "Ser inte elbilen", "text": d["text"],
                    "hint": "Upptäckt ur historiken (ev_in_meter.py). Kollas igen varje dygn.", "level": "info"})
    d = _j(ov.get("ev_hold"))
    if isinstance(d, dict):
        for car, txt in d.items():
            name = (car_names or {}).get(car) or str(car).capitalize()
            out.append({"device": name, "title": "Laddar långsammare än planen", "text": str(txt),
                        "hint": "Inget fel i EnergyWizard. Håller det i sig blir bilen klar senare än planerat.", "level": "info"})
    return out
