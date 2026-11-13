"""Experimental CPU rejection stays distinct from numerical/infrastructure failure."""
import importlib.util
import json
from pathlib import Path
import subprocess
from unittest.mock import Mock

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
