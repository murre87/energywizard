"""Experimental CPU rejection stays distinct from numerical/infrastructure failure."""
import importlib.util
import json
from pathlib import Path
import subprocess
from unittest.mock import Mock
import sys

import pytest

spec=importlib.util.spec_from_file_location('legacy',Path(__file__).resolve().parents[1]/'scripts/check_numpy_compat.py')
legacy=importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)
FAULT='qemu: uncaught target signal 4 (Illegal instruction) - core dumped'


@pytest.mark.parametrize('outcome',[Mock(returncode=132,stdout='',stderr=FAULT),
    subprocess.TimeoutExpired('probe',20,stderr=FAULT.encode())])
def test_explicit_experiment_records_only_cpu_rejection(monkeypatch,tmp_path,outcome):
    probe=Mock(side_effect=outcome) if isinstance(outcome,Exception) else Mock(return_value=outcome)
    monkeypatch.setattr(legacy,'run_image',probe)
    monkeypatch.setattr(legacy.subprocess,'run',Mock(return_value=Mock(stdout='sha256:tested\n')))
    path=tmp_path/'result.json'
    assert legacy.candidate_result('candidate-openblas',path)['status']=='rejected_cpu'
    assert json.loads(path.read_text())['image_id']=='sha256:tested'


@pytest.mark.parametrize('error',['AssertionError: numerical result differs','network failed',''])
def test_other_failures_remain_failures(monkeypatch,tmp_path,error):
    monkeypatch.setattr(legacy,'run_image',Mock(return_value=Mock(returncode=1,stdout='',stderr=error)))
    with pytest.raises(RuntimeError):legacy.candidate_result('candidate-openblas',tmp_path/'result.json')


def test_default_cpu_rejection_is_still_a_failure(monkeypatch):
    monkeypatch.setattr(legacy,'run_image',Mock(return_value=Mock(returncode=132,stdout='',stderr=FAULT)))
    with pytest.raises(RuntimeError):legacy.candidate_result('candidate-openblas')


@pytest.mark.parametrize('model',legacy.CPU_MODELS)
def test_cpu_selection_is_explicit_and_failed_container_is_removed(monkeypatch,model):
    invoke=Mock(side_effect=[subprocess.TimeoutExpired('probe',15),Mock()])
    monkeypatch.setattr(legacy.subprocess,'run',invoke)
    with pytest.raises(subprocess.TimeoutExpired):legacy.run_image('candidate-openblas',cpu_model=model)
    cmd=invoke.call_args_list[0].args[0]
    assert cmd[cmd.index('-cpu')+1]==legacy.CPU_MODELS[model]
    assert cmd[-1]=='/smoke.py' and cmd[cmd.index('--network')+1]=='none'
    name=cmd[cmd.index('--name')+1]
    assert invoke.call_args_list[1].args[0]==['docker','rm','-f',name]


def test_successful_output_does_not_enable_rejection_recording(monkeypatch,tmp_path):
    monkeypatch.setattr(legacy,'run_image',Mock(return_value=Mock(returncode=132,stdout='',stderr=FAULT)))
    output=tmp_path/'result.json'
    with pytest.raises(RuntimeError):legacy.candidate_result('candidate-openblas',cpu_model='intel-v1',output=output)
    assert not output.exists()


@pytest.mark.parametrize('model',['intel-v1','amd-3dnow'])
def test_all_controls_use_selected_model_before_strict_candidate(monkeypatch,tmp_path,model):
    output=tmp_path/'result.json'
    monkeypatch.setattr(sys,'argv',['probe','--candidate-target','candidate-openblas','--cpu-model',model,'--output',str(output)])
    monkeypatch.setattr(legacy.subprocess,'run',Mock(return_value=Mock(stdout='sha256:tested\n')))
    probe=Mock(side_effect=[Mock(returncode=0),Mock(returncode=132,stdout='',stderr=FAULT),
        Mock(returncode=0,stdout='capped passed'),Mock(returncode=0,stdout='candidate passed',stderr='')])
    monkeypatch.setattr(legacy,'run_image',probe)
    legacy.main()
    assert all(call.kwargs['cpu_model']==model for call in probe.call_args_list)
    assert [call.args[0] for call in probe.call_args_list]==['upstream','upstream','capped','candidate-openblas']
    result=json.loads(output.read_text())
    assert result['status']=='compatible_smoke' and result['cpu_model']==legacy.CPU_MODELS[model]
    assert result['controls']==dict(python_startup='passed',capped_smoke='passed',upstream_cpu_rejection='reproduced')


def test_passing_upstream_control_rejects_the_experiment(monkeypatch):
    monkeypatch.setattr(sys,'argv',['probe','--candidate-target','candidate-openblas','--cpu-model','intel-v1'])
    monkeypatch.setattr(legacy.subprocess,'run',Mock())
    probe=Mock(side_effect=[Mock(returncode=0),Mock(returncode=0)])
    monkeypatch.setattr(legacy,'run_image',probe)
    with pytest.raises(RuntimeError,match='unexpectedly passed'):legacy.main()
    assert probe.call_count==2
