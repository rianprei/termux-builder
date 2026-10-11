import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from builder import compiler
from builder.compiler import _effective_java_version


class EffectiveJavaVersionTests(unittest.TestCase):
    def test_sdk_d8_keeps_configured_java_version_when_not_on_path(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            d8 = root / "sdk" / "build-tools" / "37.0.0" / "d8"
            d8.parent.mkdir(parents=True)
            d8.write_text("#!/bin/sh\n", encoding="utf-8")
            d8.chmod(0o755)
            empty_path = root / "empty-path"
            empty_path.mkdir()
            config = SimpleNamespace(bin_d8=str(d8), java_version=17)

            with patch.dict(os.environ, {"PATH": str(empty_path)}):
                self.assertEqual(_effective_java_version(config), 17)

    def test_configured_javac_outside_path_is_used_with_annotation_processors(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            javac = root / "jdk" / "bin" / "javac"
            javac.parent.mkdir(parents=True)
            javac.write_text("#!/bin/sh\n", encoding="utf-8")
            javac.chmod(0o755)
            empty_path = root / "empty-path"
            empty_path.mkdir()
            android_jar = root / "android.jar"
            android_jar.write_bytes(b"jar")
            config = SimpleNamespace(
                bin_javac=str(javac),
                annotation_processors=["processor.jar"],
                find_java_files=lambda base_dir=None: ["src/Main.java"] if base_dir is None else [],
                find_lib_jars=lambda: [],
                gen_dir=str(root / "gen"),
                view_binding=False,
                java_classes_dir=str(root / "classes"),
                android_jar=str(android_jar),
                build_dir=str(root / "build"),
            )

            with patch.dict(os.environ, {"PATH": str(empty_path)}):
                with patch("builder.compiler._resolve_android_jar", return_value=str(android_jar)):
                    with patch("builder.compiler._effective_java_version", return_value=17):
                        with patch("builder.compiler._can_use_ecj", return_value=True):
                            with patch("builder.compiler._resolve_processor_jars", return_value=["processor.jar"]):
                                with patch("builder.compiler._compile_java_javac") as javac_compile:
                                    with patch("builder.compiler._compile_java_ecj") as ecj_compile:
                                        compiler.compile_java(config)

            javac_compile.assert_called_once()
            ecj_compile.assert_not_called()
