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


class ProcessorOutputInvalidationTests(unittest.TestCase):
    def test_no_sources_removes_previous_processor_outputs(self):
        for language, names in (("java", ["gen-apt"]), ("kotlin", ["kapt", "ksp"])):
            with self.subTest(language=language), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                for name in names:
                    output = root / name
                    output.mkdir()
                    (output / "Deleted.java").write_text("obsolete")
                config = SimpleNamespace(
                    build_dir=temp, java_classes_dir=str(root / "java"),
                    kotlin_classes_dir=str(root / "kotlin"), gen_dir=str(root / "gen"),
                    view_binding=False, find_java_files=lambda base_dir=None: [],
                    find_kotlin_files=lambda: [],
                )
                getattr(compiler, "compile_" + language)(config)
                for name in names:
                    self.assertFalse((root / name / "Deleted.java").exists())

    def test_real_processor_does_not_leave_removed_generated_source(self):
        import shutil
        import subprocess
        if shutil.which("javac") is None or shutil.which("jar") is None:
            self.skipTest("real javac and jar unavailable")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            processor_source = root / "Generator.java"
            processor_source.write_text('''
import java.util.Set;
import javax.annotation.processing.*;
import javax.lang.model.SourceVersion;
import javax.lang.model.element.*;
@SupportedAnnotationTypes("*")
public class Generator extends AbstractProcessor {
    public SourceVersion getSupportedSourceVersion() { return SourceVersion.latestSupported(); }
    public boolean process(Set<? extends TypeElement> annotations, RoundEnvironment round) {
        for (Element element : round.getRootElements()) {
            if (element.getAnnotation(Deprecated.class) != null) {
                try (java.io.Writer writer = processingEnv.getFiler().createSourceFile("Generated").openWriter()) {
                    writer.write("public class Generated {}");
                } catch (java.io.IOException error) { throw new RuntimeException(error); }
            }
        }
        return false;
    }
}
''')
            classes = root / "processor-classes"
            subprocess.run(["javac", "-proc:none", "-d", str(classes), str(processor_source)], check=True)
            service = classes / "META-INF/services/javax.annotation.processing.Processor"
            service.parent.mkdir(parents=True)
            service.write_text("Generator\n")
            processor = root / "processor.jar"
            subprocess.run(["jar", "cf", str(processor), "-C", str(classes), "."], check=True)
            source = root / "Main.java"
            output = root / "classes"
            config = SimpleNamespace(
                build_dir=temp, gen_dir=str(root / "gen"), view_binding=False,
                java_classes_dir=str(output), bin_javac=shutil.which("javac"),
                annotation_processors=[str(processor)], find_lib_jars=lambda: [],
                find_java_files=lambda base_dir=None: [str(source)] if base_dir is None else [],
            )
            with patch("builder.compiler._resolve_android_jar", return_value=temp), patch(
                "builder.compiler._effective_java_version", return_value=8
            ), patch("builder.compiler._resolve_processor_jars", return_value=[str(processor)]):
                source.write_text("@Deprecated public class Main {}")
                compiler.compile_java(config)
                self.assertTrue((root / "gen-apt/Generated.java").exists())
                self.assertTrue((output / "Generated.class").exists())
                source.write_text("public class Main {}")
                compiler.compile_java(config)
                self.assertFalse((root / "gen-apt/Generated.java").exists())
                self.assertFalse((output / "Generated.class").exists())

    def test_symlinked_processor_output_preserves_external_files(self):
        for language, name in (("java", "gen-apt"), ("kotlin", "kapt"), ("kotlin", "ksp")):
            with self.subTest(output=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                build = root / "build"
                build.mkdir()
                outside = root / "outside"
                outside.mkdir()
                sentinel = outside / "Keep.java"
                sentinel.write_text("keep")
                (build / name).symlink_to(outside, target_is_directory=True)
                config = SimpleNamespace(build_dir=str(build))
                with self.assertRaises(ValueError):
                    getattr(compiler, "compile_" + language)(config)
                self.assertEqual(sentinel.read_text(), "keep")


class KotlinProcessorWiringTests(unittest.TestCase):
    def test_kapt_binary_outputs_are_on_final_compiler_classpath(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'processor.jar').write_bytes(b'jar')
            config = SimpleNamespace(
                build_dir=temp, project_dir=temp, kotlin_classes_dir=str(root / 'kotlin'),
                java_classes_dir=str(root / 'java'), find_kotlin_files=lambda: ['Main.kt'],
                find_lib_jars=lambda: [], kapt_enabled=True, ksp_enabled=False,
                annotation_processors=['processor.jar'], bin_kotlinc='kotlinc', compose=False,
            )
            with patch('builder.compiler._resolve_android_jar', return_value='android.jar'), patch(
                'builder.compiler._effective_java_version', return_value=8
            ), patch('builder.kapt.resolve_kapt_toolchain', return_value=(['compiler'], 'kapt.jar')), patch('builder.compiler.run') as run:
                compiler.compile_kotlin(config)
            args = run.call_args.args[0]
            self.assertIn(str(root / 'kapt/classes'), args[args.index('-classpath') + 1].split(os.pathsep))

    def test_kapt_receives_resolved_processor_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            processor = root / 'processors/generator.jar'
            processor.parent.mkdir()
            processor.write_bytes(b'jar')
            config = SimpleNamespace(
                build_dir=temp, project_dir=temp, kotlin_classes_dir=str(root / 'kotlin'),
                java_classes_dir=str(root / 'java'), find_kotlin_files=lambda: ['Main.kt'],
                find_lib_jars=lambda: [], kapt_enabled=True, ksp_enabled=False,
                annotation_processors=['processors/generator.jar'], bin_kotlinc='kotlinc', compose=False,
            )
            with patch('builder.compiler._resolve_android_jar', return_value='android.jar'), patch(
                'builder.compiler._effective_java_version', return_value=8
            ), patch('builder.kapt.resolve_kapt_toolchain', return_value=(['compiler'], 'kapt.jar')), patch('builder.compiler.run') as run:
                compiler.compile_kotlin(config)
            self.assertIn('plugin:org.jetbrains.kotlin.kapt3:apclasspath=' + str(processor), run.call_args_list[0].args[0])

    def test_generated_java_is_resolved_by_kotlin_and_compiled(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            processor = root / 'processor.jar'
            processor.write_bytes(b'jar')
            config = SimpleNamespace(
                build_dir=temp, project_dir=temp, kotlin_classes_dir=str(root / 'kotlin'),
                java_classes_dir=str(root / 'java'), find_kotlin_files=lambda: ['Main.kt'],
                find_lib_jars=lambda: [], kapt_enabled=True, ksp_enabled=False,
                annotation_processors=['processor.jar'], bin_kotlinc='kotlinc', bin_javac='javac', compose=False,
            )
            generated = root / 'kapt/sources/Generated.java'
            def execute(args):
                if '-Xplugin=kapt.jar' in args:
                    generated.write_text('public class Generated {}')
            with patch('builder.compiler._resolve_android_jar', return_value='android.jar'), patch(
                'builder.compiler._effective_java_version', return_value=8
            ), patch('builder.kapt.resolve_kapt_toolchain', return_value=(['compiler'], 'kapt.jar')), patch(
                'builder.compiler.run', side_effect=execute
            ) as run, patch('builder.compiler._can_use_ecj', return_value=False):
                compiler.compile_kotlin(config)
            commands = [call.args[0] for call in run.call_args_list]
            self.assertIn(str(generated), commands[1])
            self.assertEqual(commands[2][0], 'javac')
            self.assertIn(str(generated), commands[2])
            self.assertIn(config.kotlin_classes_dir, commands[2][commands[2].index('-classpath') + 1])

    def test_generated_java_rejects_external_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            build = root / 'build'
            build.mkdir()
            outside = root / 'outside'
            outside.mkdir()
            sentinel = outside / 'Keep.class'
            sentinel.write_bytes(b'keep')
            (build / 'java').symlink_to(outside, target_is_directory=True)
            processor = root / 'processor.jar'
            processor.write_bytes(b'jar')
            config = SimpleNamespace(
                build_dir=str(build), project_dir=temp, kotlin_classes_dir=str(build / 'kotlin'),
                java_classes_dir=str(build / 'java'), find_kotlin_files=lambda: ['Main.kt'],
                find_lib_jars=lambda: [], kapt_enabled=True, ksp_enabled=False,
                annotation_processors=['processor.jar'], bin_kotlinc='kotlinc', bin_javac='javac', compose=False,
            )
            def execute(args):
                if '-Xplugin=kapt.jar' in args:
                    (build / 'kapt/sources/Generated.java').write_text('public class Generated {}')
            with patch('builder.compiler._resolve_android_jar', return_value='android.jar'), patch(
                'builder.compiler._effective_java_version', return_value=8
            ), patch('builder.kapt.resolve_kapt_toolchain', return_value=(['compiler'], 'kapt.jar')), patch(
                'builder.compiler.run', side_effect=execute
            ), patch('builder.compiler._compile_java_javac') as javac:
                with self.assertRaises(ValueError):
                    compiler.compile_kotlin(config)
            javac.assert_not_called()
            self.assertEqual(sentinel.read_bytes(), b'keep')

    def test_ksp_receives_resolved_processor_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            processor = root / 'processors/generator.jar'
            processor.parent.mkdir()
            processor.write_bytes(b'jar')
            other = processor.with_name('other.jar')
            other.write_bytes(b'jar')
            config = SimpleNamespace(
                build_dir=temp, project_dir=temp, kotlin_classes_dir=str(root / 'kotlin'),
                java_classes_dir=str(root / 'java'), find_kotlin_files=lambda: ['Main.kt'],
                find_lib_jars=lambda: [], kapt_enabled=False, ksp_enabled=True,
                annotation_processors=['processors/generator.jar', 'processors/other.jar'], bin_kotlinc='kotlinc', compose=False,
            )
            with patch('builder.compiler._resolve_android_jar', return_value='android.jar'), patch(
                'builder.compiler._effective_java_version', return_value=8
            ), patch('builder.ksp.setup_ksp_toolchain', return_value=(['compiler'], 'ksp.jar')), patch('builder.compiler.run') as run:
                compiler.compile_kotlin(config)
            self.assertIn('plugin:com.google.devtools.ksp.symbol-processing:apclasspath=' + os.pathsep.join([str(processor), str(other)]), run.call_args_list[0].args[0])
