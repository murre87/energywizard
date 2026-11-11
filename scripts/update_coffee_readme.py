"""Update only the coffee section using the existing API, without npm actions."""
import base64
from html import escape
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

START = '<!--START_SECTION:buy-me-a-coffee-->'
END = '<!--END_SECTION:buy-me-a-coffe-->'  # Existing README marker spelling.
LOGO = 'https://github.com/akosbalasko/coffee-to-file/blob/main/assets/bmc-logo.png?raw=true'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('API redirects are not allowed')


def request_json(url, token, payload=None):
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json',
               'User-Agent': 'EnergyWizard-coffee-readme'}
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    if data is not None:
        headers['Content-Type'] = 'application/json'
    request = Request(url, data=data, headers=headers, method='GET' if data is None else 'PUT')
    try:
        with build_opener(NoRedirect()).open(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as error:
        # Never log response bodies, request headers, supporter data or tokens.
        raise RuntimeError(f'API request failed with HTTP {error.code}') from None
    except URLError:
        raise RuntimeError('API connection failed') from None


def update_section(readme, supporters):
    if readme.count(START) != 1 or readme.count(END) != 1:
        raise ValueError('Expected exactly one coffee section')
    start = readme.index(START) + len(START)
    end = readme.index(END)
    if end < start:
        raise ValueError('Coffee section markers are reversed')
    if not isinstance(supporters, list):
        raise ValueError('Invalid supporters response')
    messages = []
    for supporter in supporters[:3]:
        count = supporter['support_coffees']
        if isinstance(count, str) and count.isdecimal():
            count = int(count)
        if type(count) is not int or not 0 <= count <= 100:
            raise ValueError('Invalid coffee count')
        name, note = supporter.get('payer_name') or '', supporter.get('support_note') or ''
        if not isinstance(name, str) or not isinstance(note, str):
            raise ValueError('Invalid supporter text')
        coffees = f'<img src="{LOGO}" width="30">' * count
        messages.append(f'<div>{coffees} from <b>{escape(name)}</b> </div>  '
                        f'<div><i>{escape(note)}</i></div><br>')
    return readme[:start] + '\n'.join(messages) + readme[end:]


def main():
    token = os.environ.get('BMAC_TOKEN', '')
    if not token:
        print('Coffee token is not configured; skipping')
        return
    repository = os.environ['GITHUB_REPOSITORY']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Invalid repository')
    github_token = os.environ['GH_TOKEN']
    url = f'https://api.github.com/repos/{repository}/contents/README.md'
    # Read current main and use its SHA, so concurrent edits cannot be overwritten.
    current = request_json(url + '?ref=main', github_token)
    readme = base64.b64decode(current['content']).decode('utf-8')
    supporters = request_json('https://developers.buymeacoffee.com/api/v1/supporters', token)
    updated = update_section(readme, supporters['data'])
    if updated == readme:
        print('Coffee section is unchanged')
        return
    request_json(url, github_token, {
        'message': 'Buy me a Coffee messages updated', 'branch': 'main', 'sha': current['sha'],
        'content': base64.b64encode(updated.encode('utf-8')).decode('ascii'),
        'committer': {'name': 'Buy Me a Coffee Readme action',
                      'email': 'noreply@buymeacoffeereadmeaction.com'},
    })
    print('Coffee section updated')


if __name__ == '__main__':
    main()
