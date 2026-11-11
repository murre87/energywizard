"""DHI verification preserves signature checks and platform binding."""
import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('vex', ROOT / 'scripts/verify_dhi_vex.py')
vex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vex)


def test_all_optional_images_share_pinned_bases():
    assert set(vex.pinned_bases(ROOT)) == {'builder', 'runtime'}


def test_full_verification_has_no_fallback(tmp_path):
    run = Mock(return_value=Mock(returncode=0, stdout='verified', stderr=''))
    assert vex.verify('scout', 'image', 'linux/amd64', 'key', tmp_path / 'vex.json', run) == 'docker-key-and-transparency-log'
    command = run.call_args.args[0]
    assert '--verify' in command and command[command.index('--key') + 1] == 'key'
    assert '--skip-tlog' not in command and run.call_count == 1


def test_only_missing_log_entry_allows_key_only_mode(tmp_path):
    run = Mock(side_effect=[Mock(returncode=1, stdout='', stderr='no matching signatures: signature not found in transparency log'),
                            Mock(returncode=0, stdout='key verified', stderr='')])
    assert vex.verify('scout', 'image', 'linux/amd64', 'key', tmp_path / 'vex.json', run) == 'docker-key-only-public-log-entry-missing'
    fallback = run.call_args.args[0]
    assert '--verify' in fallback and '--key' in fallback and '--skip-tlog' in fallback


@pytest.mark.parametrize('error', ['bad signature', 'not logged in', 'connection failed'])
def test_other_failures_never_relax_verification(tmp_path, error):
    run = Mock(return_value=Mock(returncode=1, stdout='', stderr=error))
    with pytest.raises(RuntimeError):
        vex.verify('scout', 'image', 'linux/arm64', 'key', tmp_path / 'vex.json', run)
    assert run.call_count == 1


def test_key_verification_failure_is_fatal(tmp_path):
    run = Mock(side_effect=[Mock(returncode=1, stdout='', stderr='no matching signatures: signature not found in transparency log'),
                            Mock(returncode=1, stdout='', stderr='bad signature')])
    with pytest.raises(RuntimeError, match='Docker-key verification failed'):
        vex.verify('scout', 'image', 'linux/amd64', 'key', tmp_path / 'vex.json', run)


def document(digest='abc', status='under_investigation'):
    return {'@context': 'https://openvex.dev/ns/v0.2.0',
            'statements': [{'products': [{'@id': 'image@sha256:' + digest}], 'status': status}]}


def test_investigations_are_retained():
    assert vex.validate_vex(document(), 'abc') == {'under_investigation': 1}


@pytest.mark.parametrize('data', [{}, {'statements': []}, document('other'), document(status='unknown')])
def test_invalid_or_wrong_platform_vex_fails(data):
    with pytest.raises(ValueError):
        vex.validate_vex(data, 'abc')
