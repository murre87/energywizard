"""Operator recovery changes only private state, never the heater."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from hot_water_recovery import recover_released
from hot_water_runtime import Journal
from test_hot_water_runtime import runtime, run, house, Heater, NOW


def interrupted(tmp_path):
    r, h, cfg = runtime(tmp_path), Heater(), house()
    run(r, h, cfg)
    run(r, h, cfg, seconds=900)
    before = deepcopy(r.state)
    r.journal.lock.close()
    return r, h, cfg, before


def recover(tmp_path, h, cfg, **changes):
    return recover_released(tmp_path / 'control.json', cfg, h,
        **{**dict(now=NOW+1000, exclusive_owner_confirmed=True, pending_commands_settled=True), **changes})


def test_released_recovery_preserves_history_and_never_writes_heater(tmp_path):
    r, h, cfg, before = interrupted(tmp_path)
    h.value = False  # Operator has independently settled/released the heater.
    assert recover(tmp_path, h, cfg)['state'] == 'recovered'
    saved = json.loads((tmp_path / 'control.json').read_text())
    assert saved['demand'] == before['demand']
    assert saved['last_trigger_at'] == before['last_trigger_at']
    assert saved['recovered_cycle'] == before['cycle']
    assert saved['cycle'] == {}
    assert h.calls == [True]
    resumed = runtime(tmp_path)
    run(resumed, h, cfg, seconds=1020)
    assert resumed.controller.state['start'] >= NOW+4500
    assert h.calls == [True]


@pytest.mark.parametrize('value', [True, None, 0, 'false'])
def test_active_unknown_and_non_boolean_readback_never_clear_journal(tmp_path, value):
    _, h, cfg, before = interrupted(tmp_path)
    h.value = value
    with pytest.raises(ValueError):
        recover(tmp_path, h, cfg)
    assert json.loads((tmp_path / 'control.json').read_text()) == before
    assert h.calls == [True]


@pytest.mark.parametrize('changes', [{'exclusive_owner_confirmed': False},
    {'pending_commands_settled': False}, {'pending_commands_settled': 1}, {'now': NOW-1}])
def test_confirmations_and_clock_are_required_before_readback(tmp_path, changes):
    _, h, cfg, before = interrupted(tmp_path)
    h.read_hot_water_boost = lambda: pytest.fail('Blocked recovery contacted heater')
    with pytest.raises(ValueError):
        recover(tmp_path, h, cfg, **changes)
    assert json.loads((tmp_path / 'control.json').read_text()) == before


def test_live_engine_lock_blocks_recovery_before_device_read(tmp_path):
    r, h, cfg = runtime(tmp_path), Heater(), house()
    run(r, h, cfg)
    h.read_hot_water_boost = lambda: pytest.fail('Locked recovery contacted heater')
    with pytest.raises(BlockingIOError):
        recover(tmp_path, h, cfg)


def test_mismatched_context_and_shadow_cycle_are_rejected(tmp_path):
    _, h, cfg, before = interrupted(tmp_path)
    h.read_hot_water_boost = lambda: pytest.fail('Invalid state contacted heater')
    cfg['heat_pump']['hot_water_control']['max_runtime_s'] += 1
    with pytest.raises(ValueError):
        recover(tmp_path, h, cfg)
    before['cycle']['mode'] = 'shadow'
    (tmp_path / 'control.json').write_text(json.dumps(before))
    with pytest.raises(ValueError):
        recover(tmp_path, h, house())


def test_recovery_of_settled_pending_start_does_not_invent_trigger_history(tmp_path):
    r, h, cfg = runtime(tmp_path), Heater(), house()
    run(r, h, cfg)
    h.deliver = False
    run(r, h, cfg, seconds=900)
    before = deepcopy(r.state)
    r.journal.lock.close()
    recover(tmp_path, h, cfg)
    saved = json.loads((tmp_path / 'control.json').read_text())
    assert 'last_trigger_at' not in saved
    assert saved['demand'] == before['demand']
    assert h.calls == [True]


def test_failed_recovery_save_preserves_original_state(tmp_path, monkeypatch):
    _, h, cfg, before = interrupted(tmp_path)
    h.value = False
    def fail(*args):
        raise OSError('private error')
    monkeypatch.setattr(Journal, 'save', fail)
    with pytest.raises(OSError):
        recover(tmp_path, h, cfg)
    assert json.loads((tmp_path / 'control.json').read_text()) == before


def test_changed_resolved_local_address_blocks_recovery_before_read(tmp_path):
    _, h, cfg, before = interrupted(tmp_path)
    h._host = 'different-heater.invalid'
    h.read_hot_water_boost = lambda: pytest.fail('Changed endpoint was contacted')
    with pytest.raises(ValueError):
        recover(tmp_path, h, cfg)
    assert json.loads((tmp_path / 'control.json').read_text()) == before


def cli():
    spec = importlib.util.spec_from_file_location('recover_cli', Path(__file__).resolve().parents[1] / 'scripts/recover_hot_water.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_refuses_missing_acknowledgements_before_reading_files(tmp_path, capsys):
    with pytest.raises(SystemExit) as error:
        cli().main(['--config', str(tmp_path/'missing'), '--journal', str(tmp_path/'missing-journal')])
    assert error.value.code == 2
    assert 'explicitly confirm' in capsys.readouterr().err


def test_cli_constructs_read_only_driver_and_sanitizes_failure(tmp_path, monkeypatch, capsys):
    import yaml
    import drivers.heatpump_nibe_local as nibe
    _, h, cfg, _ = interrupted(tmp_path)
    config = tmp_path / 'house.yaml'
    config.write_text(yaml.safe_dump(cfg))
    def factory(**kwargs):
        assert kwargs['control_enabled'] is False
        h.value = False
        return h
    monkeypatch.setattr(nibe, 'NibeLocalHeatPumpDriver', factory)
    module = cli()
    monkeypatch.setattr(module.time, 'time', lambda: NOW+1000)
    args = ['--config', str(config), '--journal', str(tmp_path/'control.json'),
            '--confirm-exclusive-ownership', '--confirm-pending-commands-settled']
    module.main(args)
    assert json.loads(capsys.readouterr().out)['state'] == 'recovered'
    config.write_text('bad: [')
    with pytest.raises(SystemExit):
        module.main(args)
    error = capsys.readouterr().err
    assert 'Recovery blocked' in error and 'never-publish' not in error
    assert h.calls == [True]
