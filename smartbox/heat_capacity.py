"""heat_capacity.py - högsta börvärde som värmepumpen klarar utan tillsats, lärt ur husets egen logg (Emil 2026-11-27).

Problem: rumsåterkopplingen (heat_ml) väljer börvärde efter hur huset reagerar, men vet inte hur mycket pumpen orkar leverera.
Över en viss nivå ger ett högre börvärde ingen mer värme från kompressorn (framledningen ligger kvar vid ca 44 °C hos Emil),
bara en större skillnad mot den beräknade framledningen. Gradminuterna är summan av just den skillnaden (framledning minus
beräknad framledning, per minut) och rasar mot -1190, där pumpen kopplar in elpatronen. Mätt hos Emil (30 dygn, -5 till +2 °C
ute): börvärde 19 ger 0 % tillsats, 21 ger 4 %, 22 ger 10 %, 23 ger 82 %.

Metod: per utetemperatur och heltalsbörvärde, snittet av (beräknad framledning - verklig framledning) över minuter med
kompressorn igång och husvärme (ej varmvattenladdning). Taket är högsta börvärdet där snittet ligger under MAX_OFFSET_C,
och där alla lägre börvärden också gör det, med minst MIN_MIN minuters data. Skillnaden är orsaken till att gradminuterna
rasar, så den är bättre än att räkna djupa gradminuter (de släpar efter tidigare höga börvärden). Lärs om en gång per dygn,
så taket följer årstiden och husets verkliga prestanda. Saknas data för utetemperaturen ger det inget tak (None).
"""
import time

MAX_OFFSET_C = 2.0          # snittet av (beräknad - verklig framledning) som pumpen klarar över tid
MIN_MIN = 60                # minuter per börvärdesnivå för att den ska räknas
WIDTH_C = 2.5               # utetemperaturer inom +-2,5 °C räknas ihop
MIN_USEFUL_SP = 17.0        # ett tak under detta är opålitligt (för lite data), ge inget tak
REFIT_S = 24 * 3600

_cache = {"at": 0.0, "table": None}


def cap_from_table(table, outdoor):
    """table: {(utegrad, börvärde): (minuter, summa av beräknad-verklig framledning)} med utegrad som heltal. Högsta börvärde
    utan tillsatsrisk vid utetemperaturen, eller None."""
    if outdoor is None:
        return None
    per_sp = {}
    for (oc, sp), (n, off) in table.items():
        if abs(oc - outdoor) <= WIDTH_C:
            a = per_sp.setdefault(sp, [0, 0])
            a[0] += n
            a[1] += off
    best = None
    for sp in sorted(per_sp):
        n, off = per_sp[sp]
        if n < MIN_MIN:
            continue                                    # för lite data på den nivån: räkna den inte som godkänd
        if off / n > MAX_OFFSET_C:
            break
        best = sp
    return float(best) if best is not None and best >= MIN_USEFUL_SP else None


def load_table(get_db, days=30):
    """{(utegrad, börvärde): (minuter, summa av beräknad minus verklig framledning)} ur sensor_log."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT round(outdoor_temp)::int, round(room_temp_setpoint)::int, count(*),
                           sum(calc_forward_temp - forward_temp)
                    FROM sensor_log
                    WHERE timestamp > now() - make_interval(days => %s) AND compressor_running = 1
                      AND coalesce(hotwater_valve, 0) = 0 AND outdoor_temp IS NOT NULL
                      AND calc_forward_temp IS NOT NULL AND forward_temp IS NOT NULL
                      AND room_temp_setpoint BETWEEN 15 AND 25
                    GROUP BY 1, 2""", (days,))
                return {(int(o), int(s)): (int(n), float(d or 0)) for o, s, n, d in cur.fetchall()}
    except Exception:
        return None


def cap(get_db, outdoor, now_s=None):
    """Högsta börvärde utan tillsats vid utetemperaturen (cachat ett dygn), eller None."""
    now_s = time.time() if now_s is None else now_s
    if _cache["table"] is None or now_s - _cache["at"] > REFIT_S:
        t = load_table(get_db)
        _cache.update(at=now_s, table=t if t is not None else (_cache["table"] or {}))
    return cap_from_table(_cache["table"], outdoor)
