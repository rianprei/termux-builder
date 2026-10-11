"""Run directly in Termux: PYTHONPATH=. python tests/integration/verify_termux.py."""
import argparse
import hashlib
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
from types import SimpleNamespace

import yaml

parser = argparse.ArgumentParser(description='Verify native Termux ARM64 CLI APK builds')
parser.add_argument('--android-jar', help='Official SDK platforms/android-N/android.jar; uses normal SDK discovery when omitted')
parser.add_argument('--aab', action='store_true', help='Also verify native CLI App Bundle builds and rebuilds')
parser.add_argument('--bundletool-jar', help='Pinned official bundletool JAR to seed the local cache for offline AAB verification')
parser.add_argument('--key-algorithm', choices=('RSA', 'EC'), default='RSA', help='Algorithm for the temporary signing key')
options = parser.parse_args()
if options.bundletool_jar and not options.aab:
    parser.error('--bundletool-jar requires --aab')
if not hasattr(sys, 'getandroidapilevel') or platform.machine() != 'aarch64':
    raise RuntimeError('This fixture requires native Android ARM64 Python in Termux')
if os.getuid() == 0:
    raise RuntimeError('Run this fixture as the Termux application user, not root')
tools = {name: shutil.which(name) for name in ('java', 'javac', 'aapt2', 'd8', 'apksigner', 'keytool')}
if options.aab:
    tools['jarsigner'] = shutil.which('jarsigner')
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
    if options.bundletool_jar:
        from builder.aab import _BUNDLETOOL_VERSION, _find_bundletool, _verify_bundletool
        cached = root / 'cache/bundletool' / ('bundletool-all-' + _BUNDLETOOL_VERSION + '.jar')
        cached.parent.mkdir(parents=True)
        shutil.copyfile(Path(options.bundletool_jar).resolve(strict=True), cached)
        _verify_bundletool(str(cached))
        if _find_bundletool(SimpleNamespace(cache_dir=raw['cache-path'])) != [tools['java'], '-jar', str(cached)]:
            raise RuntimeError('A bundletool executable in PATH overrides the seeded JAR; remove it from PATH or omit --bundletool-jar')
    environment = os.environ.copy()
    environment['TB_FIXTURE_PASSWORD'] = secrets.token_hex(16)
    keystore = root / 'fixture.p12'
    subprocess.run([tools['keytool'], '-genkeypair', '-keystore', str(keystore),
        '-storepass:env', 'TB_FIXTURE_PASSWORD', '-keypass:env', 'TB_FIXTURE_PASSWORD',
        '-alias', 'fixture', '-dname', 'CN=Native Integration Fixture', '-keyalg', options.key_algorithm,
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
    if options.aab:
        snapshots = []
        for phase in ('aab-first', 'aab-rebuild'):
            start = time.monotonic()
            subprocess.run([sys.executable, '-m', 'builder', 'build', str(project), '--aab'],
                env=environment, check=True)
            elapsed = time.monotonic() - start
            artifacts = list((project / '.build').glob('*-debug.aab'))
            if len(artifacts) != 1:
                raise RuntimeError('Expected one CLI AAB, found ' + repr(artifacts))
            artifact = artifacts[0]
            subprocess.run([tools['jarsigner'], '-verify', str(artifact)], check=True)
            from builder.aab import _find_bundletool
            bundletool = _find_bundletool(SimpleNamespace(cache_dir=raw['cache-path']))
            if not bundletool:
                raise RuntimeError('CLI build did not leave a usable bundletool')
            identity = subprocess.run([*bundletool, 'dump', 'manifest', '--bundle=' + str(artifact),
                '--module=base', '--xpath=/manifest/@package'], check=True, capture_output=True, text=True)
            if identity.stdout.strip() != 'com.example.nativevalidation':
                raise RuntimeError('Native AAB package identity differs')
            with zipfile.ZipFile(artifact) as archive:
                if archive.testzip() or not archive.read('base/dex/classes.dex').startswith(b'dex\n'):
                    raise RuntimeError('Invalid native-built AAB ZIP or DEX')
                for name in ('base/manifest/AndroidManifest.xml', 'base/resources.pb', 'BundleConfig.pb'):
                    if not archive.read(name):
                        raise RuntimeError('Missing App Bundle metadata: ' + name)
                snapshots.append({entry.filename: {
                    'sha256': hashlib.sha256(archive.read(entry)).hexdigest(),
                    'timestamp': entry.date_time, 'compressed_bytes': entry.compress_size,
                    'compression': entry.compress_type, 'attributes': entry.external_attr,
                } for entry in archive.infolist()})
            observations.append({'phase': phase, 'seconds': elapsed, 'aab_bytes': artifact.stat().st_size})
        names = sorted(set(snapshots[0]) | set(snapshots[1]))
        changed_content = [name for name in names if snapshots[0].get(name, {}).get('sha256') != snapshots[1].get(name, {}).get('sha256')]
        changed_metadata = [name for name in names if snapshots[0].get(name) != snapshots[1].get(name)]
        signature_entries = {'META-INF/MANIFEST.MF'} | {name for name in names
            if name.startswith('META-INF/') and name.count('/') == 1 and name.upper().endswith(('.SF', '.RSA', '.DSA', '.EC'))}
        changed_payload = [name for name in changed_content if name not in signature_entries]
        print(json.dumps({'aab_rebuild_comparison': {'content_changes': changed_content,
            'entry_changes': changed_metadata, 'payload_changes': changed_payload}}), flush=True)
        if changed_payload:
            raise RuntimeError('Unchanged native project produced different AAB payload entries: ' + repr(changed_payload))
        print('REAL TERMUX AAB: CLI build/rebuild, bundletool validation and JAR signing passed', flush=True)
    print(json.dumps({'observations': observations, 'samples_per_phase': 1,
        'scope': 'Native smoke fixture; timings do not establish a performance comparison'}), flush=True)
