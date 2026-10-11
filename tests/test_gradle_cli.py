import io
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import uuid
import zipfile
from contextlib import redirect_stdout
from unittest.mock import patch

from builder import cli
from builder import gradle


class GradleCommandTests(unittest.TestCase):
    def _report_build(self, temp, report_value, failed=False):
        args = SimpleNamespace(project=temp, module=':app', variant='debug', gradle=str(Path(temp) / 'gradle'),
            offline=True, aab=False, aapt2=None, apksigner=None, bundletool_jar=None)
        Path(args.gradle).write_text('#!/bin/sh\n')
        def execute(command, project, capture=True):
            if '--version' in command:
                return 'Gradle 9.7.1\n'
            self.assertIn('--no-configuration-cache', command)
            import json
            report = next(arg.removeprefix('-Dtb.report=') for arg in command if arg.startswith('-Dtb.report='))
            nonce = next(arg.removeprefix('-Dtb.nonce=') for arg in command if arg.startswith('-Dtb.nonce='))
            value = report_value(nonce) if callable(report_value) else report_value
            Path(report).write_text(json.dumps(value))
            if failed:
                raise RuntimeError('fixture failure')
            return ''
        with patch.object(gradle, '_tool', side_effect=lambda value, name: args.gradle if name == 'gradle' else name), \
             patch.object(gradle, '_execute', side_effect=execute):
            return gradle.build(args)

    def test_malformed_reports_fail_with_diagnostics(self):
        for value, failed in (([], True), ([], False), (lambda nonce: dict(nonce=nonce, module=':app', variant='debug',
                format='apk', gradle='9.7.1', agp='9.4.1', applicationId=42, artifacts=[]), False)):
            with self.subTest(value=value, failed=failed), tempfile.TemporaryDirectory() as temp:
                with self.assertRaises(RuntimeError):
                    self._report_build(temp, value, failed)

    def test_export_disables_incompatible_configuration_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError, 'no artifacts'):
                self._report_build(temp, lambda nonce: dict(nonce=nonce, module=':app', variant='debug',
                    format='apk', applicationId='com.example.app', artifacts=[]))

    def test_artifact_changes_during_verification_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'artifact.apk'
            path.write_bytes(b'original fixture')
            def report(nonce):
                return dict(nonce=nonce, module=':app', variant='debug', format='apk', gradle='9.7.1', agp='9.4.1',
                    applicationId='com.example.app', artifacts=[dict(path=str(path))])
            def verify(snapshot, *unused):
                self.assertNotEqual(snapshot, path)
                self.assertEqual(snapshot.read_bytes(), b'original fixture')
                path.write_bytes(b'changed fixture')
            with patch.object(gradle, '_verify_apk', side_effect=verify):
                with self.assertRaisesRegex(RuntimeError, 'changed'):
                    self._report_build(temp, report)

    def test_gradle_command_routes_without_loading_direct_configuration(self):
        arguments = ['termux-builder', 'gradle-build', '/fixture', '--gradle', '/tools/gradle',
            '--module', ':app', '--variant', 'demoDebug', '--aab', '--offline']
        with patch.object(sys, 'argv', arguments), patch('builder.config.Config') as config, \
             patch('builder.gradle.build') as build:
            cli.main()
        config.assert_not_called()
        request = build.call_args.args[0]
        self.assertEqual(request.project, '/fixture')
        self.assertEqual(request.module, ':app')
        self.assertEqual(request.variant, 'demoDebug')
        self.assertTrue(request.aab)
        self.assertTrue(request.offline)

    def test_help_describes_installed_launcher_and_artifact_verification(self):
        output = io.StringIO()
        with patch.object(sys, 'argv', ['termux-builder', 'gradle-build', '--help']), \
             redirect_stdout(output), self.assertRaises(SystemExit) as exited:
            cli.main()
        self.assertEqual(exited.exception.code, 0)
        self.assertIn('--gradle', output.getvalue())
        self.assertIn('--variant', output.getvalue())
        self.assertIn('--offline', output.getvalue())

    def test_invalid_module_and_variant_are_rejected_before_tools(self):
        for module, variant in (('app', 'debug'), (':app', 'debug;echo')):
            with self.subTest(module=module, variant=variant), patch.object(gradle, '_tool') as tool:
                with self.assertRaises(ValueError):
                    gradle.build(SimpleNamespace(module=module, variant=variant))
                tool.assert_not_called()

    def test_offline_wrapper_is_rejected_without_bootstrap(self):
        with tempfile.TemporaryDirectory() as temp:
            wrapper = Path(temp) / 'gradlew'
            wrapper.write_text('#!/bin/sh\n# org.gradle.wrapper.GradleWrapperMain\n')
            wrapper.chmod(0o755)
            args = SimpleNamespace(project=temp, module=':app', variant='debug', gradle=str(wrapper), offline=True)
            with patch.object(gradle, '_execute') as execute, self.assertRaisesRegex(ValueError, 'Wrapper'):
                gradle.build(args)
            execute.assert_not_called()

    def test_unreadable_launcher_has_actionable_diagnostic(self):
        with tempfile.TemporaryDirectory() as temp:
            args = SimpleNamespace(project=temp, module=':app', variant='debug', gradle='gradle')
            with patch.object(gradle, '_tool', return_value='/fixture/gradle'), \
                 patch.object(Path, 'read_text', side_effect=PermissionError('fixture')):
                with self.assertRaisesRegex(RuntimeError, 'launcher.*read'):
                    gradle.build(args)

    def test_failed_process_output_does_not_expose_environment_secret(self):
        secret = uuid.uuid4().hex
        code = "import os,sys; print(os.environ['TB_FIXTURE_PASSWORD']); sys.exit(7)"
        with patch.dict(os.environ, {'TB_FIXTURE_PASSWORD': secret}):
            with self.assertRaisesRegex(RuntimeError, 'exit 7') as failure:
                gradle._execute([sys.executable, '-c', code], None)
        self.assertNotIn(secret, str(failure.exception))

    def test_apk_rejects_unsafe_empty_and_duplicate_entries_before_tools(self):
        for bad in ('../escape', 'AndroidManifest.xml', 'empty'):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / 'artifact.apk'
                with zipfile.ZipFile(path, 'w') as archive:
                    archive.writestr('AndroidManifest.xml', b'' if bad == 'empty' else b'fixture')
                    if bad != 'empty':
                        import warnings
                        with warnings.catch_warnings():
                            warnings.simplefilter('ignore', UserWarning)
                            archive.writestr(bad, b'fixture')
                with patch.object(gradle, '_execute') as execute, self.assertRaises(RuntimeError):
                    gradle._verify_apk(path, 'apksigner', 'aapt2', 'com.example.app')
                execute.assert_not_called()

    def test_apk_rejects_crc_corruption_before_tools(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'artifact.apk'
            with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_STORED) as archive:
                archive.writestr('AndroidManifest.xml', b'fixture')
                archive.writestr('assets/file', b'original CRC payload')
            path.write_bytes(path.read_bytes().replace(b'original CRC payload', b'changed! CRC payload'))
            with patch.object(gradle, '_execute') as execute, self.assertRaisesRegex(RuntimeError, 'CRC'):
                gradle._verify_apk(path, 'apksigner', 'aapt2', 'com.example.app')
            execute.assert_not_called()
