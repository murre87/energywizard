"""
battery_control.py - husbatteriet som en del av HELA systemet, inte en egen ö.

Batteriet konkurrerar med elbil, värmepump, spabad och export om samma watt. Därför fattas
besluten här med hela husets läge som indata (elbilens laddning, effekttaket, säkringen,
elpriset, solöverskottet) - samma idé som evcc:s samspel mellan batteri och elbil och FTW:s
säkerhetsmodell, men egen implementation.

Tre lägen (battery.control i house_config.yaml):
  samarbete  (standard) Ett annat system styr batteriet (växelriktarens egen BESS, Predbat).
             EnergyWizard skriver ALDRIG till batteriet - läser bara, och resten av motorn
             räknar redan rätt eftersom allt mäts vid huvudsäkringen (efter batteriet).
  styr       EnergyWizard väljer läge enligt reglerna nedan.
  av         Batteriet ignoreras.

Reglerna, i prioritetsordning (första som gäller vinner):
  1. Gammal data (batteriet eller elmätaren svarar inte)  -> auto  (växelriktaren tar över)
  2. Säkringen överbelastad / över 1,2 x                   -> ladda ur (om över reservnivån)
  3. Effekttaket nått och huset köper el                   -> ladda ur (om över reservnivån)
  3b. "Toppa nu till X %" (appen, #396)                   -> ladda tills målet (inom säkringen)
  4. Minuspris                                             -> ladda (även från nätet), upp till max
  5. Elbilen laddar från nätet                             -> håll (töm inte batteriet i bilen)
  6. Elbilen solladdar och batteriet är över prioritetsnivån -> vila (överskottet till bilen)
  7. Batteriet vid/under reservnivån utan planerad laddning -> håll (sparas till strömavbrott)
  8. Dygnsplanen (battery_plan.py) för pågående kvart     -> ladda / ladda ur / håll / auto
  9. (utan plan) Billig timme och dyrare timmar kvar       -> håll (spara till de dyra timmarna)
 10. Annars                                                -> auto (självförbrukning)

En avsikt som drivrutinen inte stöder ersätts av närmaste säkra (vila -> håll -> auto).
Ren funktion; testas i tests/test_battery_control.py.
"""

from datetime import timedelta

FUSE_CAP_STEP_W = 100         # #399: minsta minskning som skrivs när säkringstaket sänker laddningen
POWER_DEADBAND_W = 200        # #194: mindre effektändringar inom samma läge skrivs inte
MIN_CHANGE_INTERVAL = timedelta(minutes=5)     # lägesbyten sparsamt (flashminne), säkerhetsregler undantagna
SAFETY_RULES = {"stale", "fuse", "fuse_cap", "peak", "soc_limit"}
FUSE_MIN_W = 500
FROZEN_AFTER_S = 600          # elmätaren visar exakt samma värde så här länge -> räknas som död


class MeterFreeze:
    """Känner igen en elmätare som fastnat (FTW-lärdom). HA kan fortsätta svara med senaste
    värdet när mätaren tystnat, så en lyckad läsning betyder inte att värdet är färskt.
    En riktig mätare ändras hela tiden, även lite."""

    def __init__(self, after_s=FROZEN_AFTER_S):
        self.after_s = after_s
        self._value = None
        self._since = None

    def update(self, value, now):
        if value != self._value:
            self._value, self._since = value, now
        return self.frozen(now)

    def frozen(self, now):
        return self._since is not None and (now - self._since) >= self.after_s
_FALLBACK = {"idle": ["idle", "hold", "auto"], "hold": ["hold", "auto"], "charge": ["charge", "auto"],
             "discharge": ["discharge", "auto"], "auto": ["auto"]}


EXPORT_MARGIN_W = 50.0      # sikta på så här mycket import när export inte är tillåten


def _percentile(values, pct):
    s = sorted(v for v in values if v is not None)
    if not s:
        return None
    return s[max(0, min(len(s) - 1, int(round(pct / 100.0 * (len(s) - 1)))))]


def decide(s, cfg, supported=frozenset({"auto"})):
    """s = husets läge (se nycklar nedan), cfg = house_config.battery_settings().
    Returnerar {'intent': str|None, 'power_w': float|None, 'rule': str, 'reason': str}.
    intent None = skriv ingenting (samarbete/av eller inget batteri)."""
    control = cfg.get("control", "samarbete")
    soc = s.get("soc")
    if control == "av":
        return {"intent": None, "power_w": None, "rule": "av", "reason": "Batteristyrningen är avstängd."}
    if control == "samarbete":
        txt = "Samarbete: batteriet styrs av ett annat system (t.ex. växelriktarens BESS eller Predbat)."
        if soc is not None:
            txt += f" EnergyWizard läser det ({soc:.0f} %) och räknar med det, men skriver aldrig."
        return {"intent": None, "power_w": None, "rule": "samarbete", "reason": txt}

    symbol = s.get("currency_symbol", "kr")
    reserve, prio, max_soc = cfg.get("reserve_soc", 20.0), cfg.get("priority_soc", 50.0), cfg.get("max_soc", 100.0)
    pmax = cfg.get("max_power_w", 5000.0)
    above_reserve = soc is not None and soc > reserve

    def no_export(intent, power, reason):
        """Ensidigt exportskydd (FTW-lärdom 2026-11-04): när export inte är tillåten får urladdningen aldrig bli större
        än det huset köper just nu - sikta på ~50 W import, aldrig export. Batteriets nuvarande urladdning räknas in
        (nätet visar redan resultatet av den)."""
        if intent != "discharge" or cfg.get("allow_export", True) or power is None:
            return power, reason
        now_dis = max(0.0, -(s.get("battery_w") or 0.0))
        cap = (s.get("avg_net_w") or 0.0) + now_dis - EXPORT_MARGIN_W
        if cap < power:
            return max(0.0, cap), reason + f" Urladdningen begränsas till husets behov ({max(0.0, cap):.0f} W) - ingen export."
        return power, reason

    def out(intent, rule, reason, power=None):
        power, reason = no_export(intent, power, reason)
        cap = s.get("fuse_charge_cap_w")
        if intent == "charge" and cap is not None:
            # #399: laddning från nätet får bara ta säkringens lediga utrymme (elbilens nya ökning avräknad)
            if cap < FUSE_MIN_W:
                intent, power, rule = "hold", None, "fuse_cap"
                reason += " Säkringen har inte utrymme för batteriet just nu - det håller i stället."
            elif power is None or power > cap:
                power, rule = cap, "fuse_cap"
                reason += f" Laddningen begränsas till {cap:.0f} W så att säkringen räcker."
        for cand in _FALLBACK[intent]:
            if cand == "auto" or cand in supported:
                if cand != intent:
                    reason += f" (batteriet saknar läget '{intent}' - kör '{cand}')"
                return {"intent": cand, "power_w": power if cand == intent else None, "rule": rule, "reason": reason}

    if soc is None or not s.get("meter_fresh", True):
        return out("auto", "stale", "Säkerhet: batteriet eller elmätaren svarar inte - växelriktaren styr själv.")
    if s.get("fuse_state") in ("trip", "overload") and above_reserve:
        # Bara överskottet (FTW-lärdom): full urladdning trycker ner nätet långt under gränsen
        # och slösar batteri. Överskottet i A på värsta fasen räknas om till effekt för en
        # trefasig växelriktare, med 20 % marginal. Okänt överskott -> full effekt.
        excess_a = s.get("fuse_excess_a") or 0
        p = pmax
        if excess_a > 0:
            p = max(FUSE_MIN_W, excess_a * 230.0 * 3 * 1.2)
            p = min(pmax, p) if pmax else p
        return out("discharge", "fuse", f"Säkringen är överbelastad - batteriet laddar ur för att avlasta ({soc:.0f} %).", p)
    if s.get("peak_reached") and (s.get("avg_net_w") or 0) > 100 and above_reserve:
        return out("discharge", "peak", f"Effekttaket är nått - batteriet täcker toppen ({soc:.0f} %).", pmax)
    price = s.get("price")
    topup = s.get("topup_target")
    if topup and soc < min(float(topup), max_soc):           # #396: "Toppa nu till X %" (säkringstaket gäller)
        return out("charge", "topup", f"Toppar batteriet till {float(topup):.0f} %, {soc:.0f} % nu.", pmax)
    if price is not None and price < 0 and soc < max_soc:
        return out("charge", "negative", f"Minuspris ({price:.2f} {symbol}/kWh) - laddar batteriet från nätet.", pmax)
    if s.get("ev_charging_grid"):
        return out("hold", "ev_grid", "Elbilen laddar från nätet - batteriet töms inte i bilen.")
    if s.get("ev_solar_active") and soc >= prio:
        return out("idle", "ev_solar", f"Elbilen solladdar och batteriet har {soc:.0f} % (över {prio:.0f} %) - solöverskottet går till bilen.")
    planned = s.get("planned_action")
    if s.get("balance_hold_now") and s.get("balance_target_soc") and soc < s["balance_target_soc"] - 0.5:
        planned = "charge"  # Top up an already scheduled dwell, never start a request early.
    if planned == "charge" and soc >= (s.get("balance_target_soc") or max_soc):
        return out("hold", "soc_limit", "Batteriet har nått laddtaket - laddningen pausas.")
    # The reserve protects against discharge, but must allow planned charging to recover (#229).
    if soc <= reserve and planned != "charge":
        return out("hold", "reserve", f"Batteriet är på reservnivån ({soc:.0f} % ≤ {reserve:.0f} %) - sparas till strömavbrott.")
    if planned:
        from battery_plan import REASON
        pmax_plan = pmax if planned in ("charge", "discharge") else None
        if pmax_plan and s.get("planned_power_w"):            # planens egen effekt, aldrig över taket
            pmax_plan = min(pmax_plan, max(500.0, float(s["planned_power_w"])))
        detail = f" ({price:.2f} {symbol}/kWh)" if price is not None else ""
        saving = s.get("plan_saving_kr")
        extra = f" Planen sparar ≈ {saving:.0f} {symbol} mot ren självförbrukning." if saving and saving >= 1 else ""
        note = f" {s['learned_note']}" if s.get("learned_note") else ""
        if s.get("balance_target_soc"):
            return out(planned, "balance", "Planen: balansering efter uppmätt skillnad mellan batterimodulerna.", pmax_plan)
        return out(planned, "plan", f"{REASON.get(planned, 'Planen')}{detail}.{extra}{note}", pmax_plan)
    remaining = s.get("prices_rest_of_day") or []
    p33, p67 = _percentile(remaining, 33), _percentile(remaining, 67)
    if price is not None and p33 is not None and p67 is not None and price <= p33 and p67 > price * 1.2 + 0.05:
        return out("hold", "cheap_hour", f"Billig timme ({price:.2f} {symbol}) och dyrare timmar kvar idag - batteriet sparas till dem.")
    return out("auto", "default", f"Självförbrukning - batteriet täcker husets behov ({soc:.0f} %).")


def should_apply(new, last, last_change_at, now, min_change_minutes=5.0):
    """Byt vid behov: säkerhetsregler direkt, annars konfigurerat intervall (minst 5 min)."""
    if new is None or new.get("intent") is None:
        return False
    if last is None or last_change_at is None:
        return True
    if new["intent"] == last.get("intent") and new.get("power_w") == last.get("power_w"):
        return False
    # #399: säkringstaket - en minskning skrivs direkt, en ökning bara om den är tydlig (flashminnet)
    if new["intent"] == last.get("intent") and new.get("rule") == "fuse_cap":
        a, b = new.get("power_w"), last.get("power_w")
        if a is not None and b is not None:
            return a <= b - FUSE_CAP_STEP_W or a >= b + max(POWER_DEADBAND_W, abs(b) * 0.10)
    # #194: samma läge, liten effektändring -> skriv inte (effektbörvärden sparas ofta i växelriktarens flash)
    if new["intent"] == last.get("intent") and new.get("rule") not in SAFETY_RULES and last.get("rule") not in SAFETY_RULES:
        a, b = new.get("power_w"), last.get("power_w")
        if a is not None and b is not None and abs(a - b) < max(POWER_DEADBAND_W, abs(b) * 0.10):
            return False
    if new.get("rule") in SAFETY_RULES or last.get("rule") in SAFETY_RULES:
        return True
    if new.get("rule") == "topup" and last.get("rule") != "topup":     # #396: användarens "Toppa nu" startar direkt
        return True
    return (now - last_change_at) >= max(MIN_CHANGE_INTERVAL, timedelta(minutes=min_change_minutes))
