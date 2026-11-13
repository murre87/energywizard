"""Compare upstream and source-built NumPy under an x86-64-v1 CPU model.

Requires Docker on amd64; builds evaluation images only and never starts EW.
"""
from pathlib import Path
import argparse
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-target', choices=('candidate', 'candidate-openblas'), default='candidate')
    args = parser.parse_args()
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
    cpu_failure = ('X86_V2' in error.upper()
                   or 'QEMU: UNCAUGHT TARGET SIGNAL 4 (ILLEGAL INSTRUCTION)' in error.upper())
    if not cpu_failure:
        raise RuntimeError('Upstream control did not reproduce the expected CPU baseline failure: '
                           + error)
    print('Upstream wheel rejects the qemu64 CPU as expected', flush=True)
    capped = run_image('capped')
    if capped.returncode:
        raise RuntimeError('Existing capped version failed compatibility smoke: ' + capped.stderr)
    print(capped.stdout, end='', flush=True)
    candidate = run_image(args.candidate_target)
    print(candidate.stdout, end='', flush=True)
    if candidate.returncode:
        raise RuntimeError('Candidate failed compatibility smoke: ' + candidate.stderr)


if __name__ == '__main__':
    main()
