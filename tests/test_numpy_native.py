"""Native qualification rejects invalid comparisons and cleans up failed probes."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location(
    'native', Path(__file__).resolve().parents[1] / 'scripts/check_numpy_native.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


def result(version, elapsed=1):
    return {'architecture': 'aarch64', 'versions': {'numpy': version},
            'timings': {'solve': {'median_seconds': elapsed}}}


def test_ratios_compare_same_architecture():
    assert native.compare(result('2.3.5', 2), result('2.4.6', 3)) == {'solve': 1.5}


@pytest.mark.parametrize('changes', [
    {'architecture': 'x86_64'}, {'versions': {'numpy': '2.3.5'}},
    {'timings': {}}, {'timings': {'other': {'median_seconds': 1}}},
])
def test_invalid_comparison_fails(changes):
    candidate = {**result('2.4.6'), **deepcopy(changes)}
    with pytest.raises(ValueError):
        native.compare(result('2.3.5'), candidate)


@pytest.mark.parametrize('elapsed', [0, -1, float('nan'), float('inf'), '1'])
def test_invalid_measurement_fails(elapsed):
    with pytest.raises(ValueError):
        native.compare(result('2.3.5'), result('2.4.6', elapsed))


@pytest.mark.parametrize('outcome', [subprocess.TimeoutExpired('probe', 180),
                                    subprocess.CalledProcessError(1, 'probe')])
def test_failed_probe_is_removed(monkeypatch, outcome):
    run = Mock(side_effect=[outcome, Mock(returncode=0)])
    monkeypatch.setattr(native.subprocess, 'run', run)
    with pytest.raises(type(outcome)):
        native.run_probe('evaluation-image', '/smoke.py')
    command = run.call_args_list[0].args[0]
    assert command[command.index('--network') + 1] == 'none'
    assert command[command.index('--memory') + 1] == '2g'
    assert command[-3:] == ['evaluation-image', 'python', '/smoke.py']
    name = command[command.index('--name') + 1]
    assert name.startswith('ew-numpy-native-')
    assert run.call_args_list[1].args[0] == ['docker', 'rm', '-f', name]
