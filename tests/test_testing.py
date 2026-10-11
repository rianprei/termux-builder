from pathlib import Path
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from builder.testing import run_tests, _find_test_classes, _write_coverage_report


class TestOutputInvalidationTests(unittest.TestCase):
    def test_coverage_requires_fresh_valid_report_before_publication(self):
        for payload in ('missing', 'malformed', 'wrong_root', 'no_html'):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as temp:
                report = Path(temp) / 'report'
                report.mkdir()
                previous = report / 'coverage.xml'
                previous.write_text('previous result')
                config = SimpleNamespace(build_dir=temp, java_classes_dir='java',
                    kotlin_classes_dir='kotlin', sources_dir='src')
                def generate(command):
                    output = Path(command[command.index('--xml') + 1])
                    if payload != 'missing':
                        output.write_text('<broken' if payload == 'malformed' else
                            '<other/>' if payload == 'wrong_root' else '<report name="fixture"/>')
                with mock.patch('builder.testing._find_jacoco', return_value='cli.jar'), \
                     mock.patch('builder.testing.run', side_effect=generate):
                    with self.assertRaisesRegex(RuntimeError, 'Coverage report'):
                        _write_coverage_report(config, 'exec', str(report))
                self.assertEqual(previous.read_text(), 'previous result')
                self.assertEqual(list(Path(temp).iterdir()), [report])

    def test_coverage_report_refuses_unsafe_existing_destinations(self):
        for kind in ('root_symlink', 'nested_symlink', 'fifo', 'file', 'hardlink'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                outside = root / 'outside'
                outside.mkdir()
                marker = outside / 'coverage.xml'
                marker.write_text('preserve')
                report = root / 'report'
                if kind == 'root_symlink':
                    report.symlink_to(outside, target_is_directory=True)
                elif kind == 'file':
                    report.write_text('preserve')
                else:
                    report.mkdir()
                    if kind == 'hardlink':
                        os.link(marker, report / 'coverage.xml')
                    elif kind == 'fifo':
                        os.mkfifo(report / 'coverage.xml')
                    else:
                        (report / 'package').symlink_to(outside, target_is_directory=True)
                config = SimpleNamespace(build_dir=str(root / 'build'),
                    java_classes_dir='java', kotlin_classes_dir='kotlin', sources_dir='src')
                with mock.patch('builder.testing._find_jacoco', return_value='cli.jar') as lookup, \
                     mock.patch('builder.testing.run') as execute:
                    with self.assertRaisesRegex(RuntimeError, 'Coverage report'):
                        _write_coverage_report(config, 'exec', str(report))
                    lookup.assert_not_called()
                    execute.assert_not_called()
                self.assertEqual(marker.read_text(), 'preserve')

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
                java_source = source.parent / 'JavaInteropTest.java'
                java_source.write_text('class JavaInteropTest {}')
                config = SimpleNamespace(
                    project_dir=temp, build_dir=str(root / '.build'),
                    android_jar='android.jar', java_classes_dir='java',
                    kotlin_classes_dir='kotlin', java_version=version,
                    bin_kotlinc='kotlinc', bin_javac='javac', find_lib_jars=lambda: [],
                )
                with mock.patch('builder.testing._find_junit', return_value='junit.jar'), \
                     mock.patch('builder.testing._find_test_classes', return_value=['ExampleTest']), \
                     mock.patch('builder.testing.find_bin', return_value='java'), \
                     mock.patch('builder.testing.run', return_value=SimpleNamespace(returncode=0)) as execute:
                    self.assertTrue(run_tests(config))
                command = execute.call_args_list[0].args[0]
                self.assertEqual(command[command.index('-jvm-target') + 1], expected)
                self.assertEqual(command[0], 'kotlinc')
                self.assertIn(str(java_source), command)
                java_command = execute.call_args_list[1].args[0]
                self.assertEqual(java_command[0], 'javac')
                self.assertIn(str(root / '.build/test-classes'), java_command[java_command.index('-classpath') + 1].split(os.pathsep))

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
