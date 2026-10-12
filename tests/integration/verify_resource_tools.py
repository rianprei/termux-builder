"""Verify resource tool preflight and a real APK through the AAPT1 fallback."""
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
    for name in ('sdk', 'aapt', 'aapt2', 'd8', 'apksigner', 'dexdump'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--target-sdk', type=int, default=36)
    args = parser.parse_args()
    environment = dict(os.environ, PYTHONPATH=str(Path(builder.__file__).resolve().parent.parent))
    with tempfile.TemporaryDirectory(prefix='resource-tools-fixture-') as temp:
        root = Path(temp)
        sdk = root / 'sdk'
        platform = 'platforms/android-' + str(args.target_sdk) + '/android.jar'
        jar = sdk / platform
        jar.parent.mkdir(parents=True)
        shutil.copyfile(Path(args.sdk) / platform, jar)

        def invoke(arguments, env=environment):
            return subprocess.run([sys.executable, '-m', 'builder'] + arguments, cwd=root,
                                  env=env, capture_output=True, text=True)

        for kind in ('missing', 'non-executable', 'directory', 'unrelated-aapt2'):
            project = root / kind
            assert invoke(['init', str(project)]).returncode == 0
            binary = project / 'configured-aapt2'
            if kind == 'non-executable':
                binary.write_text('not executable')
                binary.chmod(0o600)
            elif kind == 'directory':
                binary.mkdir()
            isolated = project / 'tools'
            isolated.mkdir()
            if kind == 'unrelated-aapt2':
                (isolated / 'aapt2').symlink_to(Path(args.aapt2).resolve())
            config_path = project / 'project.yml'
            raw = yaml.safe_load(config_path.read_text())
            raw['android'].update({'sdk-path': str(sdk), 'target-sdk': args.target_sdk})
            raw['bins'] = {'aapt2': str(binary)}
            config_path.write_text(yaml.safe_dump(raw))
            before = config_path.read_bytes()
            marker = project / '.build/previous.apk'
            marker.parent.mkdir()
            marker.write_bytes(b'prior output fixture')
            result = invoke(['build', str(project), '--clean'], dict(environment, PATH=str(isolated)))
            output = result.stdout + result.stderr
            preserved = marker.is_file() and marker.read_bytes() == b'prior output fixture'
            diagnosed = result.returncode == 1 and 'aapt2' in output and 'aapt' in output and 'install' in output
            print('RESOURCE PREFLIGHT', kind, 'exit', result.returncode, 'preserved', preserved,
                  'diagnosed', diagnosed, flush=True)
            assert preserved and diagnosed and 'Traceback' not in output, output
            assert config_path.read_bytes() == before

        project = root / 'fallback'
        assert invoke(['init', str(project)]).returncode == 0
        tools = project / 'tools'
        tools.mkdir()
        (tools / 'aapt').symlink_to(Path(args.aapt).resolve())
        (tools / 'aapt2').symlink_to(Path(args.aapt2).resolve())
        binary = project / 'non-executable-aapt2'
        binary.write_text('not executable')
        binary.chmod(0o600)
        config_path = project / 'project.yml'
        raw = yaml.safe_load(config_path.read_text())
        raw['android'].update({'sdk-path': str(sdk), 'target-sdk': args.target_sdk})
        raw['bins'] = {'aapt2': str(binary), 'd8': str(Path(args.d8).resolve()),
                       'apksigner': str(Path(args.apksigner).resolve())}
        config_path.write_text(yaml.safe_dump(raw))
        before = config_path.read_bytes()
        result = invoke(['build', str(project)], dict(environment, PATH=str(tools) + os.pathsep + environment['PATH']))
        output = result.stdout + result.stderr
        print(output, flush=True)
        assert result.returncode == 0 and 'Using aapt (v1 fallback)' in output, output
        assert config_path.read_bytes() == before
        artifact, = (project / '.build').glob('*.apk')
        with zipfile.ZipFile(artifact) as archive:
            assert archive.testzip() is None
            dex = root / 'inspect.dex'
            dex.write_bytes(archive.read('classes.dex'))
        listing = subprocess.run([args.dexdump, str(dex)], check=True, capture_output=True, text=True).stdout
        descriptor = 'L' + Config(project).package_name.replace('.', '/') + '/MainActivity;'
        assert re.search(r"Class descriptor\s*:\s*'" + re.escape(descriptor) + "'", listing)
        subprocess.run([args.apksigner, 'verify', str(artifact)], check=True, capture_output=True)
        print('REAL AAPT1 FALLBACK APK VERIFIED: DEX definition, CRC and signature; configured non-executable '
              'aapt2 ignored, unrelated executable aapt2 not selected', flush=True)


if __name__ == '__main__':
    main()
