"""health.py – Enkel övervakning av sensorer och länken till Home Assistant (rena funktioner, lätta att testa).

SensorWatch: varnar när en sensor som nyligen fungerat slutat rapportera (och när den kommer tillbaka).
LinkWatch:   noterar när Home Assistant varit onåbar en längre stund och ger en sammanfattning när den är tillbaka.
             (En notis MEDAN HA är nere kan inte gå via HA:s mobilapp; det täcks av den externa ha_watchdog.sh.)

Bakgrund: 2026-09-17 försvann Zigbee-sensorn och de tre Matter-sensorerna utan att någon märkte det på dagar.
"""
from datetime import timedelta


class SensorWatch:
    def __init__(self, grace_min=30):
        self.grace = timedelta(minutes=grace_min)
        self.last_seen = {}
        self.alerted = set()

    def seed(self, name, ts):
        """Sätter senast kända tidpunkt (t.ex. från databasen vid start) utan att räknas som live-värde."""
        if ts is not None:
            self.last_seen[name] = ts

    def update(self, readings, now):
        """readings = {namn: värde eller None}. Returnerar händelser [("lost"|"back", namn, tid_sedan_senast)]."""
        events = []
        for name, val in readings.items():
            if val is not None:
                if name in self.alerted:
                    self.alerted.discard(name)
                    events.append(("back", name, now - self.last_seen.get(name, now)))
                self.last_seen[name] = now
            else:
                ts = self.last_seen.get(name)
                if ts is not None and (now - ts) > self.grace and name not in self.alerted:
                    self.alerted.add(name)
                    events.append(("lost", name, now - ts))
        return events


class LinkWatch:
    def __init__(self, min_outage_min=5):
        self.min_outage = timedelta(minutes=min_outage_min)
        self.down_since = None

    def update(self, ok, now):
        """ok = True om HA svarade nu. Returnerar ("recovered", varaktighet, från) när HA kommit tillbaka efter
        ett längre avbrott, annars None."""
        if ok:
            ev = None
            if self.down_since is not None and (now - self.down_since) >= self.min_outage:
                ev = ("recovered", now - self.down_since, self.down_since)
            self.down_since = None
            return ev
        if self.down_since is None:
            self.down_since = now
        return None


def fmt_duration(td):
    mins = int(td.total_seconds() // 60)
    if mins < 90:
        return f"{mins} min"
    h, m = divmod(mins, 60)
    if h < 48:
        return f"{h} h {m} min"
    return f"{h // 24} dygn"


def load_check(total_w, known_w, net_w, phase_currents, pv_frozen=False, volt=230.0):
    """Oförklarad last med extra kontroll från FASSTRÖMMARNA (Tibber, oberoende av solsensorn).

    Nätimporten är alltid verklig förbrukning, så husets last >= brutto-importen (summan av de POSITIVA fasströmmarna
    x spänning). Det ger en solfri nedre gräns för oförklarad last:  grid_lb = max(0, brutto-import - känd last).
    Den solberoende siffran (pv_based) kan bli helt fel om solvärdet är gammalt/fastfruset (2026-09-20: 6865 W kvar
    från moln-API:t medan verklig sol var ~220 W -> falsk "6,6 kW oförklarat"). Därför:
      - är solvärdet fastfruset används bara fas-gränsen som oförklarad last
      - en notis kräver att fasströmmarna bekräftar minst 1 kW oförklarad nätimport
    Returnerar dict med gross_import_w, grid_lb_w, pv_based_w, unexplained_w, alert.
    """
    gross = sum(max(0.0, (a or 0.0)) for a in phase_currents) * volt
    grid_lb = max(0.0, gross - known_w)
    pv_based = max(0.0, total_w - known_w) if net_w > 0 else 0.0
    unexplained = grid_lb if pv_frozen else pv_based
    alert = unexplained > 2000.0 and net_w > 0 and grid_lb >= 1000.0
    return {"gross_import_w": gross, "grid_lb_w": grid_lb, "pv_based_w": pv_based, "unexplained_w": unexplained, "alert": alert}
