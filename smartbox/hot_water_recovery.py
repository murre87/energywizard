"""Operator-confirmed journal recovery after released readback. No device writes."""
from copy import deepcopy
import math

from hot_water_control import BoostController
from hot_water_demand import derive
from hot_water_runtime import Journal, control_context


def recover_released(path, house, driver, *, now, exclusive_owner_confirmed,
                     pending_commands_settled):
    if exclusive_owner_confirmed is not True or pending_commands_settled is not True:
        raise ValueError('Explicit exclusive ownership and settled-command confirmations required')
    if type(now) not in (int, float) or not math.isfinite(now):
        raise ValueError('Finite recovery time required')
    hp = house['heat_pump']
    if hp.get('driver') != 'nibe_local':
        raise ValueError('Recovery requires configured local REST')
    context = control_context(house, driver)
    journal = Journal(path)  # A running engine's lifetime lock prevents recovery.
    try:
        state = journal.load()
        if type(state.get('schema')) is not int or state['schema'] != 1 or state.get('context_id') != context:
            raise ValueError('Recovery context does not match')
        cycle = state['cycle']
        if cycle.get('phase') not in {'active', 'start_pending', 'release_pending', 'interrupted'}:
            raise ValueError('No interrupted or unresolved cycle to recover')

        def forbidden_save(value):
            raise ValueError('Recovery cannot execute lifecycle transitions')

        validator = BoostController(driver, lambda: deepcopy(cycle), forbidden_save, context_id=context)
        if validator.storage_error or now < cycle['last_at'] or now < cycle.get('attempted_at', cycle['last_at']):
            raise ValueError('Invalid recovery cycle or clock')
        _, demand = derive(state['demand'], {}, now=now,
            policy=hp['hot_water_control']['comfort_policy'], last_trigger_at=state.get('last_trigger_at'))
        if demand['state'] in {'policy_changed', 'clock_moved_backwards'}:
            raise ValueError('Recovery history requires review')
        if driver.read_hot_water_boost() is not False:
            raise ValueError('Independent released-state readback required')
        # Preserve demand anchors, accepted trigger history and the unresolved
        # cycle as evidence. Recovery is never an invented accepted trigger.
        journal.save({**state, 'cycle': {}, 'recovered_cycle': cycle,
                      'recovery': {'at': now, 'previous_phase': cycle['phase'],
                                   'released_readback': True, 'pending_commands_settled': True}})
        return {'state': 'recovered', 'previous_phase': cycle['phase']}
    finally:
        journal.lock.close()
