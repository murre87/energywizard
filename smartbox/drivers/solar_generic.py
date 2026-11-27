"""GenericNumberSolarDriver: täcker växelriktare utan egen drivrutin, genom att läsa/
skriva entiteter husets egen HA-integration redan exponerar - exakt den väg
SolarDriver:s ABC-docstring själv föreslår ("en redan existerande HA-entitet
(number/switch) ... föredras när den finns"). Exportgräns som en vanlig
number-entitet är vanligt hos flera märken, inte bara SolarEdge.

Två former av exportgräns stöds, beroende på vad integrationen exponerar:

  export_limit_pct  number i PROCENT (0-100). T.ex. Growatt via 0xAHA/Growatt_ModbusTCP
                    ("Export Limit Power", %), Fronius-numbers i %.
  export_limit_w    number i WATT. T.ex. Sungrow via mkaiser/Sungrow-SHx-Inverter-Modbus-
                    Home-Assistant ("Export power limit", W, steg 100). Procenten från gpm.py
                    räknas om mot export_limit_max_w (ett tal i configen), annars mot
                    entitetens egen 'max'-attribut. Okänt max = ingen strypning (False),
                    hellre det än att gissa fram en wattsiffra.

  export_limit_switch  valfri switch som måste vara PÅ för att gränsen ska gälla (Sungrows
                    "Export power limit"-switch styr registret för gränsläget). Slås på när
                    vi stryper, av igen vid 100 %, så växelriktaren lämnas som den var.
"""
from drivers.host import homeassistant
from drivers.solar import SolarDriver


class GenericNumberSolarDriver(SolarDriver):
    """Default för växelriktare utan egen drivrutin. Effekt/dagsenergi är valfria
    sensor-entiteter; exportgräns kräver en number-entitet (procent eller watt)."""
    def __init__(self, entities: dict | None = None):
        self._e = entities or {}

    def _sum(self, ents):
        """En entitet eller en lista (eller kommaseparerat). Lista = reserv i tur och ordning (som SolarEdge-drivrutinen:
        snabb Modbus först, molnet som reserv). Med sum_inverters: true summeras listan i stället - flera
        växelriktare (roadmap 2026-11-07); en som inte svarar räknas inte, svarar ingen blir det None, inte 0."""
        if not ents:
            return None
        if isinstance(ents, str):
            ents = [e.strip() for e in ents.split(",")]
        vals = [homeassistant._get_numeric_state(e) for e in ents if isinstance(e, str) and "." in e]
        vals = [v for v in vals if isinstance(v, (int, float)) and v == v]
        if not vals:
            return None
        return sum(vals) if self._e.get("sum_inverters") else vals[0]

    def read_production(self) -> dict:
        status_e = self._e.get("status")
        return {
            "pv_power_w": self._sum(self._e.get("pv_power_w")),
            "today_kwh": self._sum(self._e.get("today_kwh")),
            "status": homeassistant._get_raw_state(status_e) if isinstance(status_e, str) and status_e else None,
        }

    def supports_curtailment(self) -> bool:
        return bool(self._e.get("export_limit_pct") or self._e.get("export_limit_w"))

    def _max_w(self):
        cfg = self._e.get("export_limit_max_w")
        if cfg is not None:
            try:
                return float(cfg)
            except (TypeError, ValueError):
                return None
        attr = homeassistant.get_attribute(self._e.get("export_limit_w"), "max")
        try:
            return float(attr) if attr is not None else None
        except (TypeError, ValueError):
            return None

    def _set_switch(self, on: bool) -> bool:
        sw = self._e.get("export_limit_switch")
        return homeassistant.set_switch(sw, on) if sw else True

    def set_export_limit_pct(self, pct: int) -> bool:
        pct = max(0, min(100, int(pct)))
        pct_e = self._e.get("export_limit_pct")
        w_e = self._e.get("export_limit_w")
        if pct_e:
            ok = homeassistant.set_number(pct_e, pct)
        elif w_e:
            max_w = self._max_w()
            if not max_w or max_w <= 0:
                print(f"⚠️ Sol: okänt max för {w_e} - sätt export_limit_max_w i house_config.yaml. Stryper inte.")
                return False
            ok = homeassistant.set_number(w_e, int(round(max_w * pct / 100.0)))
        else:
            return False
        # Gränsläget på först när gränsen är skriven (aldrig ett ögonblick med gammal låg gräns
        # aktiv), och av igen vid 100 % så växelriktaren lämnas som den var.
        return ok and self._set_switch(pct < 100)

    def get_export_limit_pct(self) -> float | None:
        pct_e = self._e.get("export_limit_pct")
        if pct_e:
            return homeassistant._get_numeric_state(pct_e)
        w_e = self._e.get("export_limit_w")
        if not w_e:
            return None
        sw = self._e.get("export_limit_switch")
        if sw and homeassistant._get_numeric_state(sw) == 0.0:
            return 100.0                     # gränsläget avslaget = ingen strypning
        w = homeassistant._get_numeric_state(w_e)
        max_w = self._max_w()
        if w is None or not max_w:
            return None
        return max(0.0, min(100.0, round(100.0 * float(w) / max_w, 1)))
