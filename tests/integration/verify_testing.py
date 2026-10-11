"""Exercise the public test CLI with a real JDK and JUnit 4."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET

import yaml


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--android-jar', required=True)
parser.add_argument('--junit-jar', required=True)
parser.add_argument('--hamcrest-jar', required=True)
parser.add_argument('--kotlinc', help='Real Kotlin compiler executable')
parser.add_argument('--kotlin-stdlib', help='Matching Kotlin standard library JAR')
parser.add_argument('--jacoco-agent', help='JaCoCo 0.8.12 runtime agent JAR')
parser.add_argument('--jacoco-cli', help='JaCoCo 0.8.12 nodeps CLI JAR')
args = parser.parse_args()
if bool(args.jacoco_agent) != bool(args.jacoco_cli):
    parser.error('--jacoco-agent and --jacoco-cli must be supplied together')
if bool(args.kotlinc) != bool(args.kotlin_stdlib):
    parser.error('--kotlinc and --kotlin-stdlib must be supplied together')
android_jar = Path(args.android_jar).resolve(strict=True)
javac = shutil.which('javac')
if not javac or not shutil.which('java'):
    raise RuntimeError('Real java and javac are required')
environment = os.environ.copy()
environment['PYTHONPATH'] = str(Path(__file__).resolve().parents[2])

with tempfile.TemporaryDirectory(prefix='termux-builder-junit-') as temp:
    project = Path(temp)
    libs = project / '.libs'
    libs.mkdir()
    junit_runtime = libs / 'runtime-renamed.jar'
    shutil.copyfile(Path(args.junit_jar).resolve(strict=True), junit_runtime)
    with zipfile.ZipFile(libs / 'aaa-junit-incompatible.jar', 'w') as decoy:
        decoy.writestr('META-INF/MANIFEST.MF', 'Manifest-Version: 1.0\n')
    shutil.copyfile(Path(args.hamcrest_jar).resolve(strict=True), libs / 'hamcrest-core-1.3.jar')
    (project / 'project.yml').write_text(yaml.safe_dump({'name': 'junit-fixture',
        'android': {'sdk-path': str(android_jar.parents[2]), 'java-version': 8}, 'bins': {'javac': javac}}))
    (project / 'AndroidManifest.xml').write_text('<manifest package="com.example.junitfixture"><application/></manifest>')
    sources = project / 'src/test'
    sources.mkdir(parents=True)
    passing = sources / 'PassingTest.java'
    passing.write_text('package example.classic; import org.junit.Test; public class PassingTest { @Test public void passes() {} }')
    removed = sources / 'RemovedTest.java'
    removed.write_text('import org.junit.Test; import static org.junit.Assert.*; '
        'public class RemovedTest { @Test public void fails() { fail("intentional fixture failure"); } }')

    def run_cli(expected, coverage=False):
        result = subprocess.run([sys.executable, '-m', 'builder', 'test', str(project),
            *(['--coverage'] if coverage else [])],
            env=environment, capture_output=True, text=True)
        print(result.stdout + result.stderr, flush=True)
        if result.returncode != expected:
            raise RuntimeError(f'JUnit CLI returned {result.returncode}, expected {expected}')
        return result

    failed = run_cli(1)
    if 'intentional fixture failure' not in failed.stdout + failed.stderr:
        raise RuntimeError('Expected actual JUnit assertion failure')
    removed.unlink()
    passed = run_cli(0)
    if 'OK (1 test)' not in passed.stdout + passed.stderr:
        raise RuntimeError('Expected exactly one remaining JUnit test')
    classes = project / '.build/test-classes'
    if (classes / 'RemovedTest.class').exists():
        raise RuntimeError('Removed JUnit class survived rebuild')
    disabled_runtime = libs / 'runtime-renamed.disabled'
    junit_runtime.rename(disabled_runtime)
    missing_runtime = run_cli(1)
    if 'JUnit 4 runtime not found' not in missing_runtime.stdout + missing_runtime.stderr:
        raise RuntimeError('Missing JUnit runtime must produce explicit diagnostic')
    disabled_runtime.rename(junit_runtime)
    run_cli(0)
    passing.unlink()
    run_cli(0)
    if classes.exists() and list(classes.rglob('*.class')):
        raise RuntimeError('JUnit bytecode survived removal of all sources')
    print('REAL JUNIT CLI: assertion failure, removal/rebuild and empty suite invalidation passed', flush=True)
    if args.kotlinc:
        shutil.copyfile(Path(args.kotlin_stdlib).resolve(strict=True), libs / 'kotlin-stdlib.jar')
        configuration = yaml.safe_load((project / 'project.yml').read_text())
        configuration['bins']['kotlinc'] = str(Path(args.kotlinc).resolve(strict=True))
        (project / 'project.yml').write_text(yaml.safe_dump(configuration))
        kotlin_test = sources / 'KotlinTest.kt'
        kotlin_test.write_text('import org.junit.Test; import org.junit.Assert.assertEquals; '
            'class KotlinValue { fun value(): Int = JavaHelper.base() } '
            'class KotlinTest { @Test fun passes() { assertEquals(7, KotlinValue().value()) } }')
        java_helper = sources / 'JavaHelper.java'
        java_helper.write_text('public class JavaHelper { public static int base() { return 7; } }')
        java_test = sources / 'JavaInteropTest.java'
        java_test.write_text('import org.junit.Test; import static org.junit.Assert.*; '
            'public class JavaInteropTest { @Test public void passes() { assertEquals(7, new KotlinValue().value()); } }')
        result = run_cli(0)
        if 'OK (2 tests)' not in result.stdout + result.stderr:
            raise RuntimeError('Expected real Java and Kotlin JUnit tests')
        bytecode = (classes / 'KotlinTest.class').read_bytes()
        if bytecode[:4] != b'\xca\xfe\xba\xbe' or int.from_bytes(bytecode[6:8], 'big') != 52:
            raise RuntimeError('Kotlin test must compile to Java 8 bytecode')
        kotlin_test.unlink()
        removed_kotlin = run_cli(1)
        if 'KotlinValue' not in removed_kotlin.stdout + removed_kotlin.stderr:
            raise RuntimeError('Java must fail explicitly after its Kotlin dependency is removed')
        if (classes / 'KotlinValue.class').exists():
            raise RuntimeError('Removed Kotlin dependency bytecode survived')
        java_helper.unlink()
        java_test.unlink()
        run_cli(0)
        if classes.exists() and list(classes.rglob('*.class')):
            raise RuntimeError('Removed Kotlin test bytecode survived')
        print('REAL KOTLIN JUNIT CLI: mixed Java/Kotlin references, Java 8 bytecode, execution and removal passed', flush=True)
    if args.jacoco_agent:
        cache = project / '.cache/deps'
        cache.mkdir(parents=True)
        shutil.copyfile(args.jacoco_agent, cache / 'org.jacoco.agent-0.8.12-runtime.jar')
        shutil.copyfile(args.jacoco_cli, cache / 'org.jacoco.cli-0.8.12-nodeps.jar')
        app_sources = project / 'src/java'
        app_sources.mkdir()
        source = app_sources / 'CoverageTarget.java'
        source.write_text('public class CoverageTarget { public static int choose(boolean flag) { if (flag) return 1; return 2; } }')
        app_classes = project / '.build/bin/classes/java'
        app_classes.mkdir(parents=True)
        kotlin_classes = project / '.build/bin/classes/kotlin'
        kotlin_classes.mkdir()
        subprocess.run([javac, '-source', '8', '-target', '8', '-d', str(app_classes), str(source)], check=True)
        for flag, value in (('true', 1), ('false', 2)):
            passing.write_text('import org.junit.Test; import static org.junit.Assert.*; '
                'public class PassingTest { @Test public void passes() { assertEquals(' + str(value) +
                ', CoverageTarget.choose(' + flag + ')); } }')
            run_cli(0, coverage=True)
            html = (project / '.build/coverage/index.html').read_text(encoding='utf-8')
            if '<html' not in html.lower() or 'JaCoCo' not in html:
                raise RuntimeError('Expected actual JaCoCo HTML report')
            report = ET.parse(project / '.build/coverage/coverage.xml')
            branch = report.find(".//class[@name='CoverageTarget']/counter[@type='BRANCH']")
            if branch is None or branch.attrib != {'type': 'BRANCH', 'missed': '1', 'covered': '1'}:
                raise RuntimeError('Coverage contains branches from a previous execution')
        coverage_dir = project / '.build/coverage'
        previous_report = {str(path.relative_to(coverage_dir)): path.read_bytes()
            for path in coverage_dir.rglob('*') if path.is_file()}
        (kotlin_classes / 'Corrupt.class').write_bytes((app_classes / 'CoverageTarget.class').read_bytes()[:20])
        failed_report = run_cli(1, coverage=True)
        if 'OK (1 test)' not in failed_report.stdout + failed_report.stderr or 'Coverage report:' in failed_report.stdout + failed_report.stderr:
            raise RuntimeError('Report failure must follow passing JUnit without announcing a successful report')
        retained_report = {str(path.relative_to(coverage_dir)): path.read_bytes()
            for path in coverage_dir.rglob('*') if path.is_file()}
        if retained_report != previous_report:
            raise RuntimeError('Failed generation changed the previously published report')
        if list((project / '.build').glob('.jacoco-report-*')):
            raise RuntimeError('JaCoCo staging survived handled report failure')
        print('REAL JACOCO CLI: independent branch coverage and report failure exit status passed', flush=True)
