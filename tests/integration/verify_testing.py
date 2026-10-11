"""Exercise the public test CLI with a real JDK and JUnit 4."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
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
    shutil.copyfile(Path(args.junit_jar).resolve(strict=True), libs / 'junit-4.13.2.jar')
    shutil.copyfile(Path(args.hamcrest_jar).resolve(strict=True), libs / 'hamcrest-core-1.3.jar')
    (project / 'project.yml').write_text(yaml.safe_dump({'name': 'junit-fixture',
        'android': {'sdk-path': str(android_jar.parents[2]), 'java-version': 8}, 'bins': {'javac': javac}}))
    (project / 'AndroidManifest.xml').write_text('<manifest package="com.example.junitfixture"><application/></manifest>')
    sources = project / 'src/test'
    sources.mkdir(parents=True)
    passing = sources / 'PassingTest.java'
    passing.write_text('import org.junit.Test; public class PassingTest { @Test public void passes() {} }')
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
            'class KotlinTest { @Test fun passes() { assertEquals(7, 3 + 4) } }')
        result = run_cli(0)
        if 'OK (1 test)' not in result.stdout + result.stderr:
            raise RuntimeError('Expected one real Kotlin JUnit test')
        bytecode = (classes / 'KotlinTest.class').read_bytes()
        if bytecode[:4] != b'\xca\xfe\xba\xbe' or int.from_bytes(bytecode[6:8], 'big') != 52:
            raise RuntimeError('Kotlin test must compile to Java 8 bytecode')
        kotlin_test.unlink()
        run_cli(0)
        if classes.exists() and list(classes.rglob('*.class')):
            raise RuntimeError('Removed Kotlin test bytecode survived')
        print('REAL KOTLIN JUNIT CLI: Java 8 bytecode, execution and removal passed', flush=True)
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
            report = ET.parse(project / '.build/coverage/coverage.xml')
            branch = report.find(".//class[@name='CoverageTarget']/counter[@type='BRANCH']")
            if branch is None or branch.attrib != {'type': 'BRANCH', 'missed': '1', 'covered': '1'}:
                raise RuntimeError('Coverage contains branches from a previous execution')
        (kotlin_classes / 'Corrupt.class').write_bytes((app_classes / 'CoverageTarget.class').read_bytes()[:20])
        failed_report = run_cli(1, coverage=True)
        if 'OK (1 test)' not in failed_report.stdout + failed_report.stderr or 'Coverage report:' in failed_report.stdout + failed_report.stderr:
            raise RuntimeError('Report failure must follow passing JUnit without announcing a successful report')
        print('REAL JACOCO CLI: independent branch coverage and report failure exit status passed', flush=True)
