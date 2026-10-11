"""Build real mixed Java/Kotlin APK and AAB projects without annotation processors."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import zipfile

import yaml
from builder.kapt import setup_k1_compiler

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--android-jar', required=True)
for tool in ('aapt2', 'd8', 'apksigner'):
    parser.add_argument('--' + tool, default=tool)
args = parser.parse_args()
android_jar = Path(args.android_jar).resolve(strict=True)
environment = os.environ.copy()
environment['PYTHONPATH'] = str(Path(__file__).resolve().parents[2])
with tempfile.TemporaryDirectory(prefix='termux-builder-mixed-') as temp:
    root = Path(temp)
    jars = setup_k1_compiler(SimpleNamespace(cache_dir=str(root / 'cache')))
    prefix = [shutil.which('java'), '-cp', os.pathsep.join(jars), 'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler']
    wrapper = root / 'kotlinc'
    wrapper.write_text('#!/usr/bin/env python3\nimport os,sys\nprefix=' + repr(prefix) + '\nos.execv(prefix[0],prefix+sys.argv[1:])\n')
    wrapper.chmod(0o755)
    project = root / 'app'
    subprocess.run([sys.executable, '-m', 'builder', 'init', str(project), '--package', 'com.example.mixed'],
        env=environment, check=True, capture_output=True)
    libraries = project / '.libs'
    libraries.mkdir()
    shutil.copyfile(next(j for j in jars if Path(j).name == 'kotlin-stdlib.jar'), libraries / 'kotlin-stdlib.jar')
    config = yaml.safe_load((project / 'project.yml').read_text())
    config['android'].update({'sdk-path': str(android_jar.parents[2]),
        'target-sdk': int(android_jar.parent.name.removeprefix('android-')), 'java-version': 8, 'kapt': False})
    config['cache-path'] = str(root / 'cache')
    config['bins'] = {'kotlinc': str(wrapper), 'aapt2': args.aapt2, 'd8': args.d8, 'apksigner': args.apksigner}
    (project / 'project.yml').write_text(yaml.safe_dump(config))
    activity = next(project.rglob('MainActivity.java'))
    activity.write_text(activity.read_text().replace('super.onCreate(savedInstanceState);',
        'super.onCreate(savedInstanceState); setTitle(Integer.toString(new KotlinValue().value()));'))
    helper = activity.with_name('JavaHelper.java')
    helper.write_text('package com.example.mixed; public class JavaHelper { public static int base() { return 7; } }')
    kotlin = activity.with_name('KotlinValue.kt')
    kotlin.parent.mkdir(parents=True, exist_ok=True)
    kotlin_text = 'package com.example.mixed; class KotlinValue { fun value(): Int = JavaHelper.base() }'
    kotlin.write_text(kotlin_text)
    def build(bundle=False, expected=0, clean=False):
        result = subprocess.run([sys.executable, '-m', 'builder', 'build', str(project), *(['--aab'] if bundle else []), *(['--clean'] if clean else [])],
            env=environment, capture_output=True, text=True)
        print(result.stdout + result.stderr, flush=True)
        if result.returncode != expected:
            raise RuntimeError(f'Mixed build returned {result.returncode}, expected {expected}')
        return result
    for bundle in (False, True):
        build(bundle)
        artifact = next((project / '.build').glob('*.aab' if bundle else '*-debug.apk'))
        with zipfile.ZipFile(artifact) as archive:
            dex = b''.join(archive.read(name) for name in archive.namelist() if name.endswith('.dex'))
            if not all(name in dex for name in (b'JavaHelper', b'KotlinValue', b'MainActivity')):
                raise RuntimeError('Mixed application classes missing from final DEX')
    probe = root / 'Probe.java'
    probe.write_text('public class Probe { public static void main(String[] args) { '
        'System.out.println(new com.example.mixed.KotlinValue().value()); } }')
    runtime_cp = os.pathsep.join([str(project / '.build/bin/classes/java'),
        str(project / '.build/bin/classes/kotlin'), str(libraries / 'kotlin-stdlib.jar')])
    subprocess.run(['javac', '-proc:none', '-classpath', runtime_cp, '-d', str(root), str(probe)], check=True)
    value = subprocess.check_output(['java', '-classpath', os.pathsep.join([str(root), runtime_cp]), 'Probe'], text=True)
    if value.strip() != '7':
        raise RuntimeError('Compiled mixed classes returned an unexpected JVM value')
    sentinel = project / '.build/preserved-output.txt'
    sentinel.write_bytes(b'previous output')
    prior_outputs = {path: path.read_bytes() for path in (project / '.build').iterdir() if path.suffix in ('.apk', '.aab')}
    config['android']['compose'] = True
    (project / 'project.yml').write_text(yaml.safe_dump(config))
    for bundle_mode in (False, True):
        failure = build(bundle=bundle_mode, expected=1, clean=True)
        if ('compose-compiler.jar' not in failure.stdout + failure.stderr or sentinel.read_bytes() != b'previous output'
                or any(path.read_bytes() != contents for path, contents in prior_outputs.items())):
            raise RuntimeError('Missing requested Compose plugin must fail explicitly before clean and preserve APK/AAB')
    config['android']['compose'] = False
    (project / 'project.yml').write_text(yaml.safe_dump(config))
    build()
    print('REAL COMPOSE NEGATIVE: missing requested plugin rejected before clean; ordinary Kotlin build recovered', flush=True)
    kotlin.unlink()
    failure = build(expected=1)
    if 'KotlinValue' not in failure.stdout + failure.stderr:
        raise RuntimeError('Removed Kotlin dependency must fail explicitly')
    kotlin.write_text(kotlin_text)
    build()
    helper.unlink()
    failure = build(expected=1)
    if 'JavaHelper' not in failure.stdout + failure.stderr:
        raise RuntimeError('Removed Java dependency must fail explicitly')
    print('REAL MIXED CLI: Java/Kotlin APK/AAB, recovery and stale-dependency rejection passed', flush=True)
