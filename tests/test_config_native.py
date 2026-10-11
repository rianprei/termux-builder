import json
import os
import tempfile
import unittest

from builder.config import Config


class NativeLibraryDiscoveryTests(unittest.TestCase):
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
