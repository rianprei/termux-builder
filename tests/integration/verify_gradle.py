"""Real Kotlin DSL/flavor builds through the public installed-Gradle adapter."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gradle', required=True)
    parser.add_argument('--sdk', required=True)
    parser.add_argument('--aapt2', required=True)
    parser.add_argument('--apksigner', required=True)
    parser.add_argument('--dexdump', required=True)
    parser.add_argument('--bundletool-jar', required=True)
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    for name in ('gradle', 'sdk', 'aapt2', 'apksigner', 'dexdump', 'bundletool_jar'):
        setattr(args, name, str(Path(getattr(args, name)).resolve(strict=True)))
    base_environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2]))
    with tempfile.TemporaryDirectory(prefix='termux-builder gradle ') as temporary:
        project = Path(temporary)
        (project / 'settings.gradle.kts').write_text('rootProject.name = "fixture"\ninclude(":mobile")\n')
        (project / 'build.gradle.kts').write_text('''buildscript {
    repositories { google(); mavenCentral() }
    dependencies { classpath("com.android.tools.build:gradle:9.4.1") }
}
allprojects { repositories { google(); mavenCentral() } }
''')
        (project / 'gradle.properties').write_text('org.gradle.jvmargs=-Xmx768m\norg.gradle.configuration-cache=true\n')
        module = project / 'mobile'
        module.mkdir()
        (module / 'build.gradle.kts').write_text('''apply(plugin = "com.android.application")
configure<com.android.build.api.dsl.ApplicationExtension> {
    namespace = "fixture.gradle"
    compileSdk = 36
    buildToolsVersion = "37.0.0"
    defaultConfig { applicationId = "fixture.gradle"; minSdk = 26; targetSdk = 36; versionCode = 1; versionName = "1" }
    flavorDimensions += "edition"
    productFlavors { create("demo") { dimension = "edition"; applicationIdSuffix = ".demo" } }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_1_8; targetCompatibility = JavaVersion.VERSION_1_8 }
}
''')
        # sdk.dir uses Java Properties escaping, rather than shell interpolation.
        (project / 'local.properties').write_text('sdk.dir=' + args.sdk.replace('\\', '\\\\').replace(':', '\\:').replace(' ', '\\ ') + '\n')
        source = module / 'src/main/java/fixture/gradle'
        source.mkdir(parents=True)
        resources = module / 'src/main/res/values'
        resources.mkdir(parents=True)
        manifest = module / 'src/main/AndroidManifest.xml'
        manifest.write_text('''<manifest xmlns:android="http://schemas.android.com/apk/res/android"><application android:label="@string/app_name"><activity android:name="fixture.gradle.MainActivity" android:exported="true"><intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter></activity></application></manifest>''')
        activity = source / 'MainActivity.java'
        body = 'package fixture.gradle; public class MainActivity extends android.app.Activity { static class DeletedMarker {} }'
        activity.write_text(body)
        removed = source / 'Removed.java'
        removed.write_text('package fixture.gradle; public class Removed {}')
        values = resources / 'strings.xml'
        values.write_text('<resources><string name="app_name">Gradle fixture one</string></resources>')

        def invoke(format='apk', variant='demoDebug', module=':mobile', expected=0, environment=None):
            command = [sys.executable, '-m', 'builder', 'gradle-build', str(project), '--gradle', args.gradle,
                '--module', module, '--variant', variant, '--aapt2', args.aapt2]
            if args.offline:
                command.append('--offline')
            command += ['--aab', '--bundletool-jar', args.bundletool_jar] if format == 'aab' else ['--apksigner', args.apksigner]
            start = time.monotonic()
            completed = subprocess.run(command, env=environment or base_environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            print(completed.stdout, end='', flush=True)
            print('GRADLE FIXTURE', format, variant, module, 'exit', completed.returncode, 'seconds', round(time.monotonic()-start, 3), flush=True)
            if completed.returncode != expected:
                raise AssertionError('Public Gradle command returned an unexpected exit status')
            if expected:
                if 'BUILD SUCCESSFUL' in completed.stdout:
                    raise AssertionError('Failed build reported success')
                return completed.stdout
            match = re.search(r'^' + format.upper() + r': (.+) \(SHA-256 ([0-9a-f]{64})\)$', completed.stdout, re.MULTILINE)
            if not match:
                raise AssertionError('Missing verified artifact and digest')
            artifact = Path(match[1])
            if hashlib.sha256(artifact.read_bytes()).hexdigest() != match[2]:
                raise AssertionError('CLI digest does not describe the returned artifact')
            return artifact

        def check(artifact, present):
            descriptors = set()
            with zipfile.ZipFile(artifact) as archive:
                assert archive.testzip() is None
                manifest_name = 'base/manifest/AndroidManifest.xml' if artifact.suffix == '.aab' else 'AndroidManifest.xml'
                assert archive.getinfo(manifest_name).file_size
                for index, name in enumerate(n for n in archive.namelist() if n.endswith('.dex')):
                    dex = project / ('inspect-' + str(index) + '.dex')
                    dex.write_bytes(archive.read(name))
                    listing = subprocess.run([args.dexdump, str(dex)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout
                    descriptors.update(re.findall(r"Class descriptor\s*:\s*'([^']+)'", listing))
            assert 'Lfixture/gradle/MainActivity;' in descriptors
            for deleted in ('Lfixture/gradle/MainActivity$DeletedMarker;', 'Lfixture/gradle/Removed;'):
                assert (deleted in descriptors) == present, (deleted, present)
            if artifact.suffix == '.apk':
                subprocess.run([args.apksigner, 'verify', str(artifact)], check=True)
                badging = subprocess.run([args.aapt2, 'dump', 'badging', str(artifact)], check=True, stdout=subprocess.PIPE, text=True).stdout
                assert "package: name='fixture.gradle.demo'" in badging

        assert not (project / 'project.yml').exists()
        apk = invoke()
        check(apk, True)
        check(invoke('aab'), True)
        # Ordinary Gradle rebuild, with no termux-builder or Gradle clean.
        check(invoke(), True)
        activity.write_text(body.replace(' static class DeletedMarker {}', ''))
        removed.unlink()
        values.write_text('<resources><string name="app_name">Gradle fixture two</string></resources>')
        check(invoke(), False)
        listing = subprocess.run([args.aapt2, 'dump', 'resources', str(apk)], check=True, stdout=subprocess.PIPE, text=True).stdout
        assert 'Gradle fixture two' in listing and 'Gradle fixture one' not in listing
        check(invoke('aab'), False)
        before = hashlib.sha256(apk.read_bytes()).hexdigest()
        assert 'exact variant not found' in invoke(variant='absentDebug', expected=1)
        assert 'module not found' in invoke(module=':absent', expected=1)
        invoke(variant='demoRelease', expected=1)  # AGP emits unsigned release APK; CLI must reject it.
        import json
        release_metadata = json.loads((module / 'build/outputs/apk/demo/release/output-metadata.json').read_text())
        assert release_metadata['variantName'] == 'demoRelease'
        for element in release_metadata['elements']:
            unsigned = module / 'build/outputs/apk/demo/release' / element['outputFile']
            with zipfile.ZipFile(unsigned) as archive:
                assert archive.testzip() is None and 'AndroidManifest.xml' in archive.namelist()
            assert subprocess.run([args.apksigner, 'verify', str(unsigned)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0
        assert hashlib.sha256(apk.read_bytes()).hexdigest() == before
        empty = project / 'empty-gradle-cache'
        empty.mkdir()
        environment = dict(base_environment, GRADLE_USER_HOME=str(empty))
        # Explicit offline invocation with an empty dependency cache must fail.
        previous = args.offline
        args.offline = True
        try:
            invoke(expected=1, environment=environment)
        finally:
            args.offline = previous
        check(invoke(), False)
        print('GRADLE FIXTURE COMPLETE: real APK/AAB, flavor, Kotlin DSL, removal, unsigned release, selection and offline recovery', flush=True)


if __name__ == '__main__':
    main()
