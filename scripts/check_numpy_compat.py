"""Compare upstream and source-built NumPy under an x86-64-v1 CPU model.

Requires Docker on amd64; builds evaluation images only and never starts EW.
"""
from pathlib import Path
import argparse
import json
import subprocess
import uuid


def run_image(target, python_only=False, timeout=180):
    name = 'ew-numpy-probe-' + uuid.uuid4().hex[:12]
    try:
        command = ['docker', 'run', '--rm', '--name', name, '--ulimit', 'core=0',
                   '--network', 'none', f'ew-numpy-compat-{target}']
        if python_only:
            command += ['qemu-x86_64', '-cpu', 'qemu64', '/usr/local/bin/python',
                        '-c', "print('Emulated Python startup passed')"]
        return subprocess.run(command,
                              capture_output=True, text=True, timeout=timeout)
    finally:
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True)


def cpu_failure(error):
    if isinstance(error,bytes):error=error.decode(errors='replace')
    return 'X86_V2' in error.upper() or 'QEMU: UNCAUGHT TARGET SIGNAL 4 (ILLEGAL INSTRUCTION)' in error.upper()


def candidate_result(target,record=None):
    """An explicitly requested experimental rejection is evidence, never a pass."""
    try:
        candidate=run_image(target,timeout=20 if record else 180)
        error=candidate.stdout+candidate.stderr
        compatible=candidate.returncode==0
    except subprocess.TimeoutExpired as timeout:
        error=timeout.stderr or b''
        compatible=False
    if isinstance(error,bytes):error=error.decode(errors='replace')
    if not compatible and not (record and cpu_failure(error)):
        raise RuntimeError('Candidate failed compatibility smoke: '+error)
    result={'target':target,'status':'compatible_smoke' if compatible else 'rejected_cpu',
            'scope':'qemu64 only; not physical hardware qualification','output':error}
    result['image_id']=subprocess.run(['docker','image','inspect','--format','{{.Id}}',
        'ew-numpy-compat-'+target],capture_output=True,text=True,check=True).stdout.strip()
    if record:record.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result),flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-target', choices=('candidate', 'candidate-openblas'), default='candidate')
    parser.add_argument('--record-experimental-rejection',type=Path,
                        help='OpenBLAS experiment only: record a reproduced CPU rejection, never other failures')
    args = parser.parse_args()
    if args.record_experimental_rejection and args.candidate_target!='candidate-openblas':
        parser.error('Rejection recording is restricted to the OpenBLAS experiment')
    root = Path(__file__).resolve().parents[1]
    for target in (args.candidate_target, 'upstream', 'capped'):
        subprocess.run(['docker', 'build', '--pull', '--target', target,
                        '-f', str(root / 'tests/numpy_compat/Dockerfile'),
                        '-t', f'ew-numpy-compat-{target}', str(root)], check=True)
    python = run_image('upstream', python_only=True)
    if python.returncode:
        raise RuntimeError('Python itself failed under the CPU model: ' + python.stderr)
    try:
        control = run_image('upstream', timeout=20)
        if control.returncode == 0:
            raise RuntimeError('Upstream wheel unexpectedly passed; CPU model is not a useful control')
        error = control.stdout + control.stderr
    except subprocess.TimeoutExpired as timeout:
        # WSL's piped crash handler can hang after QEMU reports SIGILL. The
        # timeout is acceptable ONLY when the expected CPU fault was observed;
        # run_image's finally block removes this uniquely named container.
        error = timeout.stderr or b''
        if isinstance(error, bytes):
            error = error.decode(errors='replace')
    if not cpu_failure(error):
        raise RuntimeError('Upstream control did not reproduce the expected CPU baseline failure: '
                           + error)
    print('Upstream wheel rejects the qemu64 CPU as expected', flush=True)
    capped = run_image('capped')
    if capped.returncode:
        raise RuntimeError('Existing capped version failed compatibility smoke: ' + capped.stderr)
    print(capped.stdout, end='', flush=True)
    candidate_result(args.candidate_target,args.record_experimental_rejection)


if __name__ == '__main__':
    main()
