"""Husbatteriets dygnsplan (smartbox/battery_plan.py): billig laddning, dyr urladdning, gränser."""
import os
import sys

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "smartbox")))

from battery_plan import optimize, blocks, simulate, live_charge_kw, command_power_w


def _slots(prices, load=1.0, solar=None, ev=None):
    solar = solar or [0.0] * len(prices)
    ev = ev or [0.0] * len(prices)
    return [{"t": f"t{i}", "buy": p * 1.25 + 0.6, "sell": p, "load_kw": load, "solar_kw": solar[i], "ev_kw": ev[i]}
            for i, p in enumerate(prices)]


# 4 h billig natt, 4 h dyr kväll (16 + 16 kvartar)
CHEAP_THEN_DEAR = [0.20] * 16 + [2.50] * 16


def test_laddar_billigt_och_laddar_ur_dyrt_och_sparar_pengar():
    r = optimize(_slots(CHEAP_THEN_DEAR), soc0_kwh=2.0, capacity_kwh=10.0, reserve_kwh=2.0, max_kwh=10.0,
                 charge_kw=3.0, discharge_kw=3.0, eff=0.9)
    acts = [x["action"] for x in r["rows"]]
    assert "charge" in acts[:16]                         # laddar på natten
    assert all(a != "charge" for a in acts[16:])         # aldrig i de dyra timmarna
    assert max(x["soc_kwh"] for x in r["rows"][:16]) > 8.0
    assert r["saving_kr"] > 5                            # 8 kWh × ~2.8 kr skillnad, minus förluster
    assert r["cost"] < r["baseline_cost"]


def test_platt_pris_ger_ingen_meningslos_cykling():
    r = optimize(_slots([1.0] * 32), 5.0, 10.0, 2.0, 10.0, 3.0, 3.0, eff=0.9)
    assert "charge" not in [x["action"] for x in r["rows"]]       # förluster gör det olönsamt
    assert abs(r["saving_kr"]) < 0.5


def test_reservniva_och_max_respekteras():
    r = optimize(_slots(CHEAP_THEN_DEAR), 4.0, 10.0, 3.0, 9.0, 3.0, 3.0)
    socs = [x["soc_kwh"] for x in r["rows"]]
    assert min(socs) >= 3.0 - 0.11 and max(socs) <= 9.0 + 0.11


def test_tommer_inte_batteriet_i_elbilen():
    ev = [0.0] * 16 + [11.0] * 16                        # bilen laddar under de dyra timmarna
    r = optimize(_slots(CHEAP_THEN_DEAR, ev=ev), 9.0, 10.0, 2.0, 10.0, 3.0, 3.0)
    assert all(x["battery_kw"] >= -1e-9 for x in r["rows"][16:])


def test_bara_stodda_avsikter_anvands():
    r = optimize(_slots(CHEAP_THEN_DEAR), 2.0, 10.0, 2.0, 10.0, 3.0, 3.0, allowed={"auto", "hold"})
    assert set(x["action"] for x in r["rows"]) <= {"auto", "hold"}


def test_solen_laddar_batteriet_gratis_i_auto():
    solar = [0.0] * 8 + [4.0] * 8 + [0.0] * 16
    cost, rows = simulate(_slots([1.0] * 32, solar=solar), 2.0, ["auto"] * 32, 10.0, 2.0, 10.0, 3.0, 3.0, 0.9)
    assert rows[15]["soc_kwh"] > 6.0


def test_pass_for_planvyn():
    r = optimize(_slots(CHEAP_THEN_DEAR), 2.0, 10.0, 2.0, 10.0, 3.0, 3.0)
    b = blocks(r["rows"])
    assert b and b[0]["action"] == "charge" and b[0]["start"] == r["rows"][0]["t"] or b[0]["action"] in ("charge", "hold")
    assert all(x["action"] != "auto" for x in b)


def test_tomt_eller_utan_kapacitet():
    assert optimize([], 0, 10, 2, 10, 3, 3)["rows"] == []
    assert optimize(_slots([1.0]), 0, None, 2, 10, 3, 3)["rows"] == []


def test_wear_blocks_discharge_below_cost_but_allows_profitable_use():
    slots = [{"t": "t0", "buy": 0.4, "sell": 0.0, "load_kw": 1.0}]
    low = optimize(slots, 5, 10, 2, 10, 1, 1, eff=1, switch_cost=0,
                   discharge_wear_cost_sek_per_kwh=0.5)
    assert low["rows"][0]["battery_kw"] == 0
    slots[0]["buy"] = 2.0
    # Include cheap future energy so terminal valuation does not reward hoarding.
    high = optimize(slots + [{**slots[0], "t": "t1", "buy": 0.0, "load_kw": 0.0}],
                    5, 10, 2, 10, 1, 1, eff=1, switch_cost=0,
                    discharge_wear_cost_sek_per_kwh=0.5)
    assert high["rows"][0]["battery_kw"] < 0
    assert high["wear_cost_sek"] > 0


def test_charge_wear_blocks_small_negative_price_opportunity():
    slots = [{"t": "t0", "buy": -0.1, "sell": -0.1, "load_kw": 0.0},
             {"t": "t1", "buy": 0.0, "sell": 0.0, "load_kw": 0.0}]
    r = optimize(slots, 2, 10, 2, 10, 1, 1, eff=1, switch_cost=0,
                 charge_wear_cost_sek_per_kwh=0.5)
    assert all(row["battery_kw"] == 0 for row in r["rows"])


def test_reversal_penalty_remembers_direction_across_idle_and_auto():
    slots = [{"t": "t0", "buy": 0.0, "sell": 0.0, "load_kw": 0.0, "solar_kw": 1.0},
             {"t": "t1", "buy": 0.0, "sell": 0.0, "load_kw": 0.0},
             {"t": "t2", "buy": 2.0, "sell": 0.0, "load_kw": 1.0}]
    plain = optimize(slots, 2, 10, 2, 10, 1, 1, eff=1, allowed={"auto", "idle"}, switch_cost=0)
    guarded = optimize(slots, 2, 10, 2, 10, 1, 1, eff=1, allowed={"auto", "idle"},
                       switch_cost=0, reversal_cost_sek=10)
    assert any(row["direction_reversal"] for row in plain["rows"])
    assert not any(row["direction_reversal"] for row in guarded["rows"])


def test_invalid_wear_cost_rejected():
    import pytest
    for value in (-1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            optimize(_slots([1.0]), 5, 10, 2, 10, 1, 1, discharge_wear_cost_sek_per_kwh=value)


def test_zero_new_costs_preserve_original_main_rows():
    """Golden rows generated from main daf9e33, before direction-state expansion.

    Keep the reference independent of the current optimizer and available without Git.
    Both cases cover prices, PV, EV load, terminal styles and different export policies.
    """
    import json
    from pathlib import Path
    fixture = json.loads((Path(__file__).parent / "fixtures" / "battery_plan_legacy.json").read_text())
    for case in fixture["cases"]:
        result = optimize(fixture["slots"], 2, 4, 1, 4, 2, 2, **case["options"],
                          charge_wear_cost_sek_per_kwh=0, discharge_wear_cost_sek_per_kwh=0,
                          reversal_cost_sek=0)
        expected = case["result"]
        # Extra diagnostic columns are additive; all original row values must be exact.
        legacy_rows = [{key: row[key] for key in expected["rows"][0]} for row in result["rows"]]
        assert legacy_rows == expected["rows"]
        for key in ("cost", "baseline_cost", "saving_kr"):
            assert result[key] == expected[key]


def test_legacy_discharge_cost_and_new_wear_are_additive_with_losses():
    import math
    import pytest
    slots = [{"t": "t0", "buy": 2.0, "sell": 0.0, "load_kw": 1.0}]
    cost, rows = simulate(slots, 5, ["auto"], 10, 2, 10, 1, 1, 0.81, 0.30,
                          discharge_wear_cost_sek_per_kwh=0.18)
    # 0.25 AC kWh delivered, 0.25 / 0.9 stored kWh removed.
    assert cost == pytest.approx(0.25 * 0.30 + 0.25 / math.sqrt(0.81) * 0.18)
    assert rows[0]["cost"] == cost


def test_plan_cost_includes_legacy_and_new_wear_once():
    import pytest
    r = optimize(_slots(CHEAP_THEN_DEAR), 2, 10, 2, 10, 3, 3, cycle_cost=0.30,
                 charge_wear_cost_sek_per_kwh=0.05, discharge_wear_cost_sek_per_kwh=0.10)
    grid_cost = sum((row["grid_kw"] * 0.25) * (slot["buy"] if row["grid_kw"] > 0 else slot["sell"])
                    for row, slot in zip(r["rows"], _slots(CHEAP_THEN_DEAR)))
    assert r["cost"] == pytest.approx(grid_cost + r["wear_cost_sek"], abs=0.01)


def test_planvyn_och_tidslinjen_visar_batteriet():
    from datetime import datetime, timedelta
    from plan_brief import battery_items, SWE
    from timeline import build
    now = datetime(2026, 11, 2, 14, 10, tzinfo=SWE)
    q = now.replace(minute=0)
    rows = [(q + timedelta(minutes=15 * i), "charge", 20 + 10 * i, 0.3) for i in range(4)] + \
           [(q + timedelta(hours=3, minutes=15 * i), "discharge", 60 - 10 * i, 2.5) for i in range(4)]
    items = battery_items(rows, now)
    assert [i["title"] for i in items] == ["🔋 Batteriet laddar", "🔋 Batteriet laddar ur"]
    assert items[0]["active"] and items[0]["when"] == "till 15:00" and "till 50 %" in items[0]["detail"]
    d = build(now, {q: {"price": 1.0, "battery_kw": 2.0}}, {q + timedelta(hours=k): 1.0 for k in range(1, 5)}, {}, {}, {},
              battery_plan={q + timedelta(hours=3): "discharge"})
    lane = next(l for l in d["lanes"] if l["key"] == "batteri")
    i_now = d["hours"].index(q.isoformat())
    assert lane["text"][i_now] == "Laddade 2.0 kW" and lane["text"][i_now + 3] == "Planerat: laddar ur"
    assert not any(l["key"] == "batteri" for l in build(now, {}, {}, {}, {}, {})["lanes"])


def test_slitage_gor_sma_prisskillnader_olonsamma():
    """Liten skillnad (0,30 -> 0,60 kr spot): utan slitage lönar sig en cykel, med 0,50 kr/kWh slitage inte."""
    prices = [0.30] * 16 + [0.60] * 16
    utan = optimize(_slots(prices), 2.0, 10.0, 2.0, 10.0, 3.0, 3.0, eff=0.95, cycle_cost=0.0)
    med = optimize(_slots(prices), 2.0, 10.0, 2.0, 10.0, 3.0, 3.0, eff=0.95, cycle_cost=0.50)
    assert "charge" in [x["action"] for x in utan["rows"]]
    assert "charge" not in [x["action"] for x in med["rows"]]
    # Stor skillnad lönar sig fortfarande trots slitage
    stor = optimize(_slots(CHEAP_THEN_DEAR), 2.0, 10.0, 2.0, 10.0, 3.0, 3.0, cycle_cost=0.50)
    assert "charge" in [x["action"] for x in stor["rows"]] and stor["saving_kr"] > 5


def _day_slots():
    """Billigt på natten, dyrt på kvällen, sol mitt på dagen."""
    from datetime import datetime, timedelta
    t0 = datetime(2026, 11, 3, 0, 0)
    out = []
    for q in range(96):
        h = q // 4
        buy = 0.5 if h < 6 else (3.0 if 17 <= h < 21 else 1.2)
        out.append({"t": t0 + timedelta(minutes=15 * q), "buy": buy, "sell": buy * 0.8, "load_kw": 0.5,
                    "solar_kw": 3.0 if 10 <= h < 15 else 0.0, "ev_kw": 0.0})
    return out


def test_forsiktig_stil_sparar_mer_i_batteriet():
    from battery_plan import optimize, style_params
    slots = _day_slots()
    end = {}
    for style in ("very_careful", "very_bold"):
        _, _, pct = style_params(style)
        r = optimize(slots, 5.0, 10.0, 1.0, 10.0, 5.0, 5.0, terminal_pct=pct)
        end[style] = r["rows"][-1]["soc_kwh"]
    assert end["very_careful"] >= end["very_bold"]


def test_utan_forsaljning_laddar_batteriet_aldrig_ur_mot_natet():
    from battery_plan import optimize
    slots = _day_slots()
    r = optimize(slots, 9.0, 10.0, 1.0, 10.0, 5.0, 5.0, allow_export=False)
    for row, s in zip(r["rows"], slots):
        net = s["load_kw"] - s["solar_kw"]
        if row["battery_kw"] < 0:
            assert -row["battery_kw"] <= max(0.0, net) + 1e-6       # bara husets förbrukning
    r2 = optimize(slots, 9.0, 10.0, 1.0, 10.0, 5.0, 5.0, allow_export=True)
    assert min(x["battery_kw"] for x in r2["rows"]) < -0.6           # med försäljning får den ladda ur mer


def test_batteripass_har_niva_energi_och_pris_for_planklockan():
    """Planklockans batterirad: 80→35 %, kWh och toppris (urladdning) / lägsta pris (laddning)."""
    from datetime import datetime, timedelta
    from plan_brief import battery_items, SWE
    now = datetime(2026, 11, 4, 6, 0, tzinfo=SWE)
    rows = [(now - timedelta(minutes=15), "auto", 80, 1.0, 0.0)] + \
           [(now + timedelta(minutes=15 * i), "discharge", 80 - 15 * (i + 1), p, -3.0) for i, p in enumerate([3.1, 4.31, 2.9])] + \
           [(now + timedelta(hours=2, minutes=15 * i), "charge", 40 + 10 * i, p, 2.0) for i, p in enumerate([0.5, 0.2])]
    ur, ladd = battery_items(rows, now)
    assert (ur["soc_from"], ur["soc_to"], ur["kwh"], ur["price_peak"]) == (80, 35, 2.2, 4.31)
    assert (ladd["soc_from"], ladd["soc_to"], ladd["kwh"], ladd["price_peak"]) == (35, 50, 1.0, 0.2)
    # Äldre rader utan battery_kw går fortfarande
    assert battery_items([r[:4] for r in rows], now)[0]["kwh"] is None


@pytest.mark.parametrize("initial_kwh", [0.0, 1.7, 2.0])
def test_plan_recovers_from_reserve_without_discharging_below_it(initial_kwh):
    from battery_control import decide

    r = optimize(_slots([0.01] + CHEAP_THEN_DEAR[1:]), initial_kwh, 10.0, 2.0, 10.0, 3.0, 3.0)
    assert r["rows"][0]["action"] == "charge"
    previous_kwh = initial_kwh
    for row in r["rows"]:
        assert row["soc_kwh"] >= min(previous_kwh, 2.0) - 1e-9
        if previous_kwh <= 2.0:
            assert row["action"] != "discharge"
            assert row["battery_kw"] >= 0
        previous_kwh = row["soc_kwh"]

    # Feed the actual optimizer output into the controller, as main.py does.
    decision = decide({"soc": initial_kwh * 10, "price": 0.3,
                       "planned_action": r["rows"][0]["action"],
                       "planned_power_w": r["rows"][0]["battery_kw"] * 1000},
                      {"control": "styr", "reserve_soc": 20, "max_power_w": 3000},
                      {"auto", "charge", "discharge"})
    assert decision["intent"] == "charge" and decision["rule"] == "plan"
    assert decision["power_w"] == 3000


def _charge_samples(start, n, watts, step=60):
    return [(start + i * step, watts) for i in range(n)]


def test_live_charge_uses_sustained_shortfall_only():
    # Fem minuter på 2,5 kW när planen räknar med 11 kW: resten av dygnet planeras i 2,5.
    assert live_charge_kw(11.0, _charge_samples(0, 6, 2500)) == 2.5
    assert live_charge_kw(11.0, _charge_samples(0, 2, 2500, step=300)) == 11.0   # för få prover
    assert live_charge_kw(11.0, _charge_samples(0, 4, 2500, step=60)) == 11.0    # kortare än fem minuter
    assert live_charge_kw(11.0, _charge_samples(0, 6, 8000)) == 11.0             # 8 kW är inte långt under 11
    assert live_charge_kw(11.0, _charge_samples(0, 6, 200)) == 11.0              # ingen riktig laddning
    assert live_charge_kw(11.0, [(0, 2500), (120, "x"), (300, None), (600, 2500)]) == 11.0
    assert live_charge_kw(2.5, _charge_samples(0, 6, 4000)) == 2.5               # höjer aldrig


def test_slow_charge_schedule_still_commands_full_power():
    assert command_power_w("charge", 2.5, 11.0, 2.5) == 11000
    assert command_power_w("charge", 4.0, 11.0, 11.0) == 4000                    # nära fullt: oförändrat
    assert command_power_w("discharge", -3.0, 11.0, 2.5) == 3000
    assert command_power_w("auto", None, 11.0, 11.0) is None


def test_lagre_laddeffekt_tar_fler_billiga_kvartar():
    # 8 kvartar lite dyrare, 4 klart billigare, sedan dyr last. 11 kW hinner i de billigaste.
    # 2,5 kW gör det inte, så planen måste börja tidigare.
    prices = [0.40] * 8 + [0.20] * 4 + [3.00] * 8
    slots = [{"t": f"t{i}", "buy": p, "sell": 0.0, "load_kw": 3.0, "solar_kw": 0.0, "ev_kw": 0.0}
             for i, p in enumerate(prices)]
    kw = dict(soc0_kwh=2.0, capacity_kwh=10.0, reserve_kwh=2.0, max_kwh=10.0, discharge_kw=5.0,
              eff=1.0, switch_cost=0, cycle_cost=0, allow_export=False)
    fast = optimize(slots, charge_kw=11.0, **kw)
    slow = optimize(slots, charge_kw=2.5, **kw)
    fast_early = sum(row["action"] == "charge" for row in fast["rows"][:8])
    slow_early = sum(row["action"] == "charge" for row in slow["rows"][:8])
    assert sum(row["action"] == "charge" for row in fast["rows"][8:12]) >= 1
    assert slow_early > fast_early
    assert min(row["soc_kwh"] for row in slow["rows"]) >= 2.0 - 0.11
