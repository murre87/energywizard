"""Test-only exhaustive reference. No production planner imports.

Objective: import - export cash cost, discharged-AC cycle cost, stored-energy
charge/discharge wear, mode changes and physical reversals, less terminal energy.
Actions choose full rated charge/discharge, self-consumption, solar-only absorption
or zero. Integrate continuous stored energy; no production grid recurrence.
"""
from itertools import product
from math import sqrt

ACTIONS = ('auto', 'hold', 'idle', 'charge', 'discharge')


def score(slots, actions, p):
    if len(actions) != len(slots):
        raise ValueError('One action per slot required')
    eta = sqrt(p.get('eff', 0.9))
    energy = p['soc0_kwh']
    lo = max(0, p['reserve_kwh'])
    hi = min(p['capacity_kwh'], p['max_kwh'])
    previous, direction = 'auto', 0
    cost, rows = 0.0, []
    allowed = set(p.get('allowed', ACTIONS)) | {'auto'}
    for s, action in zip(slots, actions):
        if action not in allowed:
            raise ValueError('Unsupported action')
        demand = s['load_kw'] + s.get('ev_kw', 0) - s.get('solar_kw', 0)
        if action == 'auto': watts = min(p['charge_kw'], max(-p['discharge_kw'], -demand))
        elif action == 'hold': watts = min(p['charge_kw'], max(0, -demand))
        elif action == 'idle': watts = 0
        elif action == 'charge': watts = p['charge_kw']
        else: watts = -p['discharge_kw']
        if not p.get('allow_export', True) and watts < 0:
            watts = max(watts, -max(0, demand))
        if s.get('ev_kw', 0) > 0.1 and watts < 0:
            mode = p.get('ev_mode', 'block')
            if mode == 'offload': watts = max(watts, -max(0, s['load_kw']-s.get('solar_kw', 0)))
            elif mode != 'free':
                if action == 'discharge': raise ValueError('Discharge prohibited during EV charging')
                watts = 0
        before = energy
        if watts >= 0:
            added = min(watts*0.25*eta, max(0, hi-energy))
            energy += added
            watts = added/(0.25*eta)
        else:
            removed = min(-watts*0.25/eta, max(0, energy-lo))
            energy -= removed
            watts = -removed*eta/0.25
        # Initial out-of-bounds energy may stay there but cannot get worse.
        if energy < min(lo, before)-1e-9 or energy > max(hi, before)+1e-9:
            raise ValueError('Energy constraint violated')
        grid = demand + watts
        cash = grid*0.25*(s['buy'] if grid > 0 else s['sell'])
        wear = (p.get('cycle_cost', 0)*max(0, -watts)*0.25
                + p.get('charge_wear_cost_sek_per_kwh', 0)*max(0, energy-before)
                + p.get('discharge_wear_cost_sek_per_kwh', 0)*max(0, before-energy))
        new_direction = 1 if watts > 1e-9 else -1 if watts < -1e-9 else 0
        reversal = bool(direction and new_direction and direction != new_direction)
        cost += (cash + wear + p.get('switch_cost', .1)*(action != previous)
                 + p.get('reversal_cost_sek', 0)*reversal)
        rows.append({'energy': energy, 'power': watts, 'grid': grid})
        previous, direction = action, new_direction or direction
    prices = sorted(s['buy'] for s in slots)
    terminal_rate = prices[min(len(prices)-1, int(len(prices)*p.get('terminal_pct', 25)/100))]*eta
    return cost-energy*terminal_rate, rows


def exhaustive(slots, p):
    if not 1 <= len(slots) <= 6:
        raise ValueError('Reference horizon limited to six quarters')
    allowed = tuple(a for a in ACTIONS if a in set(p.get('allowed', ACTIONS)) | {'auto'})
    best, winner = float('inf'), None
    for actions in product(allowed, repeat=len(slots)):
        try: value, _ = score(slots, actions, p)
        except ValueError: continue
        if value < best:
            best, winner = value, actions
    return best, winner


def check_candidate(slots, rows, p, tolerance=1e-7):
    value, physical = score(slots, [r['action'] for r in rows], p)
    for actual, expected in zip(rows, physical):
        if abs(actual['soc_kwh']-expected['energy']) > .00001 or abs(actual['battery_kw']-expected['power']) > .00051:
            raise ValueError('Candidate violates continuous energy/power accounting')
    optimum, _ = exhaustive(slots, p)
    if value > optimum+tolerance:
        raise ValueError('Candidate is economically suboptimal')
    return value
