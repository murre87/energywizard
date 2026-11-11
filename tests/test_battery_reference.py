from pathlib import Path
import pytest
from battery_reference import score, exhaustive, check_candidate
from battery_plan import optimize


def slots(prices, load=1, solar=0, ev=0):
    return [{'t': str(i), 'buy': price, 'sell': price*.5,
             'load_kw': load, 'solar_kw': solar, 'ev_kw': ev} for i, price in enumerate(prices)]


def params(**kw):
    return dict(soc0_kwh=.5, capacity_kwh=1, reserve_kwh=0, max_kwh=1,
                charge_kw=1, discharge_kw=1, eff=1, step_kwh=.005, switch_cost=0, **kw)


def test_hand_calculated_cash_efficiency_wear_and_terminal():
    p = params(cycle_cost=.2, discharge_wear_cost_sek_per_kwh=.3,
               charge_wear_cost_sek_per_kwh=.1, reversal_cost_sek=.4)
    ss = slots([0, 4], load=0)
    value, rows = score(ss, ['charge', 'discharge'], p)
    # +.25 stored (wear .025); -.25 exported earns .50, wears .05+.075;
    # reversal .4; terminal value zero.
    assert value == pytest.approx(.05)
    assert rows[-1]['energy'] == .5
    p['eff'] = .81
    value, rows = score(slots([0], load=0), ['charge'], p)
    assert rows[0]['energy'] == pytest.approx(.725)
    assert value == pytest.approx(.0225)


@pytest.mark.parametrize('ss,extra', [
    (slots([0, 4, 1, 0]), {}),
    (slots([-2, 3, -.5, 0]), {}),
    (slots([0, 4, 1, 0]), {'reserve_kwh': .25, 'max_kwh': .75}),
    (slots([0, 4, 1, 0]), {'eff': .64, 'step_kwh': .0025}),
    (slots([0, 4, 1, 0]), {'cycle_cost': .8, 'charge_wear_cost_sek_per_kwh': .4, 'discharge_wear_cost_sek_per_kwh': .7}),
    (slots([0, 4, 1, 0]), {'reversal_cost_sek': .3}),
    (slots([0, 4, 1, 0]), {'switch_cost': .1}),
    (slots([0, 4, 1, 0], solar=2), {'allow_export': False}),
    (slots([0, 4, 1, 0], ev=2), {'ev_mode': 'block'}),
    (slots([0, 4, 1, 0], ev=2), {'ev_mode': 'offload'}),
    (slots([0, 4, 1, 0], ev=2), {'ev_mode': 'free'}),
    (slots([0, 4, 1, 0]), {'terminal_pct': 75}),
    (slots([0, 4, 1, 0]), {'allowed': ['auto', 'hold']}),
])
def test_production_matches_continuous_reference_on_aligned_grid(ss, extra):
    p = params();p.update(extra)
    result = optimize(ss, **p)
    check_candidate(ss, result['rows'], p)


def test_switching_and_reversal_through_idle_are_independently_scored():
    p = params(reversal_cost_sek=.4);p['switch_cost'] = .2
    value, _ = score(slots([0, 0, 0], load=0), ['charge', 'idle', 'discharge'], p)
    assert value == pytest.approx(1.0)  # three changes plus one physical reversal


def test_checker_rejects_bad_physics_and_inferior_plans():
    ss = slots([0, 4, 0]);p=params()
    _, physical = score(ss, ['idle']*3, p)
    rows = [{'action':'idle','soc_kwh':r['energy'],'battery_kw':r['power']} for r in physical]
    with pytest.raises(ValueError, match='suboptimal'): check_candidate(ss, rows, p)
    rows[0]['soc_kwh']=100
    with pytest.raises(ValueError, match='accounting'): check_candidate(ss, rows, p)
    with pytest.raises(ValueError): score(ss, ['bad']*3, p)
    with pytest.raises(ValueError): exhaustive(slots([0]*7), p)


def test_reference_has_no_production_dependency():
    import ast
    tree=ast.parse(Path(__file__).with_name('battery_reference.py').read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import): assert all(n.name in ('itertools', 'math') for n in node.names)
        if isinstance(node, ast.ImportFrom): assert node.module in ('itertools', 'math')
