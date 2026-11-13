"""
plan_brief.py - planen framåt i klartext ("vad händer härnäst, och varför").

Bygger INTE en ny plan, den beskriver bara det motorn redan bestämt eller kommer att göra:

  - Elbilen: laddpassen ur ev_plan_slots (decisions.py:s laddplan, 15-minutersslottar),
    ihopslagna till sammanhängande pass per bil, med passets snittpris mot dygnets snitt.
  - Värmepumpen: grundläget per kvart enligt exakt samma regel som gpm.py använder -
    nordpool.calculate_day_strategy() ger dygnets prisgräns (det N:te billigaste kvarts-
    priset) och hysteres; billigt om priset <= gräns - hysteres, dyrt om >= gräns +
    hysteres, gråzonen behåller föregående läge. Det är GRUNDLÄGET: gpm.py höjer gränsen
    när huset svalnar snabbt, och högre prioriteter (komfortgolv, varmvatten, effektvakt,
    spärrtid för kompressorn) kan överstyra i stunden. Texten säger det, den lovar inte mer.

Rena funktioner utan I/O - testas i tests/test_plan_brief.py.
"""

from datetime import datetime, timedelta
import zoneinfo

SWE = zoneinfo.ZoneInfo("Europe/Stockholm")
SLOT = timedelta(minutes=15)
HORIZON = timedelta(hours=36)


def _local(ts):
    return ts.replace(tzinfo=SWE) if ts.tzinfo is None else ts.astimezone(SWE)


def _kr(v, currency="SEK", symbol="kr"):
    """Samma stil som webdashboardens fmtKrOre: under 1 kr i öre, annars kronor."""
    if v is None:
        return "–"
    return f"{round(v * 100)} öre" if currency == "SEK" and abs(v) < 1 and v != 0 else f"{_num(v, 2)} {symbol}"


def _clock(ts, now):
    ts = _local(ts)
    day = ts.date() - _local(now).date()
    prefix = "" if day.days == 0 else ("imorgon " if day.days == 1 else ts.strftime("%a ").lower())
    return f"{prefix}{ts:%H:%M}"


def _num(v, dec=1):
    """Svenskt decimalkomma, som i appen: 11,0 kW."""
    return f"{v:.{dec}f}".replace(".", ",")


def _span(start, end, now):
    if _local(start) <= _local(now):
        # Pågående: "till 24:00" (en Nu-markering visas bredvid i gränssnittet).
        e_local = _local(end)
        if e_local.hour == 0 and e_local.minute == 0 and e_local.date() > _local(now).date():
            return "till 24:00" if e_local.date() - _local(now).date() == timedelta(days=1) else "till imorgon 24:00"
        return f"till {_clock(end, now)}"
    s = _clock(start, now)
    e_local = _local(end)
    if e_local.hour == 0 and e_local.minute == 0 and e_local.date() > _local(start).date():
        # Ett pass som slutar vid midnatt slutar med sin dag: "06:00–24:00", inte "imorgon 00:00".
        if e_local.date() - _local(now).date() > timedelta(days=1):
            return f"{s}–imorgon 24:00"
        return f"{s}–24:00"
    e = _clock(end, now)
    # "imorgon 02:00–imorgon 05:00" -> "imorgon 02:00–05:00"
    if s.split(" ")[0] == e.split(" ")[0] and " " in s:
        e = e.split(" ", 1)[1]
    return f"{s}–{e}"


def _price_lookup(prices):
    """prices = [(start, pris)] -> funktion som ger priset för en tidpunkt (None utanför)."""
    pts = sorted((_local(t), float(p)) for t, p in prices if p is not None)

    def at(ts):
        ts = _local(ts)
        best = None
        for i, (t, p) in enumerate(pts):
            end = pts[i + 1][0] if i + 1 < len(pts) else t + SLOT
            if t <= ts < end:
                best = p
                break
        return best
    return pts, at


def ev_items(ev_rows, prices, now, currency="SEK", symbol="kr"):
    """Sammanhängande laddpass per bil som inte redan är slut."""
    now = _local(now)
    pts, price_at = _price_lookup(prices)
    day_avg = {}
    for t, p in pts:
        day_avg.setdefault(t.date(), []).append(p)
    day_avg = {d: sum(v) / len(v) for d, v in day_avg.items()}

    per_car = {}
    for car, t_slot, kw in ev_rows or []:
        if t_slot is None or kw is None or float(kw) <= 0.05:
            continue
        per_car.setdefault(str(car), []).append((_local(t_slot), float(kw)))

    items = []
    for car, slots in per_car.items():
        slots.sort()
        blocks = []
        for start, kw in slots:
            if blocks and blocks[-1]["end"] == start:
                blocks[-1]["end"] = start + SLOT
                blocks[-1]["slots"].append((start, kw))
            else:
                blocks.append({"start": start, "end": start + SLOT, "slots": [(start, kw)]})
        for b in blocks:
            if b["end"] <= now:
                continue
            kwh = sum(kw * SLOT.total_seconds() / 3600 for _, kw in b["slots"])
            kw_max = max(kw for _, kw in b["slots"])
            ps = [(price_at(s), kw) for s, kw in b["slots"]]
            ps = [(p, kw) for p, kw in ps if p is not None]
            avg = sum(p * kw for p, kw in ps) / sum(kw for _, kw in ps) if ps else None
            davg = day_avg.get(b["start"].date())
            why = f"snittpris {_kr(avg, currency, symbol)}/kWh" if avg is not None else ""
            if avg is not None and davg is not None:
                why += f" (dygnets snitt {_kr(davg, currency, symbol)})"
            items.append({
                "kind": "ev", "car": car, "start": b["start"].isoformat(), "end": b["end"].isoformat(),
                "when": _span(max(b["start"], now), b["end"], now),
                "title": f"🚗 {car.capitalize()} laddar",
                "detail": " · ".join(x for x in (f"{_num(kw_max)} kW", f"{_num(kwh)} kWh", why) if x),
                "active": b["start"] <= now < b["end"],
            })
    return items


def heat_items(prices, now, strategy_fn, cheap_hours_count=8, current_mode=None, currency="SEK", symbol="kr"):
    """Värmepumpens grundläge per sammanhängande period, enligt gpm.py:s prisregel."""
    now = _local(now)
    pts, _ = _price_lookup(prices)
    if not pts:
        return []
    by_day = {}
    for t, p in pts:
        by_day.setdefault(t.date(), []).append((t, p))

    items = []
    cur = None          # pågående period - fortsätter över midnatt om läget är detsamma
    mode = current_mode if current_mode in ("CHEAP", "EXPENSIVE") else None
    for day in sorted(by_day):
        day_pts = by_day[day]
        strat = strategy_fn([p for _, p in day_pts], cheap_hours_count)
        day_end = day_pts[-1][0] + SLOT
        if day_end <= now or day_pts[0][0] > now + HORIZON:
            continue
        if strat.get("mode") == "comfort":
            start = max(day_pts[0][0], now)
            items.append({"kind": "heat", "mode": "COMFORT", "start": start.isoformat(), "end": day_end.isoformat(),
                          "when": _span(start, day_end, now), "title": "😌 Jämn komfort hela dygnet",
                          "detail": "Billig dag med liten prisskillnad - ingen idé att flytta värmen.",
                          "active": start <= now < day_end})
            mode, cur = None, None
            continue
        lim, hyst = strat.get("dynamic_limit"), float(strat.get("hysteresis") or 0)
        if lim is None:
            continue
        for i, (t, p) in enumerate(day_pts):
            if p <= lim - hyst:
                mode = "CHEAP"
            elif p >= lim + hyst:
                mode = "EXPENSIVE"
            elif mode is None:
                mode = "CHEAP" if p <= lim else "EXPENSIVE"
            end = day_pts[i + 1][0] if i + 1 < len(day_pts) else t + SLOT
            if end <= now:
                continue
            if cur and cur["mode"] == mode and cur["end"] == t:
                cur["end"] = end
            else:
                cur = {"mode": mode, "start": max(t, now), "end": end}
                items.append(cur)
        for it in items:
            if "kind" in it:
                continue
            it["kind"] = "heat"
            cheap = it["mode"] == "CHEAP"
            it["title"] = "🔥 Huset laddas med värme" if cheap else "🌡️ Värmen sänks"
            it["detail"] = (f"Bland dygnets {cheap_hours_count} billigaste timmar (gräns {_kr(lim, currency, symbol)}/kWh)." if cheap
                            else f"Elpriset över dagens gräns {_kr(lim, currency, symbol)}/kWh - huset lever på lagrad värme.")
    for it in items:
        if isinstance(it.get("start"), datetime):
            s, e = it["start"], it["end"]
            it["active"] = s <= now < e
            it["when"] = _span(s, e, now)
            it["start"], it["end"] = s.isoformat(), e.isoformat()
    return items


_BAT = {"charge": "🔋 Batteriet laddar", "discharge": "🔋 Batteriet laddar ur", "hold": "🔋 Batteriet sparas",
        "idle": "🔋 Batteriet vilar", "export": "🔋 Batteriet laddar ur och säljer"}
EXPORT_KW = 0.1        # planerat nätflöde under -0,1 kW medan batteriet laddar ur = säljer överskottet (Anders på Discord)


def battery_items(rows, now, currency="SEK", symbol="kr"):
    """rows = [(t_slot, action, soc_pct, spot[, battery_kw[, grid_kw]])] ur battery_plan_slots. Urladdning när planen
    säljer till nätet (grid_kw < -EXPORT_KW) blir egna pass med action "export" - egen färg i gränssnittet. (soc_pct = nivån efter
    kvarten). Sammanhängande pass utom auto. Varje pass får också nivån före/efter, energin och det högsta
    (urladdning) eller lägsta (laddning) spotpriset - för planklockans kompakta rad (önskemål från HannesB)."""
    now = _local(now)
    blocks, prev_soc = [], None
    for r in sorted(rows or [], key=lambda r: r[0]):
        t, action, soc, spot = r[:4]
        kw = r[4] if len(r) > 4 else None
        grid = r[5] if len(r) > 5 else None
        balance = bool(r[6]) if len(r) > 6 else False
        if action == "discharge" and grid is not None and float(grid) < -EXPORT_KW:
            action = "export"
        t = _local(t)
        if blocks and blocks[-1]["action"] == action and blocks[-1]["end"] == t and blocks[-1]["balance"] == balance:
            b = blocks[-1]
            b["end"] = t + SLOT
            b["soc"] = soc
            b["spots"].append(spot)
            b["kws"].append(kw)
        else:
            blocks.append({"action": action, "start": t, "end": t + SLOT, "soc": soc, "soc_from": prev_soc,
                           "spots": [spot], "kws": [kw], "balance": balance})
        prev_soc = soc
    out = []
    for b in blocks:
        if (b["action"] not in _BAT and not b["balance"]) or b["end"] <= now:
            continue
        sp = [float(x) for x in b["spots"] if x is not None]
        avg = sum(sp) / len(sp) if sp else None
        kws = [abs(float(x)) for x in b["kws"] if x is not None]
        kwh = round(sum(kws) * SLOT.total_seconds() / 3600, 1) if kws else None
        peak = (max(sp) if b["action"] in ("discharge", "export") else min(sp) if b["action"] == "charge" else None) if sp else None
        parts = [f"till {float(b['soc']):.0f} %" if b["soc"] is not None else ""]
        if avg is not None:
            parts.append(f"spotpris {_kr(avg, currency, symbol)}/kWh")
        out.append({"kind": "battery", "action": b["action"], "start": b["start"].isoformat(), "end": b["end"].isoformat(),
                    "when": _span(max(b["start"], now), b["end"], now),
                    "title": "🔋 Batteriet balanseras" if b["balance"] else _BAT[b["action"]],
                    "detail": " · ".join(x for x in parts if x), "active": b["start"] <= now < b["end"],
                    "soc_from": None if b["soc_from"] is None else round(float(b["soc_from"])),
                    "soc_to": None if b["soc"] is None else round(float(b["soc"])),
                    "kwh": kwh if kwh else None, "price_peak": peak})
    return out


def load_battery_rows(conn):
    """Batteriplanens kvartar till battery_items (webben och appen). grid_kw finns först när motorn sparat en plan
    med den kolumnen - innan dess utan, så att planen inte försvinner under uppdateringen."""
    from sqlalchemy import text
    for cols in ("t_slot, action, soc_pct, spot, battery_kw, grid_kw, balance",
                 "t_slot, action, soc_pct, spot, battery_kw, grid_kw", "t_slot, action, soc_pct, spot, battery_kw"):
        try:
            return [tuple(r) for r in conn.execute(text(f"SELECT {cols} FROM battery_plan_slots "
                                                         "WHERE t_slot >= now() - interval '15 minutes' ORDER BY t_slot")).fetchall()]
        except Exception:          # kolumnen eller tabellen finns inte än
            conn.rollback()
    return []


def build_brief(now, prices, ev_rows, strategy_fn, cheap_hours_count=8, current_mode=None, battery_rows=None, currency="SEK", symbol="kr"):
    """{'headline': str, 'items': [...], 'note': str}. items sorterade på starttid, de som
    pågår nu markerade active=True."""
    now = _local(now)
    items = ev_items(ev_rows, prices, now, currency, symbol) + heat_items(prices, now, strategy_fn, cheap_hours_count, current_mode, currency, symbol) \
        + battery_items(battery_rows, now, currency, symbol)
    items = [i for i in items if datetime.fromisoformat(i["start"]) < now + HORIZON]
    items.sort(key=lambda i: (i["start"], i["kind"] != "ev"))

    def _t(i):
        return i["title"].split(" ", 1)[1] if " " in i["title"] else i["title"]

    active = [i for i in items if i["active"]]
    upcoming = [i for i in items if not i["active"]]
    if active and upcoming:
        headline = f"Just nu: {_t(active[0])}. Härnäst {upcoming[0]['when']}: {_t(upcoming[0])}."
    elif active:
        headline = f"Just nu: {_t(active[0])} ({active[0]['when']})."
    elif upcoming:
        headline = f"Härnäst {upcoming[0]['when']}: {_t(upcoming[0])}."
    else:
        headline = "Inget planerat än - priserna för imorgon kommer vid 13-tiden."
    return {
        "headline": headline,
        "items": items,
        "note": ("Värmepumpens perioder är grundläget enligt elpriset. Vid kyla flyttas gränsen uppåt, "
                 "och komfortgolv, varmvatten och effektvakten går alltid före."),
    }
