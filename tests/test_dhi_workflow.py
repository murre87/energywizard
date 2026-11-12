"""DHI runner credentials stay out of fork jobs and uploaded artifacts."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_dhi_credentials_require_trusted_pr_and_signatures():
    workflow = yaml.load((ROOT / '.github/workflows/dhi.yml').read_text(encoding='utf-8'),
                         Loader=yaml.BaseLoader)
    assert 'pull_request_target' not in workflow['on']
    assert workflow['permissions'] == {'contents': 'read'}
    signatures = workflow['jobs']['signatures']
    assert "github.event_name != 'pull_request'" in signatures['if']
    assert 'github.event.pull_request.head.repo.full_name == github.repository' in signatures['if']
    assert workflow['jobs']['runtime']['needs'] == 'signatures'
    logins = []
    for job in workflow['jobs'].values():
        assert 'env' not in job  # No job-wide PAT for arbitrary commands or containers.
        for step in job['steps']:
            if 'secrets.' in str(step):
                assert step['uses'].startswith('docker/login-action@')
                assert step['with']['password'] == '${{ secrets.DHI_IO }}'
                logins.append(step)
            if step.get('uses', '').startswith('actions/upload-artifact@'):
                assert all(line.startswith('${{ runner.temp }}/dhi-')
                           for line in step['with']['path'].splitlines() if line)
                assert '.docker' not in step['with']['path']
    assert len(logins) == 3
