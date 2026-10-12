"""Verify resource preflight and real AAPT1 APKs, including density splits."""
import argparse
import base64
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

        densities = ('ldpi', 'mdpi', 'hdpi', 'xhdpi', 'xxhdpi', 'xxxhdpi')
        resource_root = Path(Config(project).res_dir)
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')
        for density in densities:
            directory = resource_root / ('drawable-' + density)
            directory.mkdir(parents=True, exist_ok=True)
            (directory / 'density_fixture.png').write_bytes(png)
        raw['android']['density-splits'] = True
        config_path.write_text(yaml.safe_dump(raw))
        before = config_path.read_bytes()
        result = invoke(['build', str(project)], dict(environment, PATH=str(tools) + os.pathsep + environment['PATH']))
        output = result.stdout + result.stderr
        print(output, flush=True)
        assert result.returncode == 0 and output.count('Density split:') == 6, output
        split_paths = [artifact.with_name(artifact.stem.removesuffix('-debug') + '-' + density + '-debug.apk')
                       for density in densities]
        base_signing = subprocess.run([args.apksigner, 'verify', '--print-certs', str(artifact)],
                                      check=True, capture_output=True, text=True).stdout
        certificate_pattern = r'certificate SHA-256 digest: ([0-9a-fA-F]{64})'
        certificates = set(re.findall(certificate_pattern, base_signing))
        assert len(certificates) == 1
        config = Config(project)
        package_pattern = r"^package: name='([^']*)' versionCode='([^']*)' versionName='([^']*)'"
        base_badging = subprocess.run([args.aapt, 'dump', 'badging', str(artifact)],
                                      check=True, capture_output=True, text=True).stdout.splitlines()[0]
        package_metadata = re.match(package_pattern, base_badging).groups()
        assert package_metadata == (config.package_name, str(config.version_code), config.version_name)
        for density, split in zip(densities, split_paths):
            with zipfile.ZipFile(split) as archive:
                assert archive.testzip() is None
                assert 'classes.dex' not in archive.namelist()
                assert 'res/drawable-' + density + '-v4/density_fixture.png' in archive.namelist()
            signing = subprocess.run([args.apksigner, 'verify', '--print-certs', str(split)],
                                     check=True, capture_output=True, text=True).stdout
            assert set(re.findall(certificate_pattern, signing)) == certificates
            badging = subprocess.run([args.aapt, 'dump', 'badging', str(split)],
                                     check=True, capture_output=True, text=True).stdout.splitlines()[0]
            split_metadata = re.match(package_pattern, badging).groups()
            assert split_metadata[:2] == package_metadata[:2], (split_metadata, package_metadata)
            # AAPT1 generates versionCode but omits optional versionName in split manifests.
            assert split_metadata[2] in ('', package_metadata[2])
            assert "split='config." + density + "_v4'" in badging
        with zipfile.ZipFile(artifact) as archive:
            assert archive.testzip() is None and not any('density_fixture.png' in name for name in archive.namelist())
            dex.write_bytes(archive.read('classes.dex'))
        listing = subprocess.run([args.dexdump, str(dex)], check=True, capture_output=True, text=True).stdout
        assert re.search(r"Class descriptor\s*:\s*'" + re.escape(descriptor) + "'", listing)
        subprocess.run([args.apksigner, 'verify', str(artifact)], check=True, capture_output=True)
        assert config_path.read_bytes() == before
        print('REAL AAPT1 SIX DENSITY SPLITS VERIFIED: signed base plus six resource-only APKs', flush=True)

        previous = {path: path.read_bytes() for path in [artifact] + split_paths}
        raw['android']['abi-splits'] = True
        config_path.write_text(yaml.safe_dump(raw))
        result = invoke(['build', str(project), '--clean'], dict(environment, PATH=str(tools) + os.pathsep + environment['PATH']))
        output = result.stdout + result.stderr
        assert result.returncode == 1 and 'abi-splits' in output and 'density-splits' in output, output
        assert all(path.read_bytes() == data for path, data in previous.items())
        raw['android']['abi-splits'] = False
        config_path.write_text(yaml.safe_dump(raw))
        before = config_path.read_bytes()

        hdpi = resource_root / 'drawable-hdpi/density_fixture.png'
        hdpi.unlink()
        result = invoke(['build', str(project)], dict(environment, PATH=str(tools) + os.pathsep + environment['PATH']))
        output = result.stdout + result.stderr
        assert result.returncode == 1 and 'has no definition for density split' in output, output
        assert 'BUILD SUCCESSFUL' not in output
        assert all(path.read_bytes() == data for path, data in previous.items())
        default = resource_root / 'drawable/density_fixture.png'
        default.parent.mkdir(parents=True, exist_ok=True)
        default.write_bytes(png)
        result = invoke(['build', str(project)], dict(environment, PATH=str(tools) + os.pathsep + environment['PATH']))
        output = result.stdout + result.stderr
        print(output, flush=True)
        assert result.returncode == 0 and output.count('Density split:') == 6, output
        for split in split_paths:
            with zipfile.ZipFile(split) as archive:
                assert archive.testzip() is None
                if split == split_paths[2]:
                    assert not any('density_fixture.png' in name for name in archive.namelist())
            subprocess.run([args.apksigner, 'verify', str(split)], check=True, capture_output=True)
        with zipfile.ZipFile(artifact) as archive:
            assert archive.testzip() is None and any('density_fixture.png' in name for name in archive.namelist())
            dex.write_bytes(archive.read('classes.dex'))
        listing = subprocess.run([args.dexdump, str(dex)], check=True, capture_output=True, text=True).stdout
        assert re.search(r"Class descriptor\s*:\s*'" + re.escape(descriptor) + "'", listing)
        subprocess.run([args.apksigner, 'verify', str(artifact)], check=True, capture_output=True)
        assert config_path.read_bytes() == before
        print('REAL AAPT1 DENSITY REGRESSIONS COMPLETE: incompatible flags preserve outputs; sparse '
              'resources fail explicitly; recovery removes stale hdpi payload without clean', flush=True)


if __name__ == '__main__':
    main()
