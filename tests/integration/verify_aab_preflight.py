"""Exercise AAB, release R8 and SDK diagnostics without deleting prior outputs."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import struct
import zipfile
import zlib

import yaml

from builder.config import Config

environment = os.environ.copy()
environment['PYTHONPATH'] = str(Path(__file__).resolve().parents[2])
tools = {name: shutil.which(name) for name in ('java', 'jarsigner')}
if not all(tools.values()):
    raise RuntimeError('Real Java and jarsigner are required to isolate each missing-tool scenario')
with tempfile.TemporaryDirectory(prefix='termux-builder-aab-preflight-') as temp:
    for missing in ('java', 'jarsigner', 'aapt2'):
        project = Path(temp) / missing
        subprocess.run([sys.executable, '-m', 'builder', 'init', str(project)],
            env=environment, check=True, capture_output=True)
        config_path = project / 'project.yml'
        config = yaml.safe_load(config_path.read_text())
        config['bins'] = {'aapt2': str(project / 'absent-aapt2')}
        config_path.write_text(yaml.safe_dump(config))
        marker = project / '.build/previous.apk'
        marker.parent.mkdir()
        marker.write_bytes(b'previous output fixture')
        isolated_path = project / 'isolated-path'
        isolated_path.mkdir()
        for name, path in tools.items():
            if name != missing:
                (isolated_path / name).symlink_to(path)
        isolated_environment = dict(environment, PATH=str(isolated_path))
        result = subprocess.run([sys.executable, '-m', 'builder', 'build', str(project), '--aab', '--clean'],
            env=isolated_environment, capture_output=True, text=True)
        if result.returncode != 1 or missing + ' not found' not in result.stdout + result.stderr:
            raise RuntimeError('Missing-tool diagnostic/exit code mismatch: ' + result.stdout + result.stderr)
        if marker.read_bytes() != b'previous output fixture':
            raise RuntimeError('Preflight failure deleted prior output')
        print('REAL AAB PREFLIGHT: ' + missing + ' missing, exit 1, prior output preserved')

    project = Path(temp) / 'release-r8'
    subprocess.run([sys.executable, '-m', 'builder', 'init', str(project)],
        env=environment, check=True, capture_output=True)
    config_path = project / 'project.yml'
    config = yaml.safe_load(config_path.read_text())
    config['android'].update({'r8': True, 'build-type': 'release'})
    config_path.write_text(yaml.safe_dump(config))
    marker = project / '.build/previous.apk'
    marker.parent.mkdir()
    marker.write_bytes(b'previous output fixture')
    result = subprocess.run([sys.executable, '-m', 'builder', 'build', str(project), '--clean'],
        env=dict(environment, PATH=''), capture_output=True, text=True)
    if result.returncode != 1 or 'r8 enabled' not in result.stdout + result.stderr:
        raise RuntimeError('Missing release R8 diagnostic/exit code mismatch: ' + result.stdout + result.stderr)
    if marker.read_bytes() != b'previous output fixture':
        raise RuntimeError('Missing release R8 deleted prior output')
    print('REAL RELEASE PREFLIGHT: r8 missing, exit 1, prior output preserved')

    for aab in (False, True):
        project = Path(temp) / ('sdk-aab' if aab else 'sdk-apk')
        subprocess.run([sys.executable, '-m', 'builder', 'init', str(project)],
            env=environment, check=True, capture_output=True)
        config_path = project / 'project.yml'
        config = yaml.safe_load(config_path.read_text())
        sdk = project / 'absent-sdk'
        config['android']['sdk-path'] = str(sdk)
        config['bins'] = {'aapt2': sys.executable}
        config_path.write_text(yaml.safe_dump(config))
        selected = Config(str(project))
        expected = sdk / 'platforms' / ('android-' + str(config['android']['target-sdk'])) / 'android.jar'
        if Path(selected.android_jar) != expected:
            raise RuntimeError('Missing SDK fixture did not select its absent android.jar')
        marker = project / '.build/previous.apk'
        marker.parent.mkdir()
        marker.write_bytes(b'previous output fixture')
        command = [sys.executable, '-m', 'builder', 'build', str(project), '--clean']
        if aab:
            command.append('--aab')
        result = subprocess.run(command, env=environment, capture_output=True, text=True)
        if result.returncode != 1 or 'android.jar not found' not in result.stdout + result.stderr:
            raise RuntimeError('Missing SDK diagnostic/exit code mismatch: ' + result.stdout + result.stderr)
        if not marker.is_file() or marker.read_bytes() != b'previous output fixture':
            raise RuntimeError('Missing android.jar deleted prior output')
        print('REAL SDK PREFLIGHT: ' + ('AAB' if aab else 'APK') + ', exit 1, prior output preserved')

    failures = []
    for damage in ('not-zip', 'truncated', 'crc', 'missing-framework', 'hidden-payload', 'null-name'):
        for aab in (False, True):
            project = Path(temp) / ('corrupt-' + damage + ('-aab' if aab else '-apk'))
            subprocess.run([sys.executable, '-m', 'builder', 'init', str(project)],
                env=environment, check=True, capture_output=True)
            config_path = project / 'project.yml'
            config = yaml.safe_load(config_path.read_text())
            sdk = project / 'sdk'
            jar = sdk / 'platforms' / ('android-' + str(config['android']['target-sdk'])) / 'android.jar'
            jar.parent.mkdir(parents=True)
            with zipfile.ZipFile(jar, 'w', compression=zipfile.ZIP_DEFLATED if damage == 'hidden-payload'
                                 else zipfile.ZIP_STORED) as archive:
                name = 'other.class' if damage == 'missing-framework' else 'android/app/Activity.class'
                if damage == 'null-name':
                    name += 'X'
                archive.writestr(name, b'SDK corruption fixture')
            data = bytearray(jar.read_bytes())
            if damage == 'not-zip':
                data = b'invalid SDK fixture'
            elif damage == 'truncated':
                data = data[:-10]
            elif damage == 'crc':
                data[30 + len('android/app/Activity.class')] ^= 1
            elif damage == 'null-name':
                data = data.replace(b'android/app/Activity.classX', b'android/app/Activity.class\x00')
            elif damage == 'hidden-payload':
                central = data.index(b'PK\x01\x02')
                checksum = zlib.crc32(b'SDK')
                struct.pack_into('<I', data, 14, checksum)
                struct.pack_into('<I', data, 22, 3)
                struct.pack_into('<I', data, central + 16, checksum)
                struct.pack_into('<I', data, central + 24, 3)
                jar.write_bytes(data)
                with zipfile.ZipFile(jar) as archive:
                    if archive.testzip() is not None:
                        raise RuntimeError('Hidden payload fixture must pass the weaker ZIP check')
            jar.write_bytes(data)
            config['android']['sdk-path'] = str(sdk)
            config['bins'] = {'aapt2': sys.executable}
            config_path.write_text(yaml.safe_dump(config))
            if Path(Config(str(project)).android_jar) != jar:
                raise RuntimeError('Corrupt SDK fixture did not select its damaged android.jar')
            marker = project / '.build/previous.apk'
            marker.parent.mkdir()
            marker.write_bytes(b'previous output fixture')
            command = [sys.executable, '-m', 'builder', 'build', str(project), '--clean']
            if aab:
                command.append('--aab')
            result = subprocess.run(command, env=environment, capture_output=True, text=True)
            preserved = marker.is_file() and marker.read_bytes() == b'previous output fixture'
            diagnosed = result.returncode == 1 and 'android.jar verification failed' in result.stdout + result.stderr
            print('REAL CORRUPT SDK:', damage, 'AAB' if aab else 'APK', 'exit', result.returncode,
                'preserved', preserved, 'diagnosed', diagnosed, flush=True)
            if not preserved or not diagnosed:
                failures.append((damage, aab, preserved, diagnosed))
    if failures:
        raise RuntimeError('Corrupt SDK preflight failures: ' + repr(failures))
