from pathlib import Path
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from builder.testing import run_tests, _find_test_classes


class TestOutputInvalidationTests(unittest.TestCase):
    def test_discovery_preserves_package_names_containing_class(self):
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp) / 'example/classic'
            package.mkdir(parents=True)
            (package / 'FeatureTest.class').write_bytes(b'fixture')
            (package / 'Helper.class').write_bytes(b'fixture')
            (package / 'FeatureTest$Inner.class').write_bytes(b'fixture')
            self.assertEqual(_find_test_classes(temp), ['example.classic.FeatureTest'])

    def test_kotlin_uses_compiler_jvm_target_spelling(self):
        for version, expected in ((8, '1.8'), (17, '17')):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                source = root / 'src/test/ExampleTest.kt'
                source.parent.mkdir(parents=True)
                source.write_text('class ExampleTest')
                config = SimpleNamespace(
                    project_dir=temp, build_dir=str(root / '.build'),
                    android_jar='android.jar', java_classes_dir='java',
                    kotlin_classes_dir='kotlin', java_version=version,
                    bin_kotlinc='kotlinc', find_lib_jars=lambda: [],
                )
                with mock.patch('builder.testing._find_junit', return_value='junit.jar'), \
                     mock.patch('builder.testing._find_test_classes', return_value=['ExampleTest']), \
                     mock.patch('builder.testing.find_bin', return_value='java'), \
                     mock.patch('builder.testing.run', return_value=SimpleNamespace(returncode=0)) as execute:
                    self.assertTrue(run_tests(config))
                command = execute.call_args_list[0].args[0]
                self.assertEqual(command[command.index('-jvm-target') + 1], expected)

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
