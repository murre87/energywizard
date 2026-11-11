"""Registry freshness checks never need a live registry or container runtime."""
import hashlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

spec = importlib.util.spec_from_file_location('image_updates', Path(__file__).resolve().parents[1] / 'smartbox/image_updates.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ImageUpdates = module.ImageUpdates


def manifest(marker='current'):
    return {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
            'config': {'digest': marker}, 'layers': []}


def response(data, status=200, headers=None):
    r = requests.Response()
    r.status_code = status
    r._content = json.dumps(data).encode()
    r.headers.update(headers or {})
    return r


def digest(data):
    return 'sha256:' + hashlib.sha256(json.dumps(data).encode()).hexdigest()


def index(entries):
    return {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.index.v1+json',
            'manifests': [{'digest': d, 'platform': {'os': 'linux', 'architecture': arch}}
                          for arch, d in entries]}


def checker(running, replies, **extra):
    session = Mock()
    session.get.side_effect = replies
    clock = Mock(return_value=1000)
    env = {'EW_UPDATE_IMAGE': 'registry.example/team/ew:latest',
           'EW_RUNNING_IMAGE_DIGEST': running, 'EW_UPDATE_PLATFORM': 'linux/amd64', **extra}
    return ImageUpdates(env, session, clock)


def test_missing_metadata_makes_no_requests():
    c = ImageUpdates({}, Mock())
    assert c.check()['status'] == 'not_configured'
    c.session.get.assert_not_called()


def test_matching_manifest_and_cache_manual_cooldown():
    m = manifest()
    c = checker(digest(m), [response(m), response(m)])
    assert c.check()['status'] == 'up_to_date'
    c.clock.return_value += 31
    c.check()
    assert c.session.get.call_count == 1
    c.check(force=True)
    c.check(force=True)
    assert c.session.get.call_count == 2


def test_changed_manifest():
    old, new = manifest(), manifest('new')
    c = checker(digest(old), [response(new), response(old)])
    assert c.check()['status'] == 'update_available'


def test_platform_digest_matches_remote_index():
    current = digest(manifest())
    remote = index([('amd64', current), ('arm64', 'sha256:' + 'b' * 64)])
    c = checker(current, [response(remote)])
    assert c.check()['status'] == 'up_to_date'
    assert c.session.get.call_count == 1


def test_other_platform_change_does_not_mark_running_platform_outdated():
    current = digest(manifest())
    old = index([('amd64', current), ('arm64', 'sha256:' + 'b' * 64)])
    new = index([('amd64', current), ('arm64', 'sha256:' + 'c' * 64)])
    c = checker(digest(old), [response(new), response(old)])
    assert c.check()['status'] == 'up_to_date'


@pytest.mark.parametrize('remote', [index([('arm64', 'sha256:' + 'b' * 64)]),
                                    index([('amd64', 'sha256:' + 'b' * 64)] * 2),
                                    {'schemaVersion': 2, 'mediaType': 'bad'},
                                    {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.index.v1+json', 'manifests': [None]}])
def test_invalid_or_ambiguous_registry_data_is_error(remote):
    c = checker(digest(manifest()), [response(remote)])
    assert c.check()['status'] == 'error'


def test_error_replaces_green_status_but_retains_success_timestamp():
    m = manifest()
    c = checker(digest(m), [response(m), requests.Timeout('secret')])
    assert c.check()['last_success_at'] == 1000
    c.clock.return_value += c.interval
    result = c.check()
    assert result['status'] == 'error'
    assert result['last_success_at'] == 1000
    assert 'secret' not in json.dumps(result)


def test_anonymous_bearer_challenge_and_credentials_not_exposed():
    m = manifest()
    challenge = response({}, 401, {'WWW-Authenticate': 'Bearer realm="https://registry.example/token",service="registry"'})
    c = checker(digest(m), [challenge, response({'token': 'private-token'}), response(m)],
                EW_UPDATE_REGISTRY_USERNAME='user', EW_UPDATE_REGISTRY_PASSWORD='password')
    result = c.check()
    assert result['status'] == 'up_to_date'
    assert c.session.get.call_args_list[1].kwargs['auth'] == ('user', 'password')
    assert c.session.get.call_args_list[2].kwargs['headers']['Authorization'] == 'Bearer private-token'
    assert 'private-token' not in json.dumps(result)
    assert all(call.kwargs['allow_redirects'] is False for call in c.session.get.call_args_list)


def test_credentials_never_forwarded_to_other_token_host():
    challenge = response({}, 401, {'WWW-Authenticate': 'Bearer realm="https://auth.other.example/token"'})
    c = checker(digest(manifest()), [challenge], EW_UPDATE_REGISTRY_PASSWORD='secret')
    assert c.check()['status'] == 'error'
    assert c.session.get.call_count == 1


def test_fetched_running_digest_is_verified():
    c = checker('sha256:' + 'a' * 64, [response(manifest('new')), response(manifest('unexpected'))])
    assert c.check()['status'] == 'error'


@pytest.mark.parametrize('configured, expected', [('nonsense', 21600), ('0', 300), ('999999999', 604800), ('3600', 3600)])
def test_interval_validation(configured, expected):
    c = ImageUpdates({'EW_UPDATE_INTERVAL_SECONDS': configured}, Mock())
    assert c.interval == expected


def test_invalid_current_digest_cannot_claim_up_to_date():
    c = checker('latest', [])
    assert c.check()['status'] == 'error'
    c.session.get.assert_not_called()


def test_concurrent_check_does_not_start_another_request():
    c = checker(digest(manifest()), [])
    c.lock.acquire()
    try:
        c.check(force=True)
        c.session.get.assert_not_called()
    finally:
        c.lock.release()
