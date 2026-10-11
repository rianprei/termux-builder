import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from builder import cli
from builder.utils import project_lock


class ProjectConcurrencyTests(unittest.TestCase):
    def test_lock_requires_an_existing_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'file'
            path.write_text('unchanged')
            for invalid in (path, path.parent / 'missing'):
                with self.subTest(path=invalid), self.assertRaisesRegex(RuntimeError, 'Cannot open project directory'):
                    with project_lock(str(invalid)):
                        self.fail('Accepted invalid project directory')
            self.assertEqual(path.read_text(), 'unchanged')

    def test_exception_releases_lock_and_other_projects_remain_available(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            with self.assertRaisesRegex(ValueError, 'fixture failure'):
                with project_lock(first), project_lock(second):
                    with self.assertRaisesRegex(RuntimeError, 'already active'):
                        with project_lock(first):
                            self.fail('Acquired a held project')
                    raise ValueError('fixture failure')
            with project_lock(first), project_lock(second):
                pass

    def test_cli_mutations_refuse_project_locked_by_another_process(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            build = root / '.build'
            build.mkdir()
            marker = build / 'preserve.txt'
            marker.write_text('active build')
            alias = root / 'alias'
            alias.symlink_to(root, target_is_directory=True)
            config = SimpleNamespace(project_dir=str(alias), build_dir=str(build),
                bin_dir=str(build), aab_enabled=False)
            holder = subprocess.Popen([sys.executable, '-c',
                'import fcntl, os, sys; fd=os.open(sys.argv[1], os.O_RDONLY | os.O_DIRECTORY); '
                'fcntl.flock(fd, fcntl.LOCK_EX); print("ready", flush=True); sys.stdin.read()', str(root)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(holder.stdout.readline().strip(), 'ready')
                args = argparse.Namespace(project=str(alias), flavor=None, clean=True, install=False, aab=False,
                    coverage=False, coverage_report=None)
                with patch('builder.config.Config', return_value=config), patch('builder.deps.resolve') as resolve, patch('builder.testing.run_tests') as tests:
                    for action in (cli._build, cli._clean, cli._deps, cli._test):
                        with self.subTest(action=action.__name__):
                            with self.assertRaisesRegex(RuntimeError, 'already active'):
                                action(args)
                            self.assertEqual(marker.read_text(), 'active build')
                            resolve.assert_not_called()
                            tests.assert_not_called()
                    args.aab = True
                    with self.assertRaisesRegex(RuntimeError, 'already active'):
                        cli._build(args)
                    with patch.object(sys, 'argv', ['termux-builder', 'clean', str(alias)]):
                        with self.assertLogs('termux-builder', level='ERROR') as messages:
                            with self.assertRaises(SystemExit) as exited:
                                cli.main()
                    self.assertEqual(exited.exception.code, 1)
                    self.assertIn('already active', messages.output[0])
                    self.assertEqual(marker.read_text(), 'active build')
                holder.kill()
                holder.wait(timeout=5)
                with patch('builder.config.Config', return_value=config):
                    cli._clean(args)
                self.assertFalse(build.exists())
                self.assertEqual(sorted(p.name for p in root.iterdir()), ['alias'])
            finally:
                if holder.poll() is None:
                    holder.kill()
                    holder.wait(timeout=5)
                holder.stdin.close()
                holder.stdout.close()


if __name__ == '__main__':
    unittest.main()
