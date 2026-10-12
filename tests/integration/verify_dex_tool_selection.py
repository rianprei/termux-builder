"""Build signed APK/AAB artifacts through configured D8 and optional DX launchers."""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

import builder
import yaml


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('sdk', 'aapt2', 'd8', 'apksigner', 'dexdump', 'bundletool-jar'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--dx')
    parser.add_argument('--target-sdk', type=int, default=36)
    args = parser.parse_args()
    environment = dict(os.environ, PYTHONPATH=str(Path(builder.__file__).resolve().parent.parent))
    with tempfile.TemporaryDirectory(prefix='dex-tool-selection-fixture-') as temp:
        root = Path(temp)
        for kind in ('d8', 'dx') if args.dx else ('d8',):
            project = root / kind
            result = subprocess.run([sys.executable, '-m', 'builder', 'init', str(project)],
                                    env=environment, capture_output=True, text=True)
            assert result.returncode == 0, result.stdout + result.stderr
            platform = 'platforms/android-' + str(args.target_sdk) + '/android.jar'
            api = project / 'sdk' / platform
            api.parent.mkdir(parents=True)
            shutil.copyfile(Path(args.sdk) / platform, api)
            cached = project / '.cache/bundletool/bundletool-all-1.18.3.jar'
            cached.parent.mkdir(parents=True)
            shutil.copyfile(args.bundletool_jar, cached)
            marker = project / 'dexer-calls.txt'
            launcher = project / ('configured ' + kind + ' launcher')
            actual = str(Path(args.d8 if kind == 'd8' else args.dx).resolve())
            launcher.write_text('#!' + sys.executable + '\nimport os,sys\n'
                                'with open(' + repr(str(marker)) + ',"a") as calls:\n'
                                '    calls.write(repr(sys.argv[1:])+"\\n")\n'
                                'os.execv(' + repr(actual) + ',[' + repr(actual) + ']+sys.argv[1:])\n')
            launcher.chmod(0o755)
            config_file = project / 'project.yml'
            raw = yaml.safe_load(config_file.read_text())
            raw['android'].update({'sdk-path': 'sdk', 'target-sdk': args.target_sdk, 'java-version': 17})
            raw['bins'] = {'aapt2': str(Path(args.aapt2).resolve()), kind: str(launcher),
                           'apksigner': str(Path(args.apksigner).resolve())}
            config_file.write_text(yaml.safe_dump(raw))
            source = next((project / 'src/java').rglob('MainActivity.java'))
            package = re.search(r'package\s+([\w.]+);', source.read_text()).group(1)
            source.write_text(source.read_text().replace('extends Activity {',
                              'extends Activity { static int libraryValue = LibraryBridge.value();'))
            assert 'LibraryBridge.value()' in source.read_text()
            library_source = project / 'library-source/LibraryBridge.java'
            library_source.parent.mkdir()
            library_source.write_text('package ' + package + '; public class LibraryBridge {'
                                      ' public static int value() { return 7; }}')
            classes = project / 'library-classes'
            subprocess.run([shutil.which('javac'), '--release', '8', '-d', str(classes),
                            str(library_source)], check=True, capture_output=True)
            jar = project / '.libs/fixture-library.jar'
            jar.parent.mkdir()
            with zipfile.ZipFile(jar, 'w') as archive:
                for binary in sorted(classes.rglob('*.class')):
                    archive.write(binary, binary.relative_to(classes).as_posix())

            build_environment = dict(environment)
            if kind == 'dx':
                isolated_path = project / 'isolated-path'
                isolated_path.mkdir()
                for name in ('java', 'javac', 'jarsigner', 'keytool', 'sh', 'bash', 'dirname',
                             'basename', 'readlink', 'uname', 'sed', 'grep', 'cat', 'dalvikvm'):
                    executable = shutil.which(name)
                    if executable:
                        (isolated_path / name).symlink_to(executable)
                build_environment['PATH'] = str(isolated_path) + (':/system/bin' if sys.platform == 'android' else '')
                assert shutil.which('d8', path=build_environment['PATH']) is None

            for build_number in range(1, 7):
                aab = build_number == 2
                automatic = build_number > 3
                if build_number == 4:
                    del raw['bins'][kind]
                    config_file.write_text(yaml.safe_dump(raw))
                    if kind == 'd8':
                        build_environment['PATH'] = str(Path(actual).parent) + os.pathsep + environment['PATH']
                    else:
                        (isolated_path / 'dx').symlink_to(actual)
                if build_number == 6:
                    added = library_source.with_name('LibraryAdded.java')
                    added.write_text('package ' + package + '; public class LibraryAdded {}')
                    subprocess.run([shutil.which('javac'), '--release', '8', '-d', str(classes),
                                    str(added)], check=True, capture_output=True)
                    binary = classes / Path(package.replace('.', '/')) / 'LibraryAdded.class'
                    with zipfile.ZipFile(jar, 'a') as archive:
                        archive.write(binary, binary.relative_to(classes).as_posix())
                result = subprocess.run([sys.executable, '-m', 'builder', 'build', str(project)]
                                        + (['--aab'] if aab else []), env=build_environment,
                                        capture_output=True, text=True)
                output = result.stdout + result.stderr
                print(output, flush=True)
                assert result.returncode == 0, (kind, result.returncode)
                assert ('DEX compatibility fallback:' in output) == (kind == 'dx'), output
                assert ('Dexing library: fixture-library.jar' in output) == (build_number != 5), output
                java_class = project / '.build/bin/classes/java' / Path(package.replace('.', '/')) / 'MainActivity.class'
                bytecode = java_class.read_bytes()
                assert bytecode[:4] == b'\xca\xfe\xba\xbe'
                assert int.from_bytes(bytecode[6:8], 'big') == (61 if kind == 'd8' else 52)
                artifact, = (project / '.build').glob('*.aab' if aab else '*.apk')
                definitions = set()
                with zipfile.ZipFile(artifact) as archive:
                    assert archive.testzip() is None
                    dex_names = [name for name in archive.namelist()
                                 if re.fullmatch(r'base/dex/classes\d*\.dex' if aab else r'classes\d*\.dex', name)]
                    assert dex_names, archive.namelist()
                    for name in dex_names:
                        dex = project / 'inspect.dex'
                        dex.write_bytes(archive.read(name))
                        listing = subprocess.run([args.dexdump, str(dex)], check=True,
                                                 capture_output=True, text=True).stdout
                        definitions.update(re.findall(r"Class descriptor\s*:\s*'([^']+)'", listing))
                for name in ('MainActivity', 'LibraryBridge'):
                    assert 'L' + package.replace('.', '/') + '/' + name + ';' in definitions, definitions
                added_descriptor = 'L' + package.replace('.', '/') + '/LibraryAdded;'
                assert (added_descriptor in definitions) == (build_number == 6), definitions
                if aab:
                    subprocess.run(['java', '-jar', args.bundletool_jar, 'validate', '--bundle=' + str(artifact)],
                                   check=True, capture_output=True)
                    verification = subprocess.run(['jarsigner', '-verify', '-strict', str(artifact)],
                                                  capture_output=True, text=True)
                    assert verification.returncode in (0, 4) and 'jar verified' in verification.stdout.lower()
                else:
                    subprocess.run([args.apksigner, 'verify', str(artifact)], check=True, capture_output=True)
                # Opaque launchers can invoke changing external tools: their library DEX must be regenerated.
                calls = marker.read_text().splitlines()
                assert sum(call.endswith(repr(str(jar)) + ']') for call in calls) == min(build_number, 3), calls
                assert len(calls) == 2 * min(build_number, 3), calls
                print('DEXER VERIFIED', kind, 'automatic' if automatic else 'configured', 'AAB' if aab else 'APK',
                      'Java target, application/library DEX, CRC and signature', flush=True)
        print('DEX tool selection regression complete', flush=True)


if __name__ == '__main__':
    main()
