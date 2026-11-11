"""Build and compare the capped and source-built stacks on the Docker host CPU.

Evaluation only. Leaves the two named images for the existing image-security gate.
Never starts EW or contacts configured devices. Run on amd64 or arm64 Docker hosts.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
import uuid

IMAGES = {target: f'ew-numpy-native-{target}' for target in ('capped', 'candidate')}


def run_probe(image, script):
    name = 'ew-numpy-native-' + uuid.uuid4().hex[:12]
    try:
        result = subprocess.run([
            'docker', 'run', '--rm', '--name', name, '--network', 'none',
            '--memory', '2g', '--cpus', '2', '--ulimit', 'core=0',
            image, 'python', script,
        ], capture_output=True, text=True, timeout=180, check=True)
        return json.loads(result.stdout)
    finally:
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True)


def compare(capped, candidate):
    if capped['architecture'] != candidate['architecture']:
        raise ValueError('Cannot compare different CPU architectures')
    if capped['versions']['numpy'] != '2.3.5' or candidate['versions']['numpy'] != '2.4.6':
        raise ValueError('Unexpected NumPy versions')
    if capped['timings'].keys() != candidate['timings'].keys() or not capped['timings']:
        raise ValueError('Benchmark workload mismatch')
    ratios = {}
    for name in capped['timings']:
        values = [row['timings'][name]['median_seconds'] for row in (capped, candidate)]
        if not all(isinstance(value, (int, float)) and math.isfinite(value) and value > 0
                   for value in values):
            raise ValueError('Invalid benchmark timing')
        ratios[name] = values[1] / values[0]
    return ratios


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('numpy-native-report.json'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    rows = {}
    for target, image in IMAGES.items():
        subprocess.run(['docker', 'build', '--pull', '--target', target,
                        '-f', str(root / 'tests/numpy_compat/Dockerfile'),
                        '-t', image, str(root)], check=True)
        smoke = run_probe(image, '/smoke.py')
        if smoke.get('status') != 'passed':
            raise ValueError('Numerical smoke did not pass')
        rows[target] = run_probe(image, '/benchmark.py')
        rows[target]['image_id'] = subprocess.run(
            ['docker', 'image', 'inspect', '--format', '{{.Id}}', image],
            capture_output=True, text=True, check=True).stdout.strip()
    report = {'recorded_at': datetime.now(timezone.utc).isoformat(),
              'scope': 'Native evaluation; 2 CPUs/2 GiB; not physical legacy hardware or production qualification',
              'results': rows, 'candidate_over_capped_ratio': compare(rows['capped'], rows['candidate'])}
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
