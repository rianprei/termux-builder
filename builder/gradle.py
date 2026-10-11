"""Delegate Android builds to the installed Gradle/AGP pair exercised by the fixtures."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
import zipfile

from builder.utils import log, project_lock


def _execute(command, project, capture=True):
    result = subprocess.run(command, cwd=project,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
    if result.returncode:
        # Project plugins can print credentials. Do not replay their output.
        raise RuntimeError(f"Gradle/tool invocation failed with exit {result.returncode}; run the tool directly to inspect its diagnostics")
    return result.stdout or ''


def _tool(value, name):
    path = shutil.which(value or name)
    if not path:
        raise RuntimeError(f"{name} not found or not executable; provide its installed path")
    return str(Path(path).resolve())


def _read_report(path):
    try:
        value = json.loads(path.read_text())
    except (OSError, UnicodeError, ValueError) as error:
        raise RuntimeError('Gradle exported an unreadable artifact report') from error
    if not isinstance(value, dict):
        raise RuntimeError('Gradle exported an invalid artifact report')
    return value


def _sha256(path):
    checksum = hashlib.sha256()
    with path.open('rb') as content:
        for chunk in iter(lambda: content.read(1024 * 1024), b''):
            checksum.update(chunk)
    return checksum.hexdigest()


def _verify_apk(path, apksigner, aapt2, application_id):
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise RuntimeError('APK contains duplicate entries')
            for entry in archive.infolist():
                parts = entry.filename.rstrip('/').split('/')
                if any(part in ('', '.', '..') for part in parts) or '\\' in entry.filename or stat.S_ISLNK(entry.external_attr >> 16):
                    raise RuntimeError('APK contains unsafe entries')
            if 'AndroidManifest.xml' not in names or archive.getinfo('AndroidManifest.xml').file_size == 0:
                raise RuntimeError('APK has no nonempty manifest')
            if archive.testzip() is not None:
                raise RuntimeError('APK CRC verification failed')
    except (OSError, zipfile.BadZipFile) as error:
        raise RuntimeError('APK is not a readable ZIP archive') from error
    _execute([apksigner, 'verify', str(path)], path.parent)
    badging = _execute([aapt2, 'dump', 'badging', str(path)], path.parent)
    if "package: name='" + application_id + "'" not in badging:
        raise RuntimeError('APK package does not match the selected AGP variant')


def build(args):
    if not re.fullmatch(r':(?:[A-Za-z0-9_.-]+(?::[A-Za-z0-9_.-]+)*)?', args.module):
        raise ValueError('Gradle module must be a fully qualified path such as :app')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', args.variant):
        raise ValueError('Gradle variant must be an exact AGP variant name such as demoDebug')
    project = Path(args.project).resolve(strict=True)
    with project_lock(str(project)):
        launcher = _tool(args.gradle, 'gradle')
        try:
            launcher_text = Path(launcher).read_text(errors='replace')
        except OSError as error:
            raise RuntimeError('Gradle launcher cannot be read; check its file permissions and installed path') from error
        if 'GradleWrapperMain' in launcher_text:
            raise ValueError('Gradle Wrapper launchers are not supported; provide an installed Gradle 9.7.1 launcher to keep offline bootstrap explicit')
        shell = _tool(None, 'sh')
        _tool(None, 'java')
        command = [shell, launcher, '--no-daemon', '--no-watch-fs', '--no-configuration-cache', '--console=plain', '--max-workers=2']
        if args.offline:
            command.append('--offline')
        if hasattr(sys, 'getandroidapilevel'):
            command.append('-Dorg.gradle.native=false')
        version = _execute(command + ['--version'], project)
        if not re.search(r'^Gradle 9\.7\.1\s*$', version, re.MULTILINE):
            raise RuntimeError('This experimental adapter requires installed Gradle 9.7.1; other versions have not been verified')
        aapt2 = _tool(args.aapt2, 'aapt2') if not args.aab or args.aapt2 or hasattr(sys, 'getandroidapilevel') else None
        apksigner = None if args.aab else _tool(args.apksigner, 'apksigner')
        bundletool = None
        if args.aab:
            from builder import aab
            if not args.bundletool_jar:
                raise ValueError('AAB verification requires --bundletool-jar with the pinned bundletool 1.18.3 JAR')
            bundletool_path = Path(args.bundletool_jar).resolve(strict=True)
            aab._verify_bundletool(str(bundletool_path))
            bundletool = [_tool(None, 'java'), '-jar', str(bundletool_path)]
            _tool(None, 'jarsigner')
        if aapt2:
            command.append('-Pandroid.aapt2FromMavenOverride=' + aapt2)
        nonce = uuid.uuid4().hex
        task = 'termuxBuilderExport' + nonce
        with tempfile.TemporaryDirectory(prefix='termux-builder-gradle-') as temp:
            report = Path(temp) / 'artifacts.json'
            init = Path(temp) / 'init.gradle'
            init.write_text(Path(__file__).with_name('gradle_init.gradle').read_text())
            command.extend(['--init-script', str(init), '-Dtb.module=' + args.module,
                '-Dtb.variant=' + args.variant, '-Dtb.format=' + ('aab' if args.aab else 'apk'),
                '-Dtb.report=' + str(report), '-Dtb.nonce=' + nonce, '-Dtb.task=' + task,
                args.module.rstrip(':') + ':' + task])
            log.info('Gradle build: module %s, variant %s, %s', args.module, args.variant, 'AAB' if args.aab else 'APK')
            try:
                _execute(command, project, capture=False)
            except RuntimeError:
                if report.is_file():
                    failure = _read_report(report)
                    if failure.get('nonce') == nonce and failure.get('error') in ('module', 'variant', 'plugin', 'agp'):
                        raise RuntimeError('Gradle selection failed: ' + {
                            'module': 'module not found', 'variant': 'exact variant not found',
                            'plugin': 'module must apply com.android.application',
                            'agp': 'this adapter requires AGP 9.4.1; other versions have not been verified',
                        }[failure['error']]) from None
                raise
            if not report.is_file():
                raise RuntimeError('Gradle did not export artifacts for this invocation')
            result = _read_report(report)
            if (not isinstance(result, dict) or result.get('nonce') != nonce or result.get('module') != args.module
                    or result.get('variant') != args.variant or result.get('format') != ('aab' if args.aab else 'apk')):
                raise RuntimeError('Gradle artifact report does not match this invocation')
            application_id = result.get('applicationId', '')
            if not isinstance(application_id, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+', application_id):
                raise RuntimeError('Gradle exported an invalid application ID')
            artifacts = result.get('artifacts')
            if not isinstance(artifacts, list) or not artifacts:
                raise RuntimeError('Gradle exported no artifacts')
            for index, artifact in enumerate(artifacts):
                if not isinstance(artifact, dict) or not isinstance(artifact.get('path'), str):
                    raise RuntimeError('Gradle exported an invalid artifact record')
                path = Path(artifact['path'])
                if not path.is_absolute() or path.is_symlink() or not path.is_file() or path.suffix != ('.aab' if args.aab else '.apk'):
                    raise RuntimeError('Gradle exported an invalid artifact path')
                snapshot = Path(temp) / ('artifact-' + str(index) + path.suffix)
                shutil.copyfile(path, snapshot)
                if args.aab:
                    aab._verify_aab(str(snapshot), bundletool)
                    manifest_id = _execute(bundletool + ['dump', 'manifest', '--bundle=' + str(snapshot), '--xpath=/manifest/@package'], project).strip()
                    if manifest_id != application_id:
                        raise RuntimeError('AAB package does not match the selected AGP variant')
                else:
                    _verify_apk(snapshot, apksigner, aapt2, application_id)
                artifact['size'] = snapshot.stat().st_size
                artifact['sha256'] = _sha256(snapshot)
                if path.is_symlink() or _sha256(path) != artifact['sha256']:
                    raise RuntimeError('Gradle artifact changed during verification; retry after stopping external writers')
                artifact['signatureVerified'] = True
            log.info('BUILD SUCCESSFUL: Gradle outputs verified; certificate trust was not checked')
            for artifact in artifacts:
                log.info('%s: %s (SHA-256 %s)', result['format'].upper(), artifact['path'], artifact['sha256'])
            return result
