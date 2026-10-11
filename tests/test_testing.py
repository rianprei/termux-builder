from pathlib import Path
import os
import tempfile
from types import SimpleNamespace
import unittest

from builder.testing import run_tests


class TestOutputInvalidationTests(unittest.TestCase):
    def test_coverage_refuses_symlink_hardlink_and_directory_execution_outputs(self):
        for kind in ('symlink', 'hardlink', 'directory', 'fifo'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                target = root / 'preserve'
                target.write_bytes(b'private fixture data')
                build = root / '.build'
                build.mkdir()
                output = build / 'jacoco.exec'
                if kind == 'symlink':
                    output.symlink_to(target)
                elif kind == 'hardlink':
                    os.link(target, output)
                elif kind == 'directory':
                    output.mkdir()
                else:
                    os.mkfifo(output)
                config = SimpleNamespace(project_dir=temp, build_dir=str(build))
                with self.assertRaisesRegex(RuntimeError, 'JaCoCo execution output'):
                    run_tests(config, coverage=True)
                self.assertEqual(target.read_bytes(), b'private fixture data')

    def test_removal_of_all_sources_clears_old_test_bytecode(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / '.build/test-classes'
            output.mkdir(parents=True)
            (output / 'DeletedTest.class').write_bytes(b'obsolete')
            config = SimpleNamespace(project_dir=str(root), build_dir=str(root / '.build'))
            self.assertTrue(run_tests(config))
            self.assertFalse(output.exists())

    def test_test_output_symlink_does_not_delete_its_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            outside = root / 'outside'
            outside.mkdir()
            marker = outside / 'preserve'
            marker.write_text('unchanged')
            build = root / '.build'
            build.mkdir()
            (build / 'test-classes').symlink_to(outside, target_is_directory=True)
            config = SimpleNamespace(project_dir=str(root), build_dir=str(build))
            with self.assertRaisesRegex(RuntimeError, 'not a symlink'):
                run_tests(config)
            self.assertEqual(marker.read_text(), 'unchanged')


if __name__ == '__main__':
    unittest.main()
