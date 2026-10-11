"""Exercise the public test CLI with a real JDK and JUnit 4."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import yaml


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--android-jar', required=True)
parser.add_argument('--junit-jar', required=True)
parser.add_argument('--hamcrest-jar', required=True)
args = parser.parse_args()
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

    def run_cli(expected):
        result = subprocess.run([sys.executable, '-m', 'builder', 'test', str(project)],
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
