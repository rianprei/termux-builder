import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from builder.doctor import check


class DoctorSdkToolTests(unittest.TestCase):
    def test_aab_diagnosis_requires_java_jarsigner_and_aapt2(self):
        for missing in ('java', 'jarsigner', 'aapt2', None):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tempdir:
                sdk = Path(tempdir) / 'sdk'
                jar = sdk / 'platforms/android-36/android.jar'
                jar.parent.mkdir(parents=True)
                jar.write_bytes(b'fixture')
                output = io.StringIO()
                def executable(name):
                    return None if name == missing else '/fixture/' + name
                with patch.dict(os.environ, {'ANDROID_SDK': str(sdk)}), \
                     patch('builder.doctor.shutil.which', side_effect=executable), \
                     patch('builder.doctor._resolve_sdk_bin', side_effect=lambda sdk, name, bins: executable(name)), \
                     contextlib.redirect_stdout(output):
                    self.assertEqual(check(), 0)
                    self.assertEqual(check(aab=True), 0 if missing is None else 1)
                self.assertIn('AAB requirements:', output.getvalue())
                if missing:
                    self.assertIn(missing + ' not found', output.getvalue())

    def test_sdk_directory_without_android_jar_is_not_healthy(self):
        with tempfile.TemporaryDirectory() as tempdir:
            sdk = Path(tempdir) / 'sdk'
            (sdk / 'platforms/android-36').mkdir(parents=True)
            output = io.StringIO()
            with patch.dict(os.environ, {'ANDROID_SDK': str(sdk)}), \
                 patch('builder.doctor.shutil.which', return_value='/fixture/tool'), \
                 patch('builder.doctor._resolve_sdk_bin', return_value='/fixture/tool'), \
                 patch('builder.doctor._SYSTEM_ANDROID_JAR', str(Path(tempdir) / 'absent.jar')), \
                 contextlib.redirect_stdout(output):
                self.assertGreater(check(), 0)
            self.assertIn('No android.jar', output.getvalue())
            self.assertNotIn('All checks passed', output.getvalue())

    def test_reports_sdk_build_tools_that_are_not_on_path(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            sdk = root / "sdk"
            empty_path = root / "empty-path"
            empty_path.mkdir()
            tools = {}
            for version in ("36.0.0", "37.0.0"):
                for name in ("d8", "aapt2", "apksigner"):
                    tool = sdk / "build-tools" / version / name
                    tool.parent.mkdir(parents=True, exist_ok=True)
                    tool.write_text("#!/bin/sh\n", encoding="utf-8")
                    tool.chmod(0o755)
                    if version == "37.0.0":
                        tools[name] = str(tool)

            output = io.StringIO()
            with patch.dict(os.environ, {"ANDROID_SDK": str(sdk), "PATH": str(empty_path)}):
                with patch("builder.config.find_bin", return_value=None):
                    with contextlib.redirect_stdout(output):
                        check()

            report = output.getvalue()
            for name, path in tools.items():
                self.assertIn(f"{name}: {path}", report)
            self.assertNotIn("No dexer", report)

    def test_reports_sdk_dx_when_d8_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            sdk = root / "sdk"
            dx = sdk / "build-tools" / "37.0.0" / "dx"
            dx.parent.mkdir(parents=True)
            dx.write_text("#!/bin/sh\n", encoding="utf-8")
            dx.chmod(0o755)
            empty_path = root / "empty-path"
            empty_path.mkdir()

            output = io.StringIO()
            with patch.dict(os.environ, {"ANDROID_SDK": str(sdk), "PATH": str(empty_path)}):
                with patch("builder.config.find_bin", return_value=None):
                    with contextlib.redirect_stdout(output):
                        check()

            self.assertIn(f"dx (fallback): {dx}", output.getvalue())
            self.assertNotIn("No dexer", output.getvalue())
