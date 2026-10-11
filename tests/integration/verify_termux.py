"""Run directly in Termux: PYTHONPATH=. python tests/integration/verify_termux.py."""
import argparse
import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import yaml

parser = argparse.ArgumentParser(description='Verify native Termux ARM64 CLI APK builds')
parser.add_argument('--android-jar', help='Official SDK platforms/android-N/android.jar; uses normal SDK discovery when omitted')
options = parser.parse_args()
if not hasattr(sys, 'getandroidapilevel') or platform.machine() != 'aarch64':
    raise RuntimeError('This fixture requires native Android ARM64 Python in Termux')
if os.getuid() == 0:
    raise RuntimeError('Run this fixture as the Termux application user, not root')
tools = {name: shutil.which(name) for name in ('java', 'javac', 'aapt2', 'd8', 'apksigner', 'keytool')}
if not all(tools.values()):
    raise RuntimeError('Missing native tools: ' + ', '.join(name for name, path in tools.items() if not path))
runtime_api = int(subprocess.check_output(['/system/bin/getprop', 'ro.build.version.sdk'], text=True).strip())
print(json.dumps({'architecture': platform.machine(), 'android_api': runtime_api, 'python_android_api': sys.getandroidapilevel(),
    'python': sys.version, 'uid': os.getuid(), 'tools': tools}), flush=True)
with tempfile.TemporaryDirectory(prefix='termux-builder-native-') as temp:
    root = Path(temp)
    project = root / 'project'
    subprocess.run([sys.executable, '-m', 'builder', 'init', str(project),
        '--package', 'com.example.nativevalidation'], check=True)
    raw = yaml.safe_load((project / 'project.yml').read_text())
    raw['cache-path'] = str(root / 'cache')
    environment = os.environ.copy()
    environment['TB_FIXTURE_PASSWORD'] = secrets.token_hex(16)
    keystore = root / 'fixture.p12'
    subprocess.run([tools['keytool'], '-genkeypair', '-keystore', str(keystore),
        '-storepass:env', 'TB_FIXTURE_PASSWORD', '-keypass:env', 'TB_FIXTURE_PASSWORD',
        '-alias', 'fixture', '-dname', 'CN=Native Integration Fixture', '-keyalg', 'RSA',
        '-validity', '1'], env=environment, check=True)
    raw['android'].update({'min-sdk': 21, 'target-sdk': 28, 'java-version': 8,
        'keystore-path': str(keystore), 'keystore-alias': 'fixture',
        'keystore-store-pass': 'env:TB_FIXTURE_PASSWORD', 'keystore-key-pass': 'env:TB_FIXTURE_PASSWORD'})
    if options.android_jar:
        android_jar = Path(options.android_jar).resolve(strict=True)
        raw['android']['sdk-path'] = str(android_jar.parents[2])
        raw['android']['target-sdk'] = int(android_jar.parent.name.removeprefix('android-'))
    (project / 'project.yml').write_text(yaml.safe_dump(raw))
    observations = []
    for phase in ('cold', 'rebuild'):
        start = time.monotonic()
        subprocess.run([sys.executable, '-m', 'builder', 'build', str(project)],
            env=environment, check=True)
        elapsed = time.monotonic() - start
        artifacts = list((project / '.build').glob('*-debug.apk'))
        if len(artifacts) != 1:
            raise RuntimeError('Expected one CLI APK, found ' + repr(artifacts))
        artifact = artifacts[0]
        subprocess.run([tools['apksigner'], 'verify', str(artifact)], check=True)
        with zipfile.ZipFile(artifact) as archive:
            if archive.testzip() or not archive.read('classes.dex').startswith(b'dex\n'):
                raise RuntimeError('Invalid native-built APK ZIP or DEX')
            if not archive.read('AndroidManifest.xml'):
                raise RuntimeError('Missing compiled manifest')
        badging = subprocess.run([tools['aapt2'], 'dump', 'badging', str(artifact)],
            check=True, capture_output=True, text=True)
        if "package: name='com.example.nativevalidation'" not in badging.stdout:
            raise RuntimeError('Native APK package identity differs')
        observations.append({'phase': phase, 'seconds': elapsed, 'apk_bytes': artifact.stat().st_size})
    print('REAL TERMUX APK: CLI cold build and rebuild, native signing and package verification passed', flush=True)
    print(json.dumps({'observations': observations, 'samples_per_phase': 1,
        'scope': 'Native smoke fixture; timings do not establish a performance comparison'}), flush=True)
