"""Preserve verified APK/AAB outputs on missing compilers; optionally build with native ECJ."""
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
    parser.add_argument('--target-sdk', type=int, default=36)
    parser.add_argument('--ecj', action='store_true', help='Require the actual Termux ECJ/Dalvik fallback')
    args = parser.parse_args()
    environment = dict(os.environ, PYTHONPATH=str(Path(builder.__file__).resolve().parent.parent))
    with tempfile.TemporaryDirectory(prefix='java-preflight-fixture-') as temp:
        project = Path(temp) / 'app'
        subprocess.run([sys.executable, '-m', 'builder', 'init', str(project)],
                       env=environment, check=True, capture_output=True)
        platform = 'platforms/android-' + str(args.target_sdk) + '/android.jar'
        api = project / 'sdk' / platform
        api.parent.mkdir(parents=True)
        shutil.copyfile(Path(args.sdk) / platform, api)
        bundletool = project / '.cache/bundletool/bundletool-all-1.18.3.jar'
        bundletool.parent.mkdir(parents=True)
        shutil.copyfile(args.bundletool_jar, bundletool)
        config_file = project / 'project.yml'
        raw = yaml.safe_load(config_file.read_text())
        raw['android'].update({'sdk-path': 'sdk', 'target-sdk': args.target_sdk, 'java-version': 17})
        raw['bins'] = {name: str(Path(getattr(args, name)).resolve()) for name in ('aapt2', 'd8', 'apksigner')}
        javac = shutil.which('javac')
        assert javac, 'fixture baseline requires a real javac'
        raw['bins']['javac'] = javac
        config_file.write_text(yaml.safe_dump(raw))

        def build(aab, env, clean=False):
            result = subprocess.run([sys.executable, '-m', 'builder', 'build', str(project)]
                                    + (['--aab'] if aab else []) + (['--clean'] if clean else []),
                                    env=env, capture_output=True, text=True)
            print(result.stdout + result.stderr, flush=True)
            return result

        def verify(aab, java_version=17):
            artifact, = (project / '.build').glob('*.aab' if aab else '*.apk')
            with zipfile.ZipFile(artifact) as archive:
                assert archive.testzip() is None
                dex = project / 'inspect.dex'
                dex.write_bytes(archive.read('base/dex/classes.dex' if aab else 'classes.dex'))
            listing = subprocess.run([args.dexdump, str(dex)], check=True, capture_output=True, text=True).stdout
            package = re.search(r'package\s+([\w.]+);', next((project / 'src/java').rglob('MainActivity.java')).read_text()).group(1)
            descriptor = 'L' + package.replace('.', '/') + '/MainActivity;'
            assert re.search(r"Class descriptor\s*:\s*'" + re.escape(descriptor) + "'", listing)
            bytecode = (project / '.build/bin/classes/java' / Path(package.replace('.', '/')) / 'MainActivity.class').read_bytes()
            assert bytecode[:4] == b'\xca\xfe\xba\xbe' and int.from_bytes(bytecode[6:8], 'big') == java_version + 44
            if aab:
                subprocess.run(['java', '-jar', args.bundletool_jar, 'validate', '--bundle=' + str(artifact)],
                               check=True, capture_output=True)
                signature = subprocess.run(['jarsigner', '-verify', '-strict', str(artifact)], capture_output=True, text=True)
                assert signature.returncode in (0, 4) and 'jar verified' in signature.stdout.lower()
            else:
                subprocess.run([args.apksigner, 'verify', str(artifact)], check=True, capture_output=True)
            print('JAVA COMPILER ARTIFACT VERIFIED', 'AAB' if aab else 'APK', 'Java', java_version, 'DEX, CRC, signature', flush=True)

        for aab in (False, True):
            assert build(aab, environment).returncode == 0
            verify(aab)
        previous = {path: path.read_bytes() for path in (project / '.build').glob('*') if path.suffix in ('.apk', '.aab')}
        isolated = project / 'isolated-path'
        isolated.mkdir()
        for name in ('java', 'jarsigner', 'keytool', 'sh', 'bash', 'dirname', 'basename',
                     'readlink', 'expr', 'pwd', 'ls', 'uname', 'sed', 'grep', 'cat', 'mkdir'):
            tool = shutil.which(name)
            if tool:
                (isolated / name).symlink_to(tool)
        missing_environment = dict(environment, PATH=str(isolated))
        assert shutil.which('dalvikvm', path=missing_environment['PATH']) is None
        for damage in ('absent', 'non-executable', 'directory'):
            binary = project / damage
            if damage == 'non-executable':
                binary.write_text('not a compiler')
                binary.chmod(0o600)
            elif damage == 'directory':
                binary.mkdir()
            raw['bins']['javac'] = str(binary)
            config_file.write_text(yaml.safe_dump(raw))
            before = config_file.read_bytes()
            for aab in (False, True):
                result = build(aab, missing_environment, clean=True)
                assert result.returncode == 1 and 'Java compiler' in result.stdout + result.stderr
                assert all(path.is_file() and path.read_bytes() == data for path, data in previous.items())
                assert config_file.read_bytes() == before
                print('JAVA PREFLIGHT REJECTED', damage, 'AAB' if aab else 'APK', 'verified artifacts preserved', flush=True)

        if args.ecj:
            dalvikvm = shutil.which('dalvikvm')
            assert dalvikvm, '--ecj requires real Dalvik'
            (isolated / 'dalvikvm').symlink_to(dalvikvm)
            raw['bins']['javac'] = str(project / 'absent')
            raw['android']['java-version'] = 99
            config_file.write_text(yaml.safe_dump(raw))
            before = config_file.read_bytes()
            for aab in (False, True):
                result = build(aab, missing_environment, clean=True)
                assert result.returncode == 1 and 'ECJ preflight failed for Java 99' in result.stdout + result.stderr
                assert all(path.is_file() and path.read_bytes() == data for path, data in previous.items())
                assert config_file.read_bytes() == before
                print('ECJ PREFLIGHT REJECTED unsupported target', 'AAB' if aab else 'APK', 'verified artifacts preserved', flush=True)
            raw['android']['java-version'] = 8
            config_file.write_text(yaml.safe_dump(raw))
            for aab in (False, True):
                result = build(aab, missing_environment)
                assert result.returncode == 0 and 'Using ecj compiler' in result.stdout + result.stderr
                verify(aab, java_version=8)
            with zipfile.ZipFile(project / 'processor.jar', 'w'):
                pass
            raw['annotation-processors'] = ['processor.jar']
            config_file.write_text(yaml.safe_dump(raw))
            before = {path: path.read_bytes() for path in previous}
            result = build(False, missing_environment, clean=True)
            assert result.returncode == 1 and 'annotation processors require javac' in result.stdout + result.stderr
            assert all(path.read_bytes() == data for path, data in before.items())
            print('JAVA APT PREFLIGHT REJECTED despite native ECJ; verified artifacts preserved', flush=True)
        print('Java compiler preflight regression complete', flush=True)


if __name__ == '__main__':
    main()
