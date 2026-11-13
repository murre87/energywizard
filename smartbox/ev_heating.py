"""ev_heating.py - temperaturberoende baslast för laddplaneringen (ev_planning.heating_adjustment).

Fysiken: värme är en last som växer när det blir kallare. Det som blir kvar åt bilen i en 15-minutersruta är
(effekttak - husets last), så kallare väder -> större hus-last -> mindre effekt åt bilen -> fler rutor behövs.
Energin bilen ska ha ändras inte; det är effekten som räcker mindre långt.

Modell (graddagsmodell, vanlig för värmelast):
    värmelast(T)  = k * max(0, balanstemp - T)                       [kW]
    baslast(ruta) = inlärd profil(ruta) + k * (GD(prognos-T) - GD_ref)
där GD(T) = max(0, balanstemp - T) ("graddagar", här per timme) och GD_ref = medel av GD över perioden den inlärda
profilen bygger på. Profilen (learning.get_base_load_profile) är 85:e percentilen av de senaste 30 dagarnas last och
innehåller redan den värme som fanns då; bara SKILLNADEN mot prognosen läggs på, så värmen inte räknas två gånger.

k (kW per grad under balanstemperaturen) lärs ur historiken: lasten per timme minus dess normala nivå vid samma
klockslag, regresserad mot motsvarande skillnad i GD. Den kan också anges för hand (kw_per_degree: <tal>).

Begränsningar att känna till: lasten är "nätimport minus loggad billaddning" (som profilen), så batteriladdning från
nätet och solproduktion bakom mätaren hamnar i k:s skattning; och värme som styrs av egna scheman följer priset, inte
bara temperaturen. Loggen skriver ut det inlärda k så att det går att bedöma.

Rena funktioner utan I/O - testas i tests/test_ev_heating.py.
"""


def heating_degrees(temp_c, balance_c):
    """Graddagar per timme: hur många grader under balanstemperaturen (aldrig negativt)."""
    return max(0.0, float(balance_c) - float(temp_c))


def _known(value):
    return value is not None and value == value          # None och NaN är okända


def hourly_frame(loads, temps):
    """Timmedel av last och utetemperatur, sammanfogade. loads: kolumnerna ts, other_kw. temps: ts, temp.
    Returnerar DataFrame med ts (timme), other_kw, temp - tom om något saknas."""
    import pandas as pd
    empty = pd.DataFrame(columns=["ts", "other_kw", "temp"])
    if loads is None or temps is None or len(loads) == 0 or len(temps) == 0:
        return empty
    a = loads.copy()
    b = temps.copy()
    a["ts"] = pd.to_datetime(a["ts"]).dt.floor("h")
    b["ts"] = pd.to_datetime(b["ts"]).dt.floor("h")
    a = a.groupby("ts", as_index=False)["other_kw"].mean()
    b = b.groupby("ts", as_index=False)["temp"].mean()
    out = pd.merge(a, b, on="ts", how="inner").dropna()
    return out.reset_index(drop=True)


def fit_heating_model(df, balance_c, min_rows=200, min_range_c=5.0):
    """Skattar k ur timdata (kolumnerna ts, other_kw, temp). Klockslagseffekten (normal last per timme på dygnet)
    plockas bort på båda sidor innan lutningen räknas. None om underlaget är för litet eller temperaturen för jämn."""
    if df is None or len(df) < min_rows:
        return None
    d = df.dropna(subset=["other_kw", "temp"]).copy()
    if len(d) < min_rows or (d["temp"].max() - d["temp"].min()) < min_range_c:
        return None
    d["gd"] = (float(balance_c) - d["temp"]).clip(lower=0.0)
    hour = d["ts"].dt.hour
    y = d["other_kw"] - d.groupby(hour)["other_kw"].transform("mean")
    x = d["gd"] - d.groupby(hour)["gd"].transform("mean")
    sxx = float((x * x).sum())
    if sxx < 1e-6:                                     # ingen variation i graddagar (alltid över balanstemperaturen)
        return None
    k = max(0.0, float((x * y).sum()) / sxx)
    return {"k_kw_per_degree": round(k, 4), "hd_ref": float(d["gd"].mean()), "balance_c": float(balance_c), "n": int(len(d))}


def model_from_slope(df, balance_c, k_kw_per_degree, min_rows=24):
    """Modell med ett angivet k; GD_ref tas ur historiken (annars finns inget att jämföra prognosen mot -> None)."""
    if df is None or len(df) < min_rows:
        return None
    d = df.dropna(subset=["temp"])
    if len(d) < min_rows:
        return None
    gd = (float(balance_c) - d["temp"]).clip(lower=0.0)
    return {"k_kw_per_degree": float(k_kw_per_degree), "hd_ref": float(gd.mean()), "balance_c": float(balance_c), "n": int(len(d))}


def adjust_base_load(base_kw, temp_c, model, floor_kw=1.0, cap_kw=None):
    """Baslast för en ruta med prognostemperatur temp_c. Utan modell eller temperatur: oförändrad."""
    if not model or not _known(temp_c):
        return base_kw
    cap = cap_kw if cap_kw is not None else model.get("cap_kw", 10.0)
    delta = model["k_kw_per_degree"] * (heating_degrees(temp_c, model["balance_c"]) - model["hd_ref"])
    return max(float(floor_kw), min(float(base_kw) + delta, float(cap)))
