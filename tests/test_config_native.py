import json
import os
import tempfile
import unittest
from unittest.mock import patch

from builder.config import Config


class NativeLibraryDiscoveryTests(unittest.TestCase):
    def test_sdk_d8_is_selected_before_dx_fallback_when_not_on_path(self):
        with tempfile.TemporaryDirectory() as tempdir:
            sdk_dir = os.path.join(tempdir, "sdk")
            d8 = os.path.join(sdk_dir, "build-tools", "37.0.0", "d8")
            os.makedirs(os.path.dirname(d8))
            with open(d8, "w", encoding="utf-8") as tool:
                tool.write("#!/bin/sh\n")
            os.chmod(d8, 0o755)
            with open(os.path.join(tempdir, "AndroidManifest.xml"), "w", encoding="utf-8") as manifest:
                manifest.write('<manifest package="com.example.app"/>')
            with open(os.path.join(tempdir, "project.yml"), "w", encoding="utf-8") as project:
                json.dump({"name": "app", "android": {"sdk-path": sdk_dir}}, project)

            with patch("builder.config.find_bin", return_value=None):
                config = Config(tempdir)

            self.assertEqual(config.bin_d8, d8)

    def test_resolves_sdk_build_tool_when_it_is_not_on_path(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = object.__new__(Config)
            config.sdk_dir = os.path.join(tempdir, "sdk")
            older = os.path.join(config.sdk_dir, "build-tools", "34.0.0", "aapt2")
            newer = os.path.join(config.sdk_dir, "build-tools", "37.0.0", "aapt2")
            for path in (older, newer):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as tool:
                    tool.write("#!/bin/sh\n")
                os.chmod(path, 0o755)

            with patch("builder.config.find_bin", return_value=None):
                resolved = Config._resolve_bin(config, "aapt2", {})

            self.assertEqual(resolved, newer)

    def test_explicit_path_and_path_environment_precede_sdk_build_tools(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = os.path.join(tempdir, "sdk")
            path_dir = os.path.join(tempdir, "path")
            explicit = os.path.join(tempdir, "configured-aapt2")
            on_path = os.path.join(path_dir, "aapt2")
            in_sdk = os.path.join(root, "build-tools", "37.0.0", "aapt2")
            for path in (explicit, on_path, in_sdk):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as tool:
                    tool.write("#!/bin/sh\n")
                os.chmod(path, 0o755)

            config = object.__new__(Config)
            config.sdk_dir = root
            with patch.dict(os.environ, {"PATH": path_dir}):
                self.assertEqual(Config._resolve_bin(config, "aapt2", {}), on_path)
                self.assertEqual(Config._resolve_bin(config, "aapt2", {"aapt2": explicit}), explicit)

    def test_library_native_paths_follow_stable_directory_order(self):
        with tempfile.TemporaryDirectory() as tempdir:
            libs_dir = os.path.join(tempdir, ".libs")
            app_jni_dir = os.path.join(tempdir, "src", "jniLibs")
            first_library = os.path.join(libs_dir, "a-library")
            second_library = os.path.join(libs_dir, "z-library")
            paths = [
                os.path.join(app_jni_dir, "arm64-v8a", "lib-app.so"),
                os.path.join(first_library, "jni", "arm64-v8a", "lib-a.so"),
                os.path.join(second_library, "jni", "arm64-v8a", "lib-z.so"),
            ]
            for path in paths:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as native_library:
                    native_library.write(os.path.basename(path).encode())

            config = object.__new__(Config)
            config.jni_dir = app_jni_dir
            config.libs_dir = libs_dir
            config.find_lib_jars = lambda: []
            config.resolved_dependency_dirs = {second_library, first_library}

            expected = [("arm64-v8a", path) for path in paths]
            self.assertEqual(Config.find_native_libs(config), expected)
            self.assertEqual(Config.find_native_libs(config), expected)

    def test_incomplete_internal_maven_cache_is_not_a_local_classpath(self):
        with tempfile.TemporaryDirectory() as tempdir:
            libs_dir = os.path.join(tempdir, ".libs")
            staged_jar = os.path.join(
                libs_dir, ".termux-builder", "maven", "com", "example", ".app-1.0.stage", "app.jar"
            )
            local_jar = os.path.join(libs_dir, "local", "local.jar")
            for path in (staged_jar, local_jar):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as jar:
                    jar.write(b"jar")

            config = object.__new__(Config)
            config.libs_dir = libs_dir
            config.resolved_dependency_dirs = set()

            self.assertEqual(Config.find_lib_jars(config), [local_jar])

    def test_config_rejects_project_name_and_flavor_path_segments(self):
        with tempfile.TemporaryDirectory() as tempdir:
            project_yml = os.path.join(tempdir, "project.yml")
            with open(os.path.join(tempdir, "AndroidManifest.xml"), "w", encoding="utf-8") as manifest_file:
                manifest_file.write('<manifest package="com.example.app"/>')
            for document, flavor, message in (
                ({"name": "../../outside", "android": {}}, None, "name"),
                ({"android": {}, "flavors": {"../../outside": {}}}, "../../outside", "flavor"),
            ):
                with self.subTest(document=document):
                    with open(project_yml, "w", encoding="utf-8") as config_file:
                        json.dump(document, config_file)
                    with self.assertRaisesRegex(ValueError, message):
                        Config(tempdir, flavor=flavor)


if __name__ == "__main__":
    unittest.main()
