"""Varmvattnets start- och stoppvärden till värmepumpen.

Drivrutinen avgör vad stoppvärdet betyder (attributet WATER_START_ONLY):

- För de flesta pumpar (HeishaMon, ThermIQ, NIBE, myUplink) är stoppet laddningens mål och
  ofta den enda spärren: dyrt -> stopp 40, start 35, precis som före 1.2.74.
- Thermia via Husdata (WATER_START_ONLY = True): kompressorns varmvattenladdning stoppar vid
  pressostatens maxtryck, inte vid en inställd temperatur (Thermias manual VUGFD207, 3.5).
  Registret 0208 "Warm Water stop temp" är TOPH. STOP, legionellakörningens stopptemperatur
  (elpatronen), och tog inte emot 40 (tillåtet 50-65). Det enda som styr när en ren
  varmvattenladdning startar är startvärdet (0212), så bara det skrivs och stoppet lämnas som
  installatören satt det.

Thermias manual (installatörsmenyn SERVICE -> HOT WATER): START 30-55 °C, TOPH. STOP (det som
Husdata kallar "Warm Water stop temp", stopptemperaturen för legionellakörningen) 60 °C från
fabrik, 50-65 °C. Drivrutinen anger startens gränser (WATER_START_RANGE) och värdet hålls inom dem.

Värdena kontrolleras vid NÄSTA kvart, inte direkt efter skrivningen: Husdata-gatewayen visar
ett nyskrivet värde först efter ungefär en halv minut (mätt 2026-11-13). Fäster de inte skrivs
de igen, högst MAX_TRIES gånger per målvärde, med en varning i loggen."""

MAX_TRIES = 3
TOL = 0.6  # °C; registren har tiondelar och vissa pumpar avrundar till hela grader


def plan(target, start_only=False, start_range=None):
    """(stopp, start) i °C för gpm:s varmvattenmål. stopp = None betyder: skrivs inte."""
    target = float(target)
    start = target - 5.0
    if start_range:
        start = min(max(start, float(start_range[0])), float(start_range[1]))
    return (None if start_only else target), start


def _close(got, want):
    return got is not None and abs(got - want) <= TOL


class WaterSetpoints:
    def __init__(self):
        self.done = None    # målvärdet som skrivits och bekräftats (eller inte kan kontrolleras)
        self.sent = None    # målvärdet som skrivits men ännu inte kontrollerats
        self.tries = {}     # målvärde -> antal misslyckade försök

    def reset(self):
        self.done = None
        self.sent = None
        self.tries = {}

    def apply(self, driver, target, sleep=None):
        """Anropas varje kvart. Skriver när målet ändrats och kontrollerar förra skrivningen.
        Returnerar True när värdena är bekräftade (eller inte kan kontrolleras)."""
        if target is None:
            return False
        stop, start = plan(target, bool(getattr(driver, "WATER_START_ONLY", False)),
                           getattr(driver, "WATER_START_RANGE", None))
        key = (stop, start)
        if self.done == key:
            return True
        if key not in self.tries:               # nytt mål: räkna försöken från noll igen
            self.tries = {key: 0}
            self.sent = None
        reader = getattr(driver, "read_water_setpoints", None)
        if self.sent == key and callable(reader):   # skrevs förra kvarten: stämmer det nu?
            got = reader()
            if got is None:                     # gick inte att läsa just nu: lita på skrivningen
                return self._ok(key)
            r_stop, r_start = got
            if _close(r_start, start) and (stop is None or _close(r_stop, stop)):
                return self._ok(key)
            n = self.tries[key] = self.tries[key] + 1
            if stop is None:
                what, shows = f"start {start:.0f} °C", f"pumpen visar start {_fmt(r_start)} °C"
            else:
                what = f"stopp {stop:.0f} °C och start {start:.0f} °C"
                shows = f"pumpen visar stopp {_fmt(r_stop)} °C och start {_fmt(r_start)} °C"
            if n >= MAX_TRIES:
                print(f"⚠️ Varmvatten: {what} fäster inte, {shows}. Slutar försöka tills målet ändras.")
                self.sent = None
                return False
            print(f"⚠️ Varmvatten: {what} fäste inte, {shows}. Försöker igen nästa kvart.")
        elif self.tries[key] >= MAX_TRIES:
            return False
        if stop is not None:
            driver.set_water_stop_temp(stop)
            if sleep:
                sleep(2)
        driver.set_water_start_temp(start)
        if not callable(reader):                # kan inte läsas tillbaka (annan pump): som förut
            return self._ok(key)
        self.sent = key
        return False

    def _ok(self, key):
        self.done, self.sent = key, None
        self.tries.pop(key, None)
        return True


def _fmt(v):
    return "?" if v is None else f"{v:.0f}"
