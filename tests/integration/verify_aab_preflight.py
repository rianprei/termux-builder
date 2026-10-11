"""Exercise AAB missing-tool diagnostics through the public CLI without deleting prior outputs."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import yaml

environment = os.environ.copy()
environment['PYTHONPATH'] = str(Path(__file__).resolve().parents[2])
tools = {name: shutil.which(name) for name in ('java', 'jarsigner')}
if not all(tools.values()):
    raise RuntimeError('Real Java and jarsigner are required to isolate each missing-tool scenario')
with tempfile.TemporaryDirectory(prefix='termux-builder-aab-preflight-') as temp:
    for missing in ('java', 'jarsigner', 'aapt2'):
        project = Path(temp) / missing
        subprocess.run([sys.executable, '-m', 'builder', 'init', str(project)],
            env=environment, check=True, capture_output=True)
        config_path = project / 'project.yml'
        config = yaml.safe_load(config_path.read_text())
        config['bins'] = {'aapt2': str(project / 'absent-aapt2')}
        config_path.write_text(yaml.safe_dump(config))
        marker = project / '.build/previous.apk'
        marker.parent.mkdir()
        marker.write_bytes(b'previous output fixture')
        isolated_path = project / 'isolated-path'
        isolated_path.mkdir()
        for name, path in tools.items():
            if name != missing:
                (isolated_path / name).symlink_to(path)
        isolated_environment = dict(environment, PATH=str(isolated_path))
        result = subprocess.run([sys.executable, '-m', 'builder', 'build', str(project), '--aab', '--clean'],
            env=isolated_environment, capture_output=True, text=True)
        if result.returncode != 1 or missing + ' not found' not in result.stdout + result.stderr:
            raise RuntimeError('Missing-tool diagnostic/exit code mismatch: ' + result.stdout + result.stderr)
        if marker.read_bytes() != b'previous output fixture':
            raise RuntimeError('Preflight failure deleted prior output')
        print('REAL AAB PREFLIGHT: ' + missing + ' missing, exit 1, prior output preserved')
