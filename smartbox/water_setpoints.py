"""Varmvattnets start- och stoppvärden till värmepumpen.

Drivrutinen avgör vad stoppvärdet betyder (attributet WATER_START_ONLY):

- För de flesta pumpar (HeishaMon, ThermIQ, NIBE, myUplink) är stoppet laddningens mål och
  ofta den enda spärren: dyrt -> stopp 40, start 35, precis som före 1.2.74.
- Thermia via Husdata (WATER_START_ONLY = True): kompressorns varmvattenladdning stoppar vid
  pressostatens maxtryck, inte vid en inställd temperatur (Thermias manual VUGFD207, 3.5).
  Registret 0208 "Warm Water stop temp" tog inte emot 40 (visade 60, mätt 2026-11-13) och styr
  troligen elpatronens toppvärmning. Det enda som styr när en ren varmvattenladdning startar är
  startvärdet (0212), så bara det skrivs och stoppet lämnas som installatören satt det.

Efter skrivningen läses värdena tillbaka när drivrutinen kan det. Fäster de inte görs
nya försök nästa kvart, högst MAX_TRIES gånger per målvärde, med en varning i loggen."""

MAX_TRIES = 3
TOL = 0.6  # °C; registren har tiondelar och vissa pumpar avrundar till hela grader


def plan(target, start_only=False):
    """(stopp, start) i °C för gpm:s varmvattenmål. stopp = None betyder: skrivs inte."""
    target = float(target)
    return (None if start_only else target), target - 5.0


def _close(got, want):
    return got is not None and abs(got - want) <= TOL


class WaterSetpoints:
    def __init__(self):
        self.done = None    # målvärdet som skrivits och bekräftats (eller inte kan kontrolleras)
        self.tries = {}     # målvärde -> antal misslyckade försök

    def reset(self):
        self.done = None
        self.tries = {}

    def apply(self, driver, target, sleep=None):
        """Skriver om målet ändrats. Returnerar True när värdena är på plats."""
        if target is None:
            return False
        stop, start = plan(target, bool(getattr(driver, "WATER_START_ONLY", False)))
        key = (stop, start)
        if self.done == key:
            return True
        if key not in self.tries:               # nytt mål: räkna försöken från noll igen
            self.tries = {key: 0}
        n = self.tries[key]
        if n >= MAX_TRIES:
            return False
        if stop is not None:
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
        if _close(r_start, start) and (stop is None or _close(r_stop, stop)):
            self.done = key
            self.tries.pop(key, None)
            return True
        self.tries[key] = n + 1
        if stop is None:
            what, shows = f"start {start:.0f} °C", f"pumpen visar start {_fmt(r_start)} °C"
        else:
            what = f"stopp {stop:.0f} °C och start {start:.0f} °C"
            shows = f"pumpen visar stopp {_fmt(r_stop)} °C och start {_fmt(r_start)} °C"
        if n + 1 >= MAX_TRIES:
            print(f"⚠️ Varmvatten: {what} fäster inte, {shows}. Slutar försöka tills målet ändras.")
        else:
            print(f"⚠️ Varmvatten: {what} fäste inte, {shows}. Försöker igen nästa kvart.")
        return False


def _fmt(v):
    return "?" if v is None else f"{v:.0f}"
