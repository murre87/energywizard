"""Isolated optional-DHI startup and root-owned-volume checks (no device access).

Requires Docker and normal dhi.io login. Builds are local, never published.
Use a native/emulation-capable Docker host for the selected platform. Signed VEX
verification is a separate prerequisite; this probe does not replace that scan.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time
import uuid

COMPONENTS = {'smartbox': None, 'webdashboard': 8503, 'ewapp': 8502, 'telemetry-collector': 8504}


def docker(*args, **kwargs):
    return subprocess.run(['docker', *args], check=True, **kwargs)


def output(*args):
    return docker(*args, capture_output=True, text=True).stdout.strip()


def logs(name):
    result = docker('logs', name, capture_output=True, text=True)
    return result.stdout + result.stderr


def wait_ready(check, name, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        if output('inspect', '--format', '{{.State.Running}}', name) != 'true':
            raise RuntimeError(f'{name} exited before readiness')
        time.sleep(1)
    raise RuntimeError(f'{name} did not become ready within {timeout} seconds')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--platform', choices=['linux/amd64', 'linux/arm64'], default='linux/amd64')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    arch = args.platform.split('/')[-1]
    prefix = 'ew-dhi-verify-' + uuid.uuid4().hex[:12]
    network, db = prefix + '-net', prefix + '-db'
    containers, volumes, rows = [], [], []
    common_env = {'POSTGRES_HOST': db, 'POSTGRES_USER': 'postgres',
                  'POSTGRES_PASSWORD': 'isolated-test-only', 'POSTGRES_DB': 'dhi_verify',
                  'DASHBOARD_PASSWORD': 'isolated-test-only',
                  'EW_NO_WATCH': '1', 'HOUSE_CONFIG_PATH': '/data/house_config.yaml'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.unlink(missing_ok=True)
    try:
        docker('network', 'create', '--internal', network)
        containers.append(db)
        docker('run', '--rm', '-d', '--name', db, '--network', network,
               '-e', 'POSTGRES_PASSWORD=isolated-test-only', '-e', 'POSTGRES_DB=dhi_verify',
               'postgres:17')
        wait_ready(lambda: subprocess.run(['docker', 'exec', db, 'pg_isready', '-U', 'postgres'],
                                         capture_output=True).returncode == 0, db)
        for component, port in COMPONENTS.items():
            image = f'ew-dhi-verify-{component}-{arch}'
            docker('build', '--pull', '--platform', args.platform,
                   '-f', str(root / component / 'Dockerfile.dhi'), '-t', image, str(root / component))
            name, volume = prefix + '-' + component, prefix + '-' + component + '-data'
            volumes.append(volume)
            docker('volume', 'create', volume)
            # Synthetic root-owned mode-0600 data only; no real host data is mounted.
            initialize = ("import os,pathlib; assert os.getuid()==0; "
                          "p=pathlib.Path('/data/energywizard.json'); p.write_text('{}'); p.chmod(0o600); "
                          "p=pathlib.Path('/data/house_config.yaml'); p.write_text('{}'); p.chmod(0o600); "
                          "p=pathlib.Path('/data/root-owned.txt'); p.write_text('before'); p.chmod(0o600)")
            docker('run', '--rm', '--platform', args.platform, '--network', 'none',
                   '-v', f'{volume}:/data', '--entrypoint', '/opt/venv/bin/python', image, '-c', initialize)
            command = ['run', '-d', '--platform', args.platform, '--name', name, '--network', network,
                       '-v', f'{volume}:/data']
            for key, value in common_env.items():
                command += ['-e', f'{key}={value}']
            if component in ('webdashboard', 'ewapp'):
                command += ['-v', f'{root / "smartbox"}:/smartbox:ro']
            containers.append(name)
            docker(*command, image)
            if component == 'smartbox':
                # Real main.py reaches the safe installation wait after DB bootstrap.
                # No HA is configured, so the controller loop cannot start.
                check = lambda: 'Home Assistant är inte kopplat än' in logs(name)
            else:
                endpoint = '/api/stats' if component == 'telemetry-collector' else '/api/ping'
                request = "import json,urllib.request,http.cookies; headers={}; "
                if component != 'telemetry-collector':
                    request += (f"q=urllib.request.Request('http://127.0.0.1:{port}/api/login', "
                                "data=json.dumps({'password':'isolated-test-only'}).encode(), "
                                "headers={'Content-Type':'application/json'}); "
                                "login=urllib.request.urlopen(q,timeout=2); assert login.status==200; "
                                "cookies=http.cookies.SimpleCookie(); "
                                "[cookies.load(v) for v in login.headers.get_all('Set-Cookie',[])]; "
                                "headers['Cookie']='; '.join(k+'='+v.value for k,v in cookies.items()); ")
                # Forward the synthetic session like the TLS-terminating proxy does;
                # EWApp deliberately marks its browser cookie Secure.
                request += (f"q=urllib.request.Request('http://127.0.0.1:{port}{endpoint}',headers=headers); "
                            "r=urllib.request.urlopen(q,timeout=2); "
                           "assert r.status==200; assert isinstance(json.load(r),dict)")
                check = lambda: subprocess.run(
                    ['docker', 'exec', name, '/opt/venv/bin/python', '-c', request],
                    capture_output=True).returncode == 0
            try:
                wait_ready(check, name)
                volume_check = ("import os,pathlib; assert os.getuid()==0; "
                                "p=pathlib.Path('/data/root-owned.txt'); assert p.read_text()=='before'; "
                                "assert p.stat().st_uid==0 and p.stat().st_mode & 0o777==0o600; "
                                "p.write_text('after'); assert p.read_text()=='after'")
                docker('exec', name, '/opt/venv/bin/python', '-c', volume_check)
                # Validate application-level settings writes against the same owned volume.
                if component != 'telemetry-collector':
                    settings_check = ("import sys; sys.path.insert(0,'/smartbox'); import ew_settings; "
                                      "ew_settings.update(language='en'); assert ew_settings.get('language')=='en'")
                    docker('exec', name, '/opt/venv/bin/python', '-c', settings_check)
                rows.append({'component': component, 'platform': args.platform,
                             'image_id': output('image', 'inspect', '--format', '{{.Id}}', image),
                             'readiness': 'installation-wait' if port is None else endpoint,
                             'root_owned_volume': 'passed', 'status': 'passed'})
            finally:
                log = logs(name)
                (args.output.parent / f'{component}-{arch}.log').write_text(log, encoding='utf-8')
                docker('rm', '-f', name)
                containers.remove(name)
        args.output.write_text(json.dumps({'checked_at': datetime.now(timezone.utc).isoformat(),
                                          'scope': 'Isolated startup and synthetic root-owned volumes; no device control',
                                          'results': rows}, indent=2), encoding='utf-8')
    finally:
        for name in reversed(containers):
            subprocess.run(['docker', 'rm', '-f', '-v', name], capture_output=True)
        for name in volumes:
            subprocess.run(['docker', 'volume', 'rm', name], capture_output=True)
        subprocess.run(['docker', 'network', 'rm', network], capture_output=True)


if __name__ == '__main__':
    main()
