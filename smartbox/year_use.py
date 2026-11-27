"""Årets elförbrukning (#603).

Energin räknas på samma sätt som historiken: varje effektsampel gånger tiden till nästa
sampel, högst fem minuter, så ett avbrott inte blir timmar på samma effekt. En månad
utan sampel saknas. Den räknas inte som noll.

Prognosen för resten av året jämför årets färdiga månader med samma månader tidigare år.
Varje tidigare år ger ett utfall. Lägsta och högsta är spannet. Saknas en månad i ett
tidigare år hoppas det året över, i stället för att saknaden blir noll.
"""
from datetime import datetime

from sqlalchemy import text

from local_sql import local_sql

from energy_history import SWE, _HOUSE, _OK

_DT = "LEAST(COALESCE(EXTRACT(EPOCH FROM lead(timestamp) OVER (ORDER BY timestamp) - timestamp), 60), 300)"
_MONTH = "date_trunc('month', timestamp AT TIME ZONE __EW_TIMEZONE__)"      # installationens tidszon (local_sql), inte en fast
_PARTS = ("ev", "pump", "spa", "other")


def _kwh(value):
    if value is None:
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return round(number, 1)


def forecast_span(monthly, year, now):
    """Spann för hela årets förbrukning (kWh), eller None när underlaget inte räcker.

    monthly: {(år, månad): kWh} för månader som har mätning. now avgör vilken månad som
    fortfarande pågår. Skalan tas från de färdiga månader som finns både i år och i det
    tidigare året. En månad som saknas i det tidigare året gör att det året hoppas över,
    så saknaden inte blir noll. Den pågående månadens återstod är det som fattas upp till
    den skalade helamånaden, aldrig ett negativt tillägg.
    """
    now = now.astimezone(SWE)
    if now.year != year or (year, now.month) not in monthly:
        return None
    completed = [month for month in range(1, now.month) if (year, month) in monthly]
    if not completed:
        return None
    future = list(range(now.month + 1, 13))
    measured_current = monthly[(year, now.month)]
    measured_completed = sum(monthly[(year, month)] for month in completed)
    estimates = []
    for prior in sorted({y for (y, _month) in monthly if y < year}):
        if any((prior, month) not in monthly for month in completed + future):
            continue
        prior_completed = sum(monthly[(prior, month)] for month in completed)
        if prior_completed <= 0:
            continue
        scale = measured_completed / prior_completed
        prior_future = sum(monthly[(prior, month)] for month in future)
        prior_current = monthly.get((prior, now.month))
        rest = 0.0 if prior_current is None else max(0.0, prior_current * scale - measured_current)
        estimates.append(measured_completed + measured_current + prior_future * scale + rest)
    if not estimates:
        return None
    return {"low": round(min(estimates), 1), "high": round(max(estimates), 1), "years": len(estimates)}


def winters(monthly, year):
    """November–mars som slutar i year och året innan. En saknad månad är null."""
    out = []
    for end_year in (year, year - 1):
        keys = ((end_year - 1, 11), (end_year - 1, 12), (end_year, 1), (end_year, 2), (end_year, 3))
        months = [{"year": y, "month": m, "used_kwh": _kwh(monthly.get((y, m)))} for y, m in keys]
        if any(item["used_kwh"] is not None for item in months):
            out.append({"label": f"{end_year - 1}/{end_year % 100:02d}", "months": months})
    return out


def _rows(conn, sql, start, end):
    return conn.execute(text(local_sql(sql)), {"start": start, "end": end}).fetchall()


def _meter_sql():
    return f"""
        WITH s AS (
            SELECT timestamp, GREATEST({_HOUSE}, 0) AS used, GREATEST(net_power, 0) AS bought, {_DT} AS dt
            FROM sensor_log
            WHERE timestamp >= :start AND timestamp < :end AND {_OK}
        )
        SELECT {_MONTH} AS month, sum(used * dt) / 3.6e6, sum(bought * dt) / 3.6e6
        FROM s GROUP BY 1 ORDER BY 1"""


def _parts_sql():
    finite = " AND ".join(
        f"({name} IS NULL OR {name}::float8 NOT IN ('Infinity','-Infinity','NaN'))"
        for name in ("ev_w", "pump_w", "spa_w", "unexplained_w"))
    return f"""
        WITH s AS (
            SELECT timestamp, ev_w, pump_w, spa_w, unexplained_w, {_DT} AS dt
            FROM load_breakdown
            WHERE timestamp >= :start AND timestamp < :end AND {finite}
        )
        SELECT {_MONTH} AS month,
               CASE WHEN count(ev_w) = 0 THEN NULL ELSE sum(GREATEST(ev_w, 0) * dt) / 3.6e6 END,
               CASE WHEN count(pump_w) = 0 THEN NULL ELSE sum(GREATEST(pump_w, 0) * dt) / 3.6e6 END,
               CASE WHEN count(spa_w) = 0 THEN NULL ELSE sum(GREATEST(spa_w, 0) * dt) / 3.6e6 END,
               CASE WHEN count(unexplained_w) = 0 THEN NULL ELSE sum(GREATEST(unexplained_w, 0) * dt) / 3.6e6 END
        FROM s GROUP BY 1 ORDER BY 1"""


def _month_key(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        local = value.astimezone(SWE) if value.tzinfo else value.replace(tzinfo=SWE)
        return local.year, local.month
    return value.year, value.month


def assemble(meter, parts, year, now):
    """Bygger svaret ur månadsraderna. meter: (månad, använd, köpt). parts: (månad, elbil, pump, spa, övrigt)."""
    now = now.astimezone(SWE)
    used = {}
    bought = {}
    for row in meter:
        key = _month_key(row[0])
        if key is None:
            continue
        if _kwh(row[1]) is not None:
            used[key] = _kwh(row[1])
        if _kwh(row[2]) is not None:
            bought[key] = _kwh(row[2])
    part_maps = {name: {} for name in _PARTS}
    for row in parts:
        key = _month_key(row[0])
        if key is None:
            continue
        for index, name in enumerate(_PARTS):
            value = _kwh(row[index + 1])
            if value is not None:
                part_maps[name][key] = value
    months = []
    for month in range(1, 13):
        key = (year, month)
        if key not in used and key not in bought and not any(key in part_maps[name] for name in _PARTS):
            months.append({"month": month, "used_kwh": None, "bought_kwh": None,
                           **{f"{name}_kwh": None for name in _PARTS}})
            continue
        months.append({
            "month": month,
            "used_kwh": used.get(key),
            "bought_kwh": bought.get(key),
            **{f"{name}_kwh": part_maps[name].get(key) for name in _PARTS},
        })
    def year_sum(source):
        present = [source[key] for key in ((year, month) for month in range(1, 13)) if key in source]
        return round(sum(present), 1) if present else None
    years = sorted({key[0] for key in used} | {year})
    return {
        "ok": True,
        "year": year,
        "years": years,
        "used_kwh": year_sum(used),
        "bought_kwh": year_sum(bought),
        "parts": {f"{name}_kwh": year_sum(part_maps[name]) for name in _PARTS},
        "months": months,
        "forecast": forecast_span(used, year, now),
        "winters": winters(used, year),
    }


def load(conn, year, now=None):
    now = (now or datetime.now(SWE)).astimezone(SWE)
    try:
        year = int(year)
    except (TypeError, ValueError):
        year = now.year
    if year < 2000 or year > now.year:
        year = now.year
    start = datetime(max(year - 4, 2000), 1, 1, tzinfo=SWE)
    end = min(datetime(year + 1, 1, 1, tzinfo=SWE), now)
    try:
        meter = _rows(conn, _meter_sql(), start, end)
    except Exception:
        meter = []
        try:
            conn.rollback()
        except Exception:
            pass
    try:
        parts = _rows(conn, _parts_sql(), start, end)
    except Exception:
        parts = []
        try:
            conn.rollback()
        except Exception:
            pass
    return assemble(meter, parts, year, now)
