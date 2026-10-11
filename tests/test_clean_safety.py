import json
from pathlib import Path
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from builder import cli
from builder.config import Config, validate_build_directory


class CleanSafetyTests(unittest.TestCase):
    def test_clean_preserves_nested_sdk_and_cache_contents(self):
        for field, directory, child in (('sdk_dir', 'sdk', 'build-tools'), ('cache_dir', '.cache', 'kapt')):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                parent = root / directory
                output = parent / child
                output.mkdir(parents=True)
                marker = output / 'tool.jar'
                marker.write_bytes(b'offline toolchain')
                config = SimpleNamespace(project_dir=temp, build_dir=str(output), **{field: str(parent)})
                with self.assertRaisesRegex(ValueError, 'build-path overlaps an input directory'):
                    cli._do_clean(config)
                self.assertEqual(marker.read_bytes(), b'offline toolchain')

    def test_clean_refuses_parent_traversal_with_different_symlink_semantics(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / 'project'
            project.mkdir()
            external = root / 'external'
            (external / 'child').mkdir(parents=True)
            (project / 'alias').symlink_to(external / 'child', target_is_directory=True)
            for output in (project / 'output', external / 'output'):
                output.mkdir()
                (output / 'preserve').write_text('original')
            config = SimpleNamespace(project_dir=str(project), build_dir=str(project / 'alias/../output'))
            with self.assertRaisesRegex(ValueError, 'ambiguous parent traversal'):
                cli._do_clean(config)
            for output in (project / 'output', external / 'output'):
                self.assertEqual((output / 'preserve').read_text(), 'original')

    def test_clean_refuses_output_symlink_with_trailing_components(self):
        for suffix in ('', '/', '/.', '/child/..'):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                project = root / 'project'
                project.mkdir()
                external = root / 'external'
                external.mkdir()
                (external / 'child').mkdir()
                marker = external / 'preserve'
                marker.write_text('original')
                link = project / '.build'
                link.symlink_to(external, target_is_directory=True)
                config = SimpleNamespace(project_dir=str(project), build_dir=str(link) + suffix)
                with self.assertRaisesRegex(ValueError, 'build-path'):
                    cli._do_clean(config)
                self.assertEqual(marker.read_text(), 'original')

    def test_clean_preserves_offline_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cache = root / '.cache'
            cache.mkdir()
            marker = cache / 'dependency.jar'
            marker.write_bytes(b'offline dependency')
            config = SimpleNamespace(project_dir=temp, build_dir=str(cache), cache_dir=str(cache))
            with self.assertRaisesRegex(ValueError, 'build-path'):
                cli._do_clean(config)
            self.assertEqual(marker.read_bytes(), b'offline dependency')

    def test_clean_preserves_configured_processor_and_r8_inputs(self):
        for field, value in (('r8_rules', '.build/rules.pro'), ('annotation_processors', ['.build/processor.jar'])):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                output = root / '.build'
                output.mkdir()
                path = root / (value if isinstance(value, str) else value[0])
                path.write_bytes(b'original input')
                config = SimpleNamespace(project_dir=temp, build_dir=str(output), **{field: value})
                with self.assertRaisesRegex(ValueError, 'build-path contains an input file'):
                    cli._do_clean(config)
                self.assertEqual(path.read_bytes(), b'original input')

    def test_public_cli_rejects_unsafe_config_without_touching_project(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / 'AndroidManifest.xml'
            original = '<manifest package="com.example.safe"/>'
            manifest.write_text(original)
            (root / 'project.yml').write_text(json.dumps({'android': {}, 'build-path': '.'}))
            for operation in (['clean', temp], ['build', temp, '--clean'], ['build', temp]):
                with self.subTest(operation=operation), patch.object(sys, 'argv', ['termux-builder', *operation]), \
                    patch.object(Config, '_resolve_android_jar', return_value='/fixture/android.jar'), \
                    patch('builder.deps.resolve') as resolve:
                    with self.assertLogs('termux-builder', level='ERROR') as messages:
                        with self.assertRaises(SystemExit) as exited:
                            cli.main()
                    self.assertEqual(exited.exception.code, 1)
                    self.assertIn('build-path', messages.output[0])
                    resolve.assert_not_called()
                    self.assertEqual(manifest.read_text(), original)

    def test_changed_input_alias_is_rechecked_before_clean(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / 'project'
            project.mkdir()
            output = root / 'output'
            output.mkdir()
            marker = output / 'preserve'
            marker.write_text('unchanged')
            original_source = root / 'original-source'
            original_source.mkdir()
            alias = project / 'custom-source'
            alias.symlink_to(original_source, target_is_directory=True)
            config = SimpleNamespace(project_dir=str(project), build_dir=str(output), sources_dir=str(alias))
            validate_build_directory(config)
            alias.unlink()
            alias.symlink_to(output, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'build-path'):
                cli._do_clean(config)
            self.assertEqual(marker.read_text(), 'unchanged')

    def test_build_directory_must_not_contain_signing_key(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            output = project / '.build'
            output.mkdir()
            key = output / 'release.p12'
            key.write_bytes(b'private signing key')
            config = SimpleNamespace(project_dir=temp, build_dir=str(output), keystore_path=str(key))
            with self.assertRaisesRegex(ValueError, 'build-path contains an input file'):
                cli._do_clean(config)
            self.assertEqual(key.read_bytes(), b'private signing key')

    def test_invalid_build_path_values_have_configuration_errors(self):
        for path in ('', '  ', None, True, 12, [], '\x00'):
            with self.subTest(path=path), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root / 'AndroidManifest.xml').write_text('<manifest package="com.example.safe"/>')
                (root / 'project.yml').write_text(json.dumps({'android': {}, 'build-path': path}))
                with self.assertRaisesRegex(ValueError, 'build-path must be a nonempty path'):
                    Config(temp)

    def test_clean_refuses_project_ancestors_and_input_directories(self):
        for location in ('.', '..', 'src', 'src/java', '.libs'):
            with self.subTest(location=location), tempfile.TemporaryDirectory() as temp:
                project = Path(temp) / 'project'
                project.mkdir()
                (project / 'project.yml').write_text('preserve')
                sources = project / 'src/java'
                sources.mkdir(parents=True)
                source = sources / 'Main.java'
                source.write_text('original source')
                libs = project / '.libs'
                libs.mkdir()
                jar = libs / 'local.jar'
                jar.write_bytes(b'original dependency')
                config = SimpleNamespace(project_dir=str(project), build_dir=str(project / location),
                    sources_dir=str(sources), libs_dir=str(libs))
                with self.assertRaisesRegex(ValueError, 'build-path'):
                    cli._do_clean(config)
                self.assertEqual(source.read_text(), 'original source')
                self.assertEqual(jar.read_bytes(), b'original dependency')
                self.assertEqual((project / 'project.yml').read_text(), 'preserve')

    def test_config_rejects_overlapping_build_paths_before_build(self):
        for location in ('.', '..', 'src', 'src/java', 'src/java/generated-build', '.libs'):
            with self.subTest(location=location), tempfile.TemporaryDirectory() as temp:
                project = Path(temp)
                (project / 'AndroidManifest.xml').write_text('<manifest package="com.example.safe"/>')
                (project / 'project.yml').write_text(json.dumps({'android': {}, 'build-path': location}))
                with patch.object(Config, '_resolve_android_jar', return_value='/fixture/android.jar'):
                    with self.assertRaisesRegex(ValueError, 'build-path'):
                        Config(temp)

    def test_normal_and_external_dedicated_build_directories_can_be_cleaned(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / 'project'
            project.mkdir()
            marker = project / 'preserve'
            marker.write_text('original')
            (project / 'AndroidManifest.xml').write_text('<manifest package="com.example.safe"/>')
            for output in (project / '.build', root / 'dedicated-output'):
                output.mkdir()
                (output / 'generated').write_text('generated')
                (project / 'project.yml').write_text(json.dumps({'android': {}, 'build-path': str(output)}))
                with patch.object(Config, '_resolve_android_jar', return_value='/fixture/android.jar'):
                    cli._do_clean(Config(str(project)))
                self.assertFalse(output.exists())
                self.assertEqual(marker.read_text(), 'original')

    def test_clean_refuses_symlink_alias_of_project(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / 'project'
            project.mkdir()
            link = Path(temp) / 'output'
            link.symlink_to(project, target_is_directory=True)
            config = SimpleNamespace(project_dir=str(project), build_dir=str(link))
            with self.assertRaisesRegex(ValueError, 'build-path'):
                cli._do_clean(config)
            self.assertTrue(project.exists())


if __name__ == '__main__':
    unittest.main()
