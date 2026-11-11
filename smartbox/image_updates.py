"""Read-only OCI registry checks, independent of the container runtime."""
import hashlib
import os
import platform
import re
import threading
import time
from urllib.parse import urlparse

import requests

ACCEPT = ', '.join([
    'application/vnd.oci.image.index.v1+json',
    'application/vnd.docker.distribution.manifest.list.v2+json',
    'application/vnd.oci.image.manifest.v1+json',
    'application/vnd.docker.distribution.manifest.v2+json',
])
DIGEST = re.compile(r'sha256:[0-9a-f]{64}')
IMAGE = re.compile(r'([a-z0-9.-]+(?::[0-9]+)?)/([a-z0-9._/-]+):([\w][\w.-]{0,127})', re.ASCII)


class ImageUpdates:
    def __init__(self, env=None, session=None, clock=time.time):
        env = os.environ if env is None else env
        self.image = env.get('EW_UPDATE_IMAGE', '').strip()
        self.running = env.get('EW_RUNNING_IMAGE_DIGEST', '').strip()
        arch = {'x86_64': 'amd64', 'aarch64': 'arm64', 'AMD64': 'amd64'}.get(platform.machine(), platform.machine())
        self.platform = env.get('EW_UPDATE_PLATFORM', f'{platform.system().lower()}/{arch}')
        self.username = env.get('EW_UPDATE_REGISTRY_USERNAME', '')
        self.password = env.get('EW_UPDATE_REGISTRY_PASSWORD', '')
        try:
            self.interval = max(300, min(604800, int(env.get('EW_UPDATE_INTERVAL_SECONDS', '21600'))))
        except ValueError:
            self.interval = 21600
        self.session = session or requests.Session()
        self.clock = clock
        self.lock = threading.Lock()
        self.attempted_at = None
        self.success_at = None
        self.result = {'status': 'not_configured'}

    def snapshot(self):
        return {**self.result, 'image': self.image, 'running_digest': self.running,
                'checked_at': self.attempted_at, 'last_success_at': self.success_at,
                'interval_seconds': self.interval}

    def _get(self, url, **kwargs):
        return self.session.get(url, timeout=(3, 10), allow_redirects=False, **kwargs)

    def _manifest(self, registry, repo, ref):
        url = f'https://{registry}/v2/{repo}/manifests/{ref}'
        headers = {'Accept': ACCEPT}
        response = self._get(url, headers=headers)
        if response.status_code == 401:
            challenge = response.headers.get('WWW-Authenticate', '')
            if not challenge.lower().startswith('bearer '):
                raise ValueError('Registry does not offer bearer authentication')
            fields = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
            realm = fields.get('realm', '')
            parsed = urlparse(realm)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                raise ValueError('Invalid registry authentication endpoint')
            # Never forward private registry credentials to another host or redirects.
            auth = None
            if self.username or self.password:
                if parsed.netloc != registry:
                    raise ValueError('Credential authentication requires a same-host token endpoint')
                auth = (self.username, self.password)
            token_response = self._get(realm, params={'service': fields.get('service', ''),
                                                     'scope': f'repository:{repo}:pull'}, auth=auth)
            token_response.raise_for_status()
            token_data = token_response.json()
            if not isinstance(token_data, dict):
                raise ValueError('Invalid registry token response')
            token = token_data.get('token') or token_data.get('access_token')
            if not isinstance(token, str) or not token:
                raise ValueError('Missing registry access token')
            headers['Authorization'] = f'Bearer {token}'
            response = self._get(url, headers=headers)
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError('Unexpected registry response')
        digest = 'sha256:' + hashlib.sha256(response.content).hexdigest()
        if DIGEST.fullmatch(ref) and digest != ref:
            raise ValueError('Registry manifest digest mismatch')
        manifest = response.json()
        if not isinstance(manifest, dict) or manifest.get('schemaVersion') != 2:
            raise ValueError('Unsupported registry manifest')
        if manifest.get('mediaType') not in ACCEPT.split(', '):
            raise ValueError('Unsupported registry media type')
        is_index = manifest['mediaType'] in ACCEPT.split(', ')[:2]
        if is_index:
            entries = manifest.get('manifests')
            if not isinstance(entries, list) or not all(isinstance(e, dict) and isinstance(e.get('platform', {}), dict) for e in entries):
                raise ValueError('Invalid registry index')
        elif not isinstance(manifest.get('config'), dict) or not isinstance(manifest.get('layers'), list):
            raise ValueError('Invalid image manifest')
        return digest, manifest

    def _platform_digest(self, digest, manifest):
        if manifest['mediaType'] not in ACCEPT.split(', ')[:2]:
            return digest
        parts = self.platform.split('/')
        if len(parts) not in (2, 3):
            raise ValueError('Invalid platform configuration')
        candidates = []
        for item in manifest['manifests']:
            p = item.get('platform', {})
            if p.get('os') == parts[0] and p.get('architecture') == parts[1]:
                if len(parts) == 2 or p.get('variant') == parts[2]:
                    candidates.append(item['digest'])
        if len(candidates) != 1 or not DIGEST.fullmatch(candidates[0]):
            raise ValueError('Platform missing or ambiguous in registry manifest')
        return candidates[0]

    def check(self, force=False):
        if not self.lock.acquire(blocking=False):
            return self.snapshot()
        try:
            if not self.image or not self.running:
                self.result = {'status': 'not_configured'}
                return self.snapshot()
            now = self.clock()
            cooldown = 30 if force else self.interval
            if self.attempted_at is not None and now - self.attempted_at < cooldown:
                return self.snapshot()
            self.attempted_at = now
            self.result = {'status': 'checking'}
            match = IMAGE.fullmatch(self.image)
            if not match or not DIGEST.fullmatch(self.running):
                self.result = {'status': 'error', 'error': 'Invalid image reference or running SHA-256 manifest digest.'}
                return self.snapshot()
            registry, repo, tag = match.groups()
            try:
                remote, manifest = self._manifest(registry, repo, tag)
                current = self.running
                latest = remote
                if current != remote:
                    latest = self._platform_digest(remote, manifest)
                    if current != latest:
                        current_digest, current_manifest = self._manifest(registry, repo, current)
                        current = self._platform_digest(current_digest, current_manifest)
                self.success_at = now
                self.result = {'status': 'up_to_date' if current == latest else 'update_available',
                               'latest_digest': remote, 'platform': self.platform}
            except (requests.RequestException, ValueError, KeyError, TypeError):
                # Do not include response bodies, URLs, or credential-bearing exceptions.
                self.result = {'status': 'error', 'error': 'Unable to check registry. Check image, platform, credentials and connectivity.'}
            return self.snapshot()
        finally:
            self.lock.release()
