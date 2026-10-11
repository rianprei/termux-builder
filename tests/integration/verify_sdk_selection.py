"""Exercise SDK configuration errors and builds from an unrelated directory."""
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
from builder.config import Config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('sdk', 'aapt2', 'd8', 'apksigner', 'dexdump', 'bundletool-jar'):
        parser.add_argument('--' + name)
    parser.add_argument('--target-sdk', type=int, default=36)
    args = parser.parse_args()
    if args.sdk and not all((args.aapt2, args.d8, args.apksigner, args.dexdump, args.bundletool_jar)):
        parser.error('positive builds require all tool paths and bundletool-jar with --sdk')
    environment = dict(os.environ, PYTHONPATH=str(Path(builder.__file__).resolve().parent.parent))
    with tempfile.TemporaryDirectory(prefix='sdk-selection-fixture-') as temp:
        root = Path(temp)
        outside = root / 'outside'
        outside.mkdir()

        def invoke(arguments):
            return subprocess.run([sys.executable, '-m', 'builder'] + arguments, cwd=outside,
                                  env=environment, capture_output=True, text=True)

        cases = [('top-level', 'misplaced-sdk'), ('both-levels', 'misplaced-sdk'),
                 ('empty', ''), ('whitespace', '  '), ('nul', 'private-token\x00'),
                 ('integer', 42), ('boolean', True), ('list', []), ('mapping', {})]
        for kind, value in cases:
            for aab in (False, True):
                project = root / (kind + ('-aab' if aab else '-apk'))
                assert invoke(['init', str(project)]).returncode == 0
                config_file = project / 'project.yml'
                raw = yaml.safe_load(config_file.read_text())
                if kind in ('top-level', 'both-levels'):
                    raw['sdk-path'] = value
                    if kind == 'both-levels':
                        raw['android']['sdk-path'] = 'sdk'
                else:
                    raw['android']['sdk-path'] = value
                config_file.write_text(yaml.safe_dump(raw))
                before = config_file.read_bytes()
                marker = project / '.build/previous.apk'
                marker.parent.mkdir()
                marker.write_bytes(b'prior output fixture')
                result = invoke(['build', str(project), '--clean'] + (['--aab'] if aab else []))
                output = result.stdout + result.stderr
                assert result.returncode == 1 and 'android.sdk-path' in output, output
                assert 'private-token' not in output and 'Traceback' not in output, output
                assert marker.read_bytes() == b'prior output fixture'
                assert config_file.read_bytes() == before
                print('SDK CONFIG REJECTED', kind, 'AAB' if aab else 'APK', 'exit 1, output preserved', flush=True)

        if args.sdk:
            project = root / 'healthy'
            assert invoke(['init', str(project)]).returncode == 0
            platform = 'platforms/android-' + str(args.target_sdk) + '/android.jar'
            jar = project / 'sdk' / platform
            jar.parent.mkdir(parents=True)
            shutil.copyfile(Path(args.sdk) / platform, jar)
            config_file = project / 'project.yml'
            raw = yaml.safe_load(config_file.read_text())
            raw['android'].update({'sdk-path': 'sdk', 'target-sdk': args.target_sdk})
            raw['bins'] = {'aapt2': str(Path(args.aapt2).resolve()), 'd8': str(Path(args.d8).resolve()),
                           'apksigner': str(Path(args.apksigner).resolve())}
            config_file.write_text(yaml.safe_dump(raw))
            assert Config(project).android_jar == str(jar)
            cached = project / '.cache/bundletool/bundletool-all-1.18.3.jar'
            cached.parent.mkdir(parents=True)
            shutil.copyfile(args.bundletool_jar, cached)
            for aab in (False, True):
                result = invoke(['build', str(project)] + (['--aab'] if aab else []))
                print(result.stdout + result.stderr, flush=True)
                assert result.returncode == 0, result.returncode
                artifact, = (project / '.build').glob('*.aab' if aab else '*.apk')
                with zipfile.ZipFile(artifact) as archive:
                    assert archive.testzip() is None
                    dex = project / 'inspect.dex'
                    dex.write_bytes(archive.read('base/dex/classes.dex' if aab else 'classes.dex'))
                listing = subprocess.run([args.dexdump, str(dex)], check=True, capture_output=True, text=True).stdout
                descriptor = 'L' + Config(project).package_name.replace('.', '/') + '/MainActivity;'
                assert re.search(r"Class descriptor\s*:\s*'" + re.escape(descriptor) + "'", listing)
                if aab:
                    verification = subprocess.run(['jarsigner', '-verify', '-strict', str(artifact)], capture_output=True, text=True)
                    assert verification.returncode in (0, 4) and 'jar verified' in verification.stdout.lower()
                else:
                    subprocess.run([args.apksigner, 'verify', str(artifact)], check=True, capture_output=True)
                print('RELATIVE SDK REAL BUILD VERIFIED', 'AAB' if aab else 'APK', 'DEX class and signature', flush=True)
        print('SDK selection regression complete', flush=True)


if __name__ == '__main__':
    main()
