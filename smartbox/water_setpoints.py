"""Varmvattnets start- och stoppvärden till värmepumpen.

Spärren mot dyr varmvattenladdning ligger i STARTvärdet: en låg start gör att pumpen inte
börjar en ren varmvattenladdning förrän tanken verkligen är kall. STOPPvärdet sänks därför
aldrig under normalnivån. Thermia via Husdata tar inte emot stopp 40 (registret visade 60
efter skrivningen, mätt 2026-11-13), och en laddning som ändå startar under en dyr timme
körde då ända upp till 60 °C.

Efter skrivningen läses värdena tillbaka när drivrutinen kan det. Fäster de inte görs
nya försök nästa kvart, högst MAX_TRIES gånger per målvärde, med en varning i loggen."""

MAX_TRIES = 3
TOL = 0.6  # °C; registren har tiondelar och vissa pumpar avrundar till hela grader


def plan(target, normal):
    """(stopp, start) i °C för gpm:s varmvattenmål."""
    target = float(target)
    return max(target, float(normal)), target - 5.0


class WaterSetpoints:
    def __init__(self):
        self.done = None    # målvärdet som skrivits och bekräftats (eller inte kan kontrolleras)
        self.tries = {}     # målvärde -> antal misslyckade försök

    def reset(self):
        self.done = None
        self.tries = {}

    def apply(self, driver, target, normal, sleep=None):
        """Skriver om målet ändrats. Returnerar True när värdena är på plats."""
        if target is None:
            return False
        stop, start = plan(target, normal)
        key = (stop, start)
        if self.done == key:
            return True
        if key not in self.tries:               # nytt mål: räkna försöken från noll igen
            self.tries = {key: 0}
        n = self.tries[key]
        if n >= MAX_TRIES:
            return False
        driver.set_water_stop_temp(stop)
        if sleep:
            sleep(2)
        driver.set_water_start_temp(start)
        reader = getattr(driver, "read_water_setpoints", None)
        got = reader() if callable(reader) else None
        if got is None:                         # kan inte läsas tillbaka (annan pump, skuggläge): som förut
            self.done = key
            self.tries.pop(key, None)
            return True
        r_stop, r_start = got
        if (r_stop is not None and abs(r_stop - stop) <= TOL
                and r_start is not None and abs(r_start - start) <= TOL):
            self.done = key
            self.tries.pop(key, None)
            return True
        shows = f"pumpen visar stopp {_fmt(r_stop)} °C och start {_fmt(r_start)} °C"
        self.tries[key] = n + 1
        if n + 1 >= MAX_TRIES:
            print(f"⚠️ Varmvatten: stopp {stop:.0f} °C och start {start:.0f} °C fäster inte, {shows}. Slutar försöka tills målet ändras.")
        else:
            print(f"⚠️ Varmvatten: stopp {stop:.0f} °C och start {start:.0f} °C fäste inte, {shows}. Försöker igen nästa kvart.")
        return False


def _fmt(v):
    return "?" if v is None else f"{v:.0f}"
