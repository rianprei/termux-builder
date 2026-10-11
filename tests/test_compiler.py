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
                build_dir=str(root),
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


class CompilerOutputInvalidationTests(unittest.TestCase):
    def test_removing_all_sources_removes_previous_classes(self):
        for language in ("java", "kotlin"):
            with self.subTest(language=language), tempfile.TemporaryDirectory() as tempdir:
                output = Path(tempdir) / "classes"
                output.mkdir()
                (output / "Deleted.class").write_bytes(b"obsolete")
                config = SimpleNamespace(
                    build_dir=tempdir, java_classes_dir=str(output), kotlin_classes_dir=str(output),
                    find_java_files=lambda base_dir=None: [],
                    find_kotlin_files=lambda: [], gen_dir=tempdir, view_binding=False,
                )
                getattr(compiler, "compile_" + language)(config)
                self.assertFalse((output / "Deleted.class").exists())

    def test_real_javac_rebuild_removes_deleted_inner_class(self):
        import shutil
        if shutil.which("javac") is None:
            self.skipTest("real javac unavailable")
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            source = root / "Main.java"
            output = root / "classes"
            config = SimpleNamespace(
                find_java_files=lambda base_dir=None: [str(source)] if base_dir is None else [],
                gen_dir=str(root / "gen"), view_binding=False,
                build_dir=tempdir, java_classes_dir=str(output), find_lib_jars=lambda: [],
                bin_javac=shutil.which("javac"), annotation_processors=[],
            )
            with patch("builder.compiler._resolve_android_jar", return_value=tempdir), patch(
                "builder.compiler._effective_java_version", return_value=8
            ):
                source.write_text("public class Main { static class Deleted {} }", encoding="utf-8")
                compiler.compile_java(config)
                self.assertTrue((output / "Main$Deleted.class").exists())
                source.write_text("public class Main {}", encoding="utf-8")
                compiler.compile_java(config)
                self.assertTrue((output / "Main.class").exists())
                self.assertFalse((output / "Main$Deleted.class").exists())


    def test_symlinked_ancestor_does_not_delete_external_classes(self):
        for language in ("java", "kotlin"):
            with self.subTest(language=language), tempfile.TemporaryDirectory() as tempdir:
                root = Path(tempdir)
                build = root / "build"
                build.mkdir()
                outside = root / "outside"
                output = outside / language
                output.mkdir(parents=True)
                sentinel = output / "Keep.class"
                sentinel.write_bytes(b"keep")
                (build / "classes").symlink_to(outside, target_is_directory=True)
                config = SimpleNamespace(build_dir=str(build))
                setattr(config, language + "_classes_dir", str(build / "classes" / language))
                with self.assertRaises(ValueError):
                    getattr(compiler, "compile_" + language)(config)
                self.assertEqual(sentinel.read_bytes(), b"keep")
