"""Audit the exact four optional images qualified by a native DHI runtime job."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

COMPONENTS = {'smartbox', 'webdashboard', 'ewapp', 'telemetry-collector'}


def tested_images(document, platform):
    rows = document.get('results', [])
    if len(rows) != len(COMPONENTS) or {r.get('component') for r in rows} != COMPONENTS:
        raise ValueError('Require exactly four distinct tested components')
    for row in rows:
        if (row.get('status') != 'passed' or row.get('platform') != platform or
                row.get('root_owned_volume') != 'passed' or
                not re.fullmatch(r'sha256:[0-9a-f]{64}', str(row.get('image_id', '')))):
            raise ValueError('Require successful same-platform runtime evidence and immutable image IDs')
    return sorted(rows, key=lambda r: r['component'])


def audit(document, platform, folder, run=subprocess.run):
    (folder / 'summary.json').unlink(missing_ok=True)
    rows = tested_images(document, platform)  # validate all evidence before any audit
    folder.mkdir(parents=True, exist_ok=True)
    results = []
    for row in rows:
        target = folder / row['component']
        target.mkdir(parents=True, exist_ok=True)
        summary_path = target / 'summary.json'
        summary_path.unlink(missing_ok=True)  # failed runs must not reuse old success
        result = run([sys.executable, str(Path(__file__).with_name('audit_image.py')),
                      row['image_id'], '--output', str(target)], check=False)
        try:
            summary = json.loads(summary_path.read_text(encoding='utf-8'))
            if not isinstance(summary, dict):
                raise ValueError('Audit summary must be an object')
            valid = (summary.get('image') == row['image_id'] and
                     isinstance(summary.get('python_findings'), list) and
                     isinstance(summary.get('blocked_image_findings'), list) and
                     isinstance(summary.get('total_scanner_matches'), int))
        except (OSError, ValueError):
            summary, valid = {}, False
        passed = (result.returncode == 0 and valid and not summary['python_findings']
                  and not summary['blocked_image_findings'])
        results.append({'component': row['component'], 'platform': platform,
                        'image_id': row['image_id'], 'status': 'passed' if passed else 'failed',
                        'audit_exit_code': result.returncode, 'matching_summary': valid,
                        'total_scanner_matches': summary.get('total_scanner_matches')})
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'results': results,
              'scope': 'Installed Python, raw image findings and current KEV policy; no CVE-free or VEX exemption claim'}
    (folder / 'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-results', required=True, type=Path)
    parser.add_argument('--platform', required=True, choices=('linux/amd64', 'linux/arm64'))
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = audit(json.loads(args.runtime_results.read_text(encoding='utf-8')), args.platform, args.output.resolve())
    print(json.dumps(report, indent=2))
    return int(any(r['status'] != 'passed' for r in report['results']))


if __name__ == '__main__':
    raise SystemExit(main())
