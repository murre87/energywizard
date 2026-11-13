import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('dhi_image_audit', ROOT / 'scripts/audit_dhi_images.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def evidence():
    return {'results': [{'component': c, 'platform': 'linux/arm64', 'status': 'passed',
                         'root_owned_volume': 'passed', 'image_id': 'sha256:' + str(i)*64}
                        for i,c in enumerate(sorted(audit.COMPONENTS),1)]}


@pytest.mark.parametrize('change', ['missing','duplicate','wrong_platform','failed','tag','volume'])
def test_incomplete_or_mutable_runtime_evidence_is_rejected(change):
    doc=evidence()
    if change=='missing': doc['results'].pop()
    if change=='duplicate': doc['results'][0]['component']=doc['results'][1]['component']
    if change=='wrong_platform': doc['results'][0]['platform']='linux/amd64'
    if change=='failed': doc['results'][0]['status']='failed'
    if change=='tag': doc['results'][0]['image_id']='ew-dhi:latest'
    if change=='volume': doc['results'][0]['root_owned_volume']='unknown'
    with pytest.raises(ValueError): audit.tested_images(doc,'linux/arm64')


def fake_runner(failure=None):
    calls=[]
    def run(command,check):
        calls.append(command)
        image=command[2]
        target=Path(command[-1]); component=target.name
        summary={'image':image,'python_findings':[],'blocked_image_findings':[],'total_scanner_matches':7}
        if component==failure: summary['blocked_image_findings']=[{'id':'CVE-2026-12345'}]
        (target/'summary.json').write_text(json.dumps(summary))
        return Mock(returncode=int(component==failure))
    return run,calls


def test_all_four_immutable_images_use_existing_auditor_and_retain_raw_counts(tmp_path):
    run,calls=fake_runner()
    report=audit.audit(evidence(),'linux/arm64',tmp_path,run)
    assert len(calls)==4 and all(c[1].endswith('audit_image.py') and c[2].startswith('sha256:') for c in calls)
    assert len({c[-1] for c in calls})==4
    assert all(r['status']=='passed' and r['total_scanner_matches']==7 for r in report['results'])
    assert json.loads((tmp_path/'summary.json').read_text())==report


def test_one_blocking_image_fails_but_does_not_skip_the_other_audits(tmp_path):
    run,calls=fake_runner('ewapp')
    report=audit.audit(evidence(),'linux/arm64',tmp_path,run)
    assert len(calls)==4
    assert [r['component'] for r in report['results'] if r['status']=='failed']==['ewapp']


def test_missing_fresh_summary_cannot_reuse_old_success(tmp_path):
    run,_=fake_runner()
    audit.audit(evidence(),'linux/arm64',tmp_path,run)
    report=audit.audit(evidence(),'linux/arm64',tmp_path,Mock(return_value=Mock(returncode=0)))
    assert all(r['status']=='failed' and not r['matching_summary'] for r in report['results'])


@pytest.mark.parametrize('failure', ['wrong_image','nonzero','malformed'])
def test_untrustworthy_summary_fails_its_image_without_skipping_others(tmp_path,failure):
    delegate,calls=fake_runner()
    def run(command,check):
        result=delegate(command,check)
        folder=Path(command[-1])
        if folder.name=='ewapp':
            path=folder/'summary.json'
            summary=json.loads(path.read_text())
            if failure=='wrong_image': summary['image']='sha256:'+'f'*64
            if failure=='malformed': summary=[]
            path.write_text(json.dumps(summary))
            if failure=='nonzero': result.returncode=1
        return result
    report=audit.audit(evidence(),'linux/arm64',tmp_path,run)
    assert len(calls)==4
    assert [r['component'] for r in report['results'] if r['status']=='failed']==['ewapp']


def test_workflow_audits_after_runtime_and_retains_reports_on_failure():
    workflow=yaml.load((ROOT/'.github/workflows/dhi.yml').read_text(),Loader=yaml.BaseLoader)
    steps=workflow['jobs']['runtime']['steps']
    runtime=next(i for i,s in enumerate(steps) if 'verify_dhi_runtime.py' in s.get('run',''))
    scan=next(i for i,s in enumerate(steps) if 'audit_dhi_images.py' in s.get('run',''))
    assert runtime<scan and '--runtime-results' in steps[scan]['run']
    upload=next(s for s in steps if s.get('uses','').startswith('actions/upload-artifact@'))
    assert upload['if']=='always()' and '/dhi-audit/**/*.json' in upload['with']['path']
