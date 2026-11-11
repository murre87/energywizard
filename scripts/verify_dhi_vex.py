"""Verify the pinned DHI bases and retain signed-VEX evidence for both platforms.

Uses Docker/Scout's normal login, never reads authentication files. Docker's
documented key-only mode is used only for the exact missing-transparency-entry
error; all other failures stop verification. No vulnerability gate is modified.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.request import urlopen

KEY_URL = 'https://registry.scout.docker.com/keyring/dhi/latest.pub'
COMPONENTS = ('smartbox', 'webdashboard', 'ewapp', 'telemetry-collector')


def pinned_bases(root):
    refs = None
    for component in COMPONENTS:
        text = (root / component / 'Dockerfile.dhi').read_text(encoding='utf-8')
        found = re.findall(r'^FROM (dhi\.io/python:[^\s@]+@sha256:[0-9a-f]{64})(?: AS builder)?$', text, re.M)
        if len(found) != 2 or (refs is not None and found != refs):
            raise ValueError('Expected identical pinned builder/runtime bases in all DHI Dockerfiles')
        refs = found
    return dict(zip(('builder', 'runtime'), refs))


def verify(scout, reference, platform, key, target, run=subprocess.run):
    command = [scout, 'vex', 'get', 'registry://' + reference, '--verify',
               '--key', str(key), '--platform', platform, '--output', str(target)]
    result = run(command, capture_output=True, text=True, timeout=180)
    log = result.stdout + result.stderr
    target.with_suffix('.verification.log').write_text(log, encoding='utf-8')
    if result.returncode == 0:
        return 'docker-key-and-transparency-log'
    if 'no matching signatures: signature not found in transparency log' not in log:
        raise RuntimeError(f'Verification failed for {reference} ({platform}); see retained log')
    # https://docs.docker.com/dhi/how-to/verify/#handle-missing-transparency-log-entries
    result = run(command + ['--skip-tlog'], capture_output=True, text=True, timeout=180)
    target.with_suffix('.key-only.log').write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError(f'Docker-key verification failed for {reference} ({platform})')
    return 'docker-key-only-public-log-entry-missing'


def validate_vex(data, digest):
    statements = data.get('statements')
    if data.get('@context') != 'https://openvex.dev/ns/v0.2.0' or not statements:
        raise ValueError('Missing OpenVEX statements')
    for statement in statements:
        # Do not apply an image-wide document to a different platform or digest.
        products = json.dumps(statement.get('products', []))
        if digest not in products:
            raise ValueError('VEX product does not match the selected platform digest')
        if statement.get('status') not in ('not_affected', 'affected', 'fixed', 'under_investigation'):
            raise ValueError('Unknown VEX status')
    return dict(Counter(row['status'] for row in statements))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scout', default='docker-scout')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'summary.json').unlink(missing_ok=True)
    key = folder / 'docker-signing-key.pub'
    with urlopen(KEY_URL, timeout=30) as response:
        key_bytes = response.read()
    key.write_bytes(key_bytes)
    results = []
    for name, reference in pinned_bases(Path(__file__).resolve().parents[1]).items():
        manifest = subprocess.run(['docker', 'buildx', 'imagetools', 'inspect', reference, '--raw'],
                                  check=True, capture_output=True, text=True, timeout=60)
        index = json.loads(manifest.stdout)
        (folder / f'{name}-index.json').write_text(manifest.stdout, encoding='utf-8')
        for arch in ('amd64', 'arm64'):
            matches = [m['digest'] for m in index['manifests']
                       if m.get('platform') == {'architecture': arch, 'os': 'linux'}]
            if len(matches) != 1:
                raise ValueError(f'Missing or ambiguous {arch} manifest')
            target = folder / f'{name}-{arch}.json'
            target.unlink(missing_ok=True)  # A failed attempt must not reuse stale VEX.
            mode = verify(args.scout, reference, 'linux/' + arch, key, target)
            data = json.loads(target.read_text(encoding='utf-8'))
            counts = validate_vex(data, matches[0].removeprefix('sha256:'))
            results.append({'base': name, 'reference': reference, 'platform': 'linux/' + arch,
                            'manifest_digest': matches[0], 'verification': mode,
                            'vex_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                            'statuses': counts,
                            'unresolved': [s['vulnerability']['name'] for s in data['statements']
                                           if s['status'] in ('affected', 'under_investigation')]})
    summary = {'checked_at': datetime.now(timezone.utc).isoformat(), 'key_url': KEY_URL,
               'key_sha256': hashlib.sha256(key_bytes).hexdigest(), 'results': results}
    (folder / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
