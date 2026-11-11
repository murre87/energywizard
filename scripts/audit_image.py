"""Audit installed packages and OS findings without running the application.

Requires Docker and pip-audit in this interpreter. Reports retain all findings;
the gate rejects Python advisories, CISA KEVs and available Debian fixes.
Unfixed/non-KEV scanner matches still require review, not a CVE-free claim.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

GRYPE = 'anchore/grype@sha256:13113eeceab017260370cf540e1d25442c59665fd07d1b09b66d63bb0c282887'
KEV_URLS = (
    'https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json',
    'https://raw.githubusercontent.com/cisagov/kev-data/develop/known_exploited_vulnerabilities.json',
)


def validate_kev(data, now=None):
    now = now or datetime.now(timezone.utc)
    released = datetime.fromisoformat(data['dateReleased'].replace('Z', '+00:00'))
    if released.tzinfo is None or not now - timedelta(days=14) <= released <= now + timedelta(days=1):
        raise ValueError('KEV catalog is stale or has an invalid timestamp')
    entries = data['vulnerabilities']
    if not isinstance(entries, list) or not entries or len(entries) != data['count']:
        raise ValueError('Invalid KEV catalog count')
    ids = {entry['cveID'] for entry in entries}
    if len(ids) != len(entries) or not all(re.fullmatch(r'CVE-\d{4}-\d{4,}', value) for value in ids):
        raise ValueError('Invalid KEV identifiers')
    return ids


def fetch_kev():
    for url in KEV_URLS:
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'EnergyWizard-security-audit'})
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.load(response)
            validate_kev(data)
            return data, url
        except (OSError, ValueError, KeyError, TypeError):
            continue
    raise RuntimeError('Cannot obtain a valid, recent CISA KEV catalog')


def policy_findings(report, kev_ids):
    # Reject incomplete/malformed scanner results instead of interpreting them as clean.
    if not report['descriptor']['db']['status']['valid']:
        raise ValueError('Scanner vulnerability database is invalid')
    findings = []
    for match in report['matches']:
        vulnerability = match['vulnerability']
        identifiers = {vulnerability['id']} | {v['id'] for v in match.get('relatedVulnerabilities', [])}
        known_exploited = sorted(identifiers & kev_ids)
        # Distro advisories account for Debian backports. Generic NVD/CPE version
        # matches (including Python fixes in another release series) need triage.
        fixable_debian = (vulnerability['namespace'].startswith('debian:')
                          and vulnerability['fix']['state'] == 'fixed'
                          and bool(vulnerability['fix']['versions']))
        if known_exploited or fixable_debian:
            findings.append({'package': match['artifact']['name'],
                             'version': match['artifact']['version'],
                             'id': vulnerability['id'], 'kev': known_exploited,
                             'fix': vulnerability['fix']})
    return findings


def requirements(inventory):
    lines = []
    for package in inventory:
        name, version = package['name'], package['version']
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', name) or not re.fullmatch(r'[A-Za-z0-9.!+_-]+', version):
            raise ValueError('Invalid installed package metadata')
        lines.append(f'{name}=={version}')
    if not lines:
        raise ValueError('No installed Python packages found')
    return '\n'.join(sorted(set(lines))) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', help='Locally built Docker image')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/:@-]*', args.image):
        parser.error('Invalid local image reference')
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    inventory_code = ('import importlib.metadata as m,json; '
                      'print(json.dumps([{"name":d.metadata["Name"],"version":d.version} for d in m.distributions()]))')
    installed = subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python3',
                                args.image, '-c', inventory_code], check=True, capture_output=True, text=True)
    inventory = json.loads(installed.stdout)
    (folder / 'inventory.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')
    requirement_file = folder / 'requirements.txt'
    requirement_file.write_text(requirements(inventory), encoding='utf-8')
    python_audit = subprocess.run([sys.executable, '-m', 'pip_audit', '--disable-pip', '--no-deps',
                                   '-r', str(requirement_file), '--format', 'json',
                                   '--output', str(folder / 'python-audit.json')])
    if python_audit.returncode not in (0, 1):
        raise RuntimeError('Python vulnerability audit failed')
    python_report = json.loads((folder / 'python-audit.json').read_text(encoding='utf-8'))
    # Unknown/skipped packages cannot silently pass the Python gate.
    if not python_report['dependencies'] or any(d.get('skip_reason') for d in python_report['dependencies']):
        raise ValueError('Python audit did not cover the full inventory')
    python_findings = [d for d in python_report['dependencies'] if d['vulns']]
    archive = folder / 'image.tar'
    try:
        subprocess.run(['docker', 'image', 'save', '--output', str(archive), args.image], check=True)
        # Scan a local archive: no Docker socket, auth file or user home is mounted.
        subprocess.run(['docker', 'run', '--rm', '--volume', f'{folder}:/scan',
                        '--volume', 'ew-security-grype-cache:/.cache/grype', GRYPE,
                        'docker-archive:/scan/image.tar', '--output', 'json',
                        '--file', '/scan/grype.json'], check=True)
    finally:
        archive.unlink(missing_ok=True)
    report = json.loads((folder / 'grype.json').read_text(encoding='utf-8'))
    kev, source = fetch_kev()
    (folder / 'kev.json').write_text(json.dumps(kev, indent=2), encoding='utf-8')
    blocked = policy_findings(report, validate_kev(kev))
    summary = {'image': args.image, 'scanned_at': datetime.now(timezone.utc).isoformat(),
               'python_findings': python_findings, 'blocked_image_findings': blocked,
               'total_scanner_matches': len(report['matches']),
               'kev_source': source, 'kev_released': kev['dateReleased'],
               'kev_sha256': hashlib.sha256(json.dumps(kev, sort_keys=True).encode()).hexdigest(),
               'scope': 'No Python advisories, KEVs or available Debian fixes; other matches remain for review'}
    (folder / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))
    return 1 if python_findings or blocked or python_audit.returncode else 0


if __name__ == '__main__':
    raise SystemExit(main())
