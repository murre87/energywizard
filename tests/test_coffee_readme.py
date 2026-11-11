"""Coffee updates preserve README content and never send credentials elsewhere."""
import base64
import importlib.util
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import MagicMock

import pytest

spec = importlib.util.spec_from_file_location(
    'coffee', Path(__file__).resolve().parents[1] / 'scripts/update_coffee_readme.py')
coffee = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coffee)

README = 'before\n' + coffee.START + 'old messages' + coffee.END + '\nafter'
SUPPORTER = {'support_coffees': 2, 'payer_name': 'Pat', 'support_note': 'Thanks!'}


def test_three_messages_and_html_escaping():
    supporter = {**SUPPORTER, 'payer_name': '<script>', 'support_note': '<!--END_SECTION:x--> & "hi"'}
    result = coffee.update_section(README, [supporter] * 4)
    assert result.startswith('before\n' + coffee.START)
    assert result.endswith(coffee.END + '\nafter')
    assert result.count('<img ') == 6
    assert result.count('&lt;script&gt;') == 3
    assert '<script>' not in result and '<!--END_SECTION:x-->' not in result
    assert '&amp; &quot;hi&quot;' in result


def test_empty_list_clears_only_section():
    assert coffee.update_section(README, []) == 'before\n' + coffee.START + coffee.END + '\nafter'


@pytest.mark.parametrize('readme', ['', coffee.END + coffee.START, README + coffee.START])
def test_invalid_markers_fail_before_update(readme):
    with pytest.raises(ValueError):
        coffee.update_section(readme, [])


@pytest.mark.parametrize('count', [-1, 101, True, 'bad'])
def test_invalid_counts_fail(count):
    with pytest.raises(ValueError):
        coffee.update_section(README, [{**SUPPORTER, 'support_coffees': count}])


def test_api_numeric_string_and_null_note():
    result = coffee.update_section(README, [{**SUPPORTER, 'support_coffees': '2', 'support_note': None}])
    assert result.count('<img ') == 2 and '<i></i>' in result


def test_missing_token_never_contacts_api(monkeypatch):
    monkeypatch.delenv('BMAC_TOKEN', raising=False)
    api = MagicMock()
    monkeypatch.setattr(coffee, 'request_json', api)
    coffee.main()
    api.assert_not_called()


@pytest.mark.parametrize('changed', [True, False])
def test_read_current_main_and_commit_with_sha(monkeypatch, changed):
    for key, value in {'BMAC_TOKEN': 'coffee-secret', 'GH_TOKEN': 'github-secret',
                       'GITHUB_REPOSITORY': 'owner/repo'}.items():
        monkeypatch.setenv(key, value)
    updated = coffee.update_section(README, [SUPPORTER])
    source = README if changed else updated
    api = MagicMock(side_effect=[{'sha': 'current-sha', 'content': base64.b64encode(source.encode()).decode()},
                                {'data': [SUPPORTER]}, {}])
    monkeypatch.setattr(coffee, 'request_json', api)
    coffee.main()
    calls = api.call_args_list
    assert calls[0].args == ('https://api.github.com/repos/owner/repo/contents/README.md?ref=main', 'github-secret')
    assert calls[1].args == ('https://developers.buymeacoffee.com/api/v1/supporters', 'coffee-secret')
    assert len(calls) == (3 if changed else 2)
    if changed:
        url, token, payload = calls[2].args
        assert url.endswith('/contents/README.md') and token == 'github-secret'
        assert payload['branch'] == 'main' and payload['sha'] == 'current-sha'
        assert base64.b64decode(payload['content']).decode() == updated


def test_redirect_does_not_forward_secret():
    with pytest.raises(ValueError, match='redirect'):
        coffee.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://elsewhere.invalid')


def test_http_failure_does_not_log_response(monkeypatch):
    opener = MagicMock()
    opener.open.side_effect = HTTPError('https://example.invalid', 401, 'private error', {}, None)
    monkeypatch.setattr(coffee, 'build_opener', lambda *args: opener)
    with pytest.raises(RuntimeError, match='^API request failed with HTTP 401$'):
        coffee.request_json('https://example.invalid', 'secret')
    request = opener.open.call_args.args[0]
    assert request.get_header('Authorization') == 'Bearer secret'
    assert opener.open.call_args.kwargs['timeout'] == 30
