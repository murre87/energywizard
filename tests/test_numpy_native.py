"""Native qualification rejects invalid comparisons and cleans up failed probes."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import subprocess
from unittest.mock import Mock
import json
import sys

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


@pytest.mark.parametrize('target', ['candidate', 'candidate-openblas'])
def test_selected_variant_is_built_measured_and_identified(monkeypatch,tmp_path,target):
    output=tmp_path/'report.json'
    monkeypatch.setattr(sys,'argv',['check_numpy_native.py','--candidate-target',target,'--output',str(output)])
    run=Mock(return_value=Mock(stdout='sha256:tested-image\n'))
    monkeypatch.setattr(native.subprocess,'run',run)
    probe=Mock(side_effect=[{'status':'passed'},result('2.3.5',2),{'status':'passed'},result('2.4.6',1)])
    monkeypatch.setattr(native,'run_probe',probe)
    native.main()
    report=json.loads(output.read_text())
    assert report['candidate_target']==target
    assert report['candidate_over_capped_ratio']=={'solve':.5}
    builds=[call.args[0] for call in run.call_args_list if call.args[0][1]=='build']
    assert [cmd[cmd.index('--target')+1] for cmd in builds]==['capped',target]
    assert probe.call_args_list[-1].args==('ew-numpy-native-'+target,'/benchmark.py')
    assert report['results'][target]['image_id']=='sha256:tested-image'
