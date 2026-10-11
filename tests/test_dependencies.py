import hashlib
import json
import os
import stat
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

from builder import deps, resources
from builder.config import Config


def _pom_response(text):
    response = Mock(status_code=200)
    response.iter_content.return_value = (text.encode("utf-8"),)
    return response


class DependencySafetyTests(unittest.TestCase):
    def test_resolve_keeps_same_artifact_version_from_distinct_groups_separate(self):
        namespace = "http://maven.apache.org/POM/4.0.0"
        pom_by_url = {}

        def find_artifact(group_path, artifact, version, extension):
            url = (
                f"https://repo1.maven.org/maven2/{group_path}/{artifact}/{version}/"
                f"{artifact}-{version}.{extension}"
            )
            if extension == "pom":
                child = "one-only" if group_path == "org/one" else "two-only"
                dependency = (
                    '<dependency><groupId>org.transitive</groupId>'
                    f'<artifactId>{child}</artifactId><version>1.0</version></dependency>'
                    if artifact == "shared"
                    else ""
                )
                pom_by_url[url] = (
                    f'<project xmlns="{namespace}"><dependencies>{dependency}</dependencies></project>'
                )
            return url

        def get_pom(url, **kwargs):
            return _pom_response(pom_by_url[url])

        def write_artifact(url, destination):
            with open(destination, "wb") as artifact_file:
                artifact_file.write(url.encode())

        with tempfile.TemporaryDirectory() as tempdir:
            config = SimpleNamespace(
                dependencies=["org.one:shared:1.0", "org.two:shared:1.0"],
                cache_dir=os.path.join(tempdir, "cache"),
                libs_dir=os.path.join(tempdir, "libs"),
            )
            with patch.object(deps, "_find_artifact", side_effect=find_artifact), patch.object(
                deps.requests, "get", side_effect=get_pom
            ), patch.object(deps, "_download", side_effect=write_artifact), patch.object(
                deps, "_verify_checksum", return_value=None
            ):
                deps.resolve(config)

            first_dir = os.path.join(
                config.libs_dir, ".termux-builder", "maven", "org", "one", "shared-1.0"
            )
            second_dir = os.path.join(
                config.libs_dir, ".termux-builder", "maven", "org", "two", "shared-1.0"
            )
            first_jar = os.path.join(first_dir, "shared-1.0.jar")
            second_jar = os.path.join(second_dir, "shared-1.0.jar")
            self.assertTrue(os.path.isfile(first_jar))
            self.assertTrue(os.path.isfile(second_jar))
            with open(first_jar, "rb") as first, open(second_jar, "rb") as second:
                self.assertNotEqual(first.read(), second.read())
            with open(os.path.join(first_dir, ".termux-builder-coordinate")) as marker:
                self.assertEqual(marker.read(), "org.one:shared:1.0")
            with open(os.path.join(second_dir, ".termux-builder-coordinate")) as marker:
                self.assertEqual(marker.read(), "org.two:shared:1.0")
            with open(os.path.join(first_dir, ".termux-builder-artifact.json")) as metadata_file:
                metadata = json.load(metadata_file)
            self.assertEqual(metadata["coordinate"], "org.one:shared:1.0")
            self.assertEqual(
                metadata["source_url"],
                "https://repo1.maven.org/maven2/org/one/shared/1.0/shared-1.0.jar",
            )
            self.assertEqual(metadata["artifact_sha256"], hashlib.sha256(
                metadata["source_url"].encode()
            ).hexdigest())
            self.assertCountEqual(
                Config.find_lib_jars(config), [
                    first_jar,
                    second_jar,
                    os.path.join(
                        config.libs_dir, ".termux-builder", "maven", "org", "transitive",
                        "one-only-1.0", "one-only-1.0.jar"
                    ),
                    os.path.join(
                        config.libs_dir, ".termux-builder", "maven", "org", "transitive",
                        "two-only-1.0", "two-only-1.0.jar"
                    ),
                ],
            )

    def test_resolve_rebuilds_modified_library_and_redownloads_corrupt_artifact_cache(self):
        namespace = "http://maven.apache.org/POM/4.0.0"
        artifact_url = (
            "https://repo1.maven.org/maven2/org/example/sample/1.0/sample-1.0.jar"
        )
        pom_url = artifact_url[:-3] + "pom"
        poms = {
            pom_url: f'<project xmlns="{namespace}"/>',
        }

        def find_artifact(group_path, artifact, version, extension):
            return (
                f"https://repo1.maven.org/maven2/{group_path}/{artifact}/{version}/"
                f"{artifact}-{version}.{extension}"
            )

        def get_pom(url, **kwargs):
            return _pom_response(poms[url])

        downloads = []

        def write_artifact(url, destination):
            downloads.append(url)
            with open(destination, "wb") as artifact_file:
                artifact_file.write(b"valid jar")

        with tempfile.TemporaryDirectory() as tempdir:
            config = SimpleNamespace(
                dependencies=["org.example:sample:1.0"],
                cache_dir=os.path.join(tempdir, "cache"),
                libs_dir=os.path.join(tempdir, "libs"),
            )
            with patch.object(deps, "_find_artifact", side_effect=find_artifact), patch.object(
                deps.requests, "get", side_effect=get_pom
            ), patch.object(deps, "_download", side_effect=write_artifact), patch.object(
                deps, "_verify_checksum", return_value=None
            ):
                deps.resolve(config)
                lib_dir = os.path.join(
                    config.libs_dir, ".termux-builder", "maven", "org", "example",
                    "sample-1.0"
                )
                jar_path = os.path.join(lib_dir, "sample-1.0.jar")
                cache_path = os.path.join(
                    config.cache_dir, "deps", "org", "example", "sample-1.0.jar"
                )
                with open(jar_path, "wb") as jar_file:
                    jar_file.write(b"modified library")
                with open(cache_path, "wb") as artifact_file:
                    artifact_file.write(b"corrupt cached artifact")
                deps.resolve(config)

            with open(jar_path, "rb") as jar_file:
                self.assertEqual(jar_file.read(), b"valid jar")
            self.assertEqual(downloads, [artifact_url, artifact_url])

    def test_resolve_refuses_symlink_in_group_cache_path(self):
        with tempfile.TemporaryDirectory() as tempdir:
            libs_dir = os.path.join(tempdir, "libs")
            outside = os.path.join(tempdir, "outside")
            os.makedirs(os.path.join(libs_dir, ".termux-builder", "maven"))
            os.makedirs(outside)
            os.symlink(outside, os.path.join(libs_dir, ".termux-builder", "maven", "org"))
            config = SimpleNamespace(
                dependencies=["org.example:sample:1.0"],
                cache_dir=os.path.join(tempdir, "cache"),
                libs_dir=libs_dir,
            )

            with self.assertRaisesRegex(RuntimeError, "symlink dependency cache directory"):
                deps.resolve(config)

    def test_resolve_downloads_declared_aar_type_and_extracts_resources(self):
        namespace = "http://maven.apache.org/POM/4.0.0"
        root_url = "https://repo1.maven.org/maven2/org/example/app/1.0/app-1.0.pom"
        library_url = "https://repo1.maven.org/maven2/org/example/library/1.0/library-1.0.pom"
        poms = {
            root_url: f'''<project xmlns="{namespace}"><dependencies>
              <dependency><groupId>org.example</groupId><artifactId>library</artifactId>
                <version>1.0</version><type>aar</type></dependency>
            </dependencies></project>''',
            library_url: f'<project xmlns="{namespace}"><packaging>jar</packaging></project>',
        }
        downloaded = []

        def find_artifact(group_path, artifact, version, extension):
            url = (
                f"https://repo1.maven.org/maven2/{group_path}/{artifact}/{version}/"
                f"{artifact}-{version}.{extension}"
            )
            if extension == "pom":
                self.assertIn(url, poms)
            return url

        def get_pom(url, **kwargs):
            return _pom_response(poms[url])

        def write_artifact(url, destination):
            downloaded.append(url)
            if url.endswith(".aar"):
                with zipfile.ZipFile(destination, "w") as archive:
                    archive.writestr("AndroidManifest.xml", "<manifest package='org.example.library'/>")
                    archive.writestr("classes.jar", b"inner jar")
                    archive.writestr("res/values/strings.xml", "<resources/>")
            else:
                with open(destination, "wb") as artifact_file:
                    artifact_file.write(b"jar")

        with tempfile.TemporaryDirectory() as tempdir:
            config = SimpleNamespace(
                dependencies=["org.example:app:1.0"],
                cache_dir=os.path.join(tempdir, "cache"),
                libs_dir=os.path.join(tempdir, "libs"),
            )
            with patch.object(deps, "_find_artifact", side_effect=find_artifact), patch.object(
                deps.requests, "get", side_effect=get_pom
            ), patch.object(deps, "_download", side_effect=write_artifact), patch.object(
                deps, "_verify_checksum", return_value=None
            ):
                deps.resolve(config)

            library_dir = os.path.join(
                config.libs_dir, ".termux-builder", "maven", "org", "example",
                "library-1.0-aar"
            )
            self.assertIn(
                "https://repo1.maven.org/maven2/org/example/library/1.0/library-1.0.aar",
                downloaded,
            )
            self.assertTrue(os.path.isfile(os.path.join(library_dir, "library-1.0-aar.jar")))
            self.assertTrue(os.path.isfile(os.path.join(library_dir, "res/values/strings.xml")))
            with open(os.path.join(library_dir, ".termux-builder-artifact.json")) as metadata_file:
                self.assertEqual(json.load(metadata_file)["packaging"], "aar")

    def test_resource_only_aar_is_cached_and_exposes_its_resources(self):
        namespace = "http://maven.apache.org/POM/4.0.0"
        pom_url = "https://repo1.maven.org/maven2/org/example/resources/1.0/resources-1.0.pom"
        pom = f'<project xmlns="{namespace}"><packaging>aar</packaging></project>'
        artifact_url = pom_url[:-4] + "aar"

        def write_aar(url, destination):
            with zipfile.ZipFile(destination, "w") as archive:
                archive.writestr("AndroidManifest.xml", "<manifest package='org.example.resources'/>")
                archive.writestr("res/values/strings.xml", "<resources/>")
                archive.writestr("assets/aar.txt", "AAR asset")
                archive.writestr("jni/arm64-v8a/libresources.so", b"native library")

        with tempfile.TemporaryDirectory() as tempdir:
            config = object.__new__(Config)
            config.dependencies = ["org.example:resources:1.0"]
            config.cache_dir = os.path.join(tempdir, "cache")
            config.libs_dir = os.path.join(tempdir, "libs")
            config.jni_dir = os.path.join(tempdir, "src", "jniLibs")
            config.assets_dir = os.path.join(tempdir, "src", "assets")
            config.res_dir = os.path.join(tempdir, "app-res")
            config.flavor_res_dir = None
            config.compiled_res_dir = os.path.join(tempdir, "compiled-res")
            with patch.object(deps, "_find_artifact", return_value=pom_url) as find_artifact, patch.object(
                deps.requests, "get", return_value=_pom_response(pom)
            ), patch.object(deps, "_download", side_effect=write_aar), patch.object(
                deps, "_verify_checksum", return_value=None
            ):
                deps.resolve(config)

            with patch.object(
                deps, "_find_artifact", side_effect=AssertionError("cached AAR must not resolve again")
            ), patch.object(
                deps.requests, "get", side_effect=AssertionError("cached POM must not be fetched again")
            ):
                deps.resolve(config)

            dependency_dir = next(iter(config.resolved_dependency_dirs))
            self.assertFalse(config.find_lib_jars())
            self.assertEqual(
                config.find_lib_resource_dirs(), [os.path.join(dependency_dir, "res")]
            )
            self.assertEqual(
                config.find_lib_asset_dirs(), [os.path.join(dependency_dir, "assets")]
            )
            native_lib = os.path.join(dependency_dir, "jni", "arm64-v8a", "libresources.so")
            self.assertEqual(config.find_native_libs(), [("arm64-v8a", native_lib)])
            self.assertIn(
                os.path.join(dependency_dir, "res"),
                [source for source, _ in resources._aapt2_resource_jobs(config)],
            )

            config.bin_dir = os.path.join(tempdir, "bin")
            config.dex_dir = os.path.join(tempdir, "dex")
            os.makedirs(config.bin_dir)
            os.makedirs(config.dex_dir)
            with open(os.path.join(config.dex_dir, "classes.dex"), "wb") as dex:
                dex.write(b"dex")
            resource_apk = os.path.join(config.bin_dir, "gen.apk.res")
            with zipfile.ZipFile(resource_apk, "w") as apk:
                apk.writestr("assets/aar.txt", "AAR asset")
            from builder import aab, packager

            unsigned_apk = packager.package(config)
            with zipfile.ZipFile(unsigned_apk) as apk:
                self.assertEqual(apk.read("lib/arm64-v8a/libresources.so"), b"native library")
                self.assertEqual(apk.read("assets/aar.txt"), b"AAR asset")

            proto_apk = os.path.join(tempdir, "proto.apk")
            with zipfile.ZipFile(proto_apk, "w") as proto:
                proto.writestr("AndroidManifest.xml", "manifest")
                proto.writestr("resources.pb", "resources")
                proto.writestr("assets/aar.txt", "AAR asset")
            base_dir = os.path.join(tempdir, "bundle", "base")
            aab._prepare_base_module(config, base_dir, proto_apk)
            with open(os.path.join(base_dir, "lib", "arm64-v8a", "libresources.so"), "rb") as native:
                self.assertEqual(native.read(), b"native library")
            with open(os.path.join(base_dir, "assets", "aar.txt")) as asset:
                self.assertEqual(asset.read(), "AAR asset")
            self.assertEqual(find_artifact.call_count, 2)

    def test_dependency_asset_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as tempdir:
            libs_dir = os.path.join(tempdir, "libs")
            library_dir = os.path.join(libs_dir, "org", "assets-1.0")
            outside_assets = os.path.join(tempdir, "outside-assets")
            os.makedirs(library_dir)
            os.makedirs(outside_assets)
            os.symlink(outside_assets, os.path.join(library_dir, "assets"))
            config = object.__new__(Config)
            config.libs_dir = libs_dir
            config.resolved_dependency_dirs = {library_dir}
            config.find_lib_jars = lambda: []

            with self.assertRaisesRegex(RuntimeError, "asset directory must not be a symlink"):
                config.find_lib_asset_dirs()

    def test_conflicting_native_library_names_fail_with_both_sources(self):
        with tempfile.TemporaryDirectory() as tempdir:
            libs_dir = os.path.join(tempdir, "libs")
            library_dir = os.path.join(libs_dir, "org", "native-1.0")
            local_jni = os.path.join(tempdir, "src", "jniLibs", "arm64-v8a")
            aar_jni = os.path.join(library_dir, "jni", "arm64-v8a")
            os.makedirs(local_jni)
            os.makedirs(aar_jni)
            local_lib = os.path.join(local_jni, "libsame.so")
            aar_lib = os.path.join(aar_jni, "libsame.so")
            with open(local_lib, "wb") as native:
                native.write(b"local")
            with open(aar_lib, "wb") as native:
                native.write(b"dependency")
            config = object.__new__(Config)
            config.libs_dir = libs_dir
            config.jni_dir = os.path.join(tempdir, "src", "jniLibs")
            config.resolved_dependency_dirs = {library_dir}
            config.find_lib_jars = lambda: []

            with self.assertRaisesRegex(RuntimeError, "Conflicting native library arm64-v8a/libsame.so"):
                config.find_native_libs()

    def test_classpath_excludes_stale_cached_maven_versions_and_keeps_local_jars(self):
        with tempfile.TemporaryDirectory() as tempdir:
            libs_dir = os.path.join(tempdir, ".libs")
            cache_dir = os.path.join(tempdir, ".cache")
            selected_dir = os.path.join(
                libs_dir, ".termux-builder", "maven", "com", "example", "sample-2.0"
            )
            stale_dir = os.path.join(
                libs_dir, ".termux-builder", "maven", "com", "example", "sample-1.0"
            )
            local_dir = os.path.join(libs_dir, "local")
            local_collision_dir = os.path.join(libs_dir, "sample-1.0")
            for directory in (selected_dir, stale_dir, local_dir, local_collision_dir):
                os.makedirs(directory)
            for directory, coordinate in (
                (selected_dir, "com.example:sample:2.0"),
                (stale_dir, "com.example:sample:1.0"),
            ):
                with open(os.path.join(directory, ".termux-builder-coordinate"), "w") as marker:
                    marker.write(coordinate)
            os.makedirs(os.path.join(cache_dir, "deps"))
            paths = {
                "selected": os.path.join(selected_dir, "sample-2.0.jar"),
                "stale": os.path.join(stale_dir, "sample-1.0.jar"),
                "local_nested": os.path.join(local_dir, "local.jar"),
                "local_collision": os.path.join(local_collision_dir, "sample-1.0.jar"),
                "local_root": os.path.join(libs_dir, "manual.jar"),
            }
            for path in paths.values():
                with open(path, "wb") as jar:
                    jar.write(b"jar")
            for name in ("sample-1.0.jar", "sample-2.0.aar"):
                open(os.path.join(cache_dir, "deps", name), "wb").close()
            config = SimpleNamespace(
                libs_dir=libs_dir,
                cache_dir=cache_dir,
                resolved_dependency_dirs={selected_dir},
            )

            actual = Config.find_lib_jars(config)

            self.assertCountEqual(actual, [
                paths["selected"], paths["local_nested"],
                paths["local_collision"], paths["local_root"],
            ])

    def test_classpath_excludes_legacy_maven_cache_without_filtering_local_collision(self):
        with tempfile.TemporaryDirectory() as tempdir:
            libs_dir = os.path.join(tempdir, ".libs")
            cache_dir = os.path.join(tempdir, ".cache")
            legacy_dir = os.path.join(libs_dir, "sample-1.0")
            local_dir = os.path.join(libs_dir, "manual-1.0")
            os.makedirs(legacy_dir)
            os.makedirs(local_dir)
            os.makedirs(os.path.join(cache_dir, "deps"))
            legacy_jar = os.path.join(legacy_dir, "sample-1.0.jar")
            cached_artifact = os.path.join(cache_dir, "deps", "sample-1.0.jar")
            local_jar = os.path.join(local_dir, "manual-1.0.jar")
            for path, content in (
                (legacy_jar, b"legacy Maven artifact"),
                (cached_artifact, b"legacy Maven artifact"),
                (local_jar, b"local library"),
            ):
                with open(path, "wb") as artifact:
                    artifact.write(content)
            config = SimpleNamespace(
                libs_dir=libs_dir,
                cache_dir=cache_dir,
                resolved_dependency_dirs=set(),
            )

            actual = Config.find_lib_jars(config)

            self.assertEqual(actual, [local_jar])

    def test_extract_aar_rejects_declared_expansion_limit_before_writing(self):
        with tempfile.TemporaryDirectory() as tempdir:
            aar_path = os.path.join(tempdir, "oversized.aar")
            with open(aar_path, "wb") as artifact:
                artifact.write(b"not read while archive metadata is mocked")
            out_dir = os.path.join(tempdir, "extracted")
            member = SimpleNamespace(
                filename="res/raw/payload.bin",
                file_size=deps.MAX_AAR_UNCOMPRESSED_BYTES + 1,
                external_attr=0,
                is_dir=lambda: False,
            )
            archive = Mock()
            archive.__enter__ = Mock(return_value=archive)
            archive.__exit__ = Mock(return_value=False)
            archive.infolist.return_value = [member]

            with patch.object(deps.zipfile, "ZipFile", return_value=archive):
                with self.assertRaisesRegex(RuntimeError, "expanded size limit"):
                    deps._extract_aar(aar_path, out_dir)

            archive.extract.assert_not_called()
            self.assertFalse(os.path.exists(out_dir))

            member.file_size = 0
            archive.infolist.return_value = [member] * (deps.MAX_AAR_ENTRIES + 1)
            with patch.object(deps.zipfile, "ZipFile", return_value=archive):
                with self.assertRaisesRegex(RuntimeError, "entry limit"):
                    deps._extract_aar(aar_path, out_dir)
            archive.extract.assert_not_called()

    def test_resolve_without_dependencies_clears_cached_maven_selection(self):
        with tempfile.TemporaryDirectory() as tempdir:
            libs_dir = os.path.join(tempdir, ".libs")
            stale_dir = os.path.join(
                libs_dir, ".termux-builder", "maven", "com", "example", "stale-1.0"
            )
            os.makedirs(stale_dir)
            with open(os.path.join(stale_dir, ".termux-builder-coordinate"), "w") as marker:
                marker.write("com.example:stale:1.0")
            stale_jar = os.path.join(stale_dir, "stale-1.0.jar")
            local_jar = os.path.join(libs_dir, "manual.jar")
            for path in (stale_jar, local_jar):
                with open(path, "wb") as jar:
                    jar.write(b"jar")
            config = SimpleNamespace(
                dependencies=[],
                cache_dir=os.path.join(tempdir, ".cache"),
                libs_dir=libs_dir,
                resolved_dependency_dirs={stale_dir},
            )

            deps.resolve(config)

            self.assertEqual(config.resolved_dependency_dirs, set())
            self.assertEqual(Config.find_lib_jars(config), [local_jar])

    def test_aar_extraction_rejects_traversal_and_symlink_entries(self):
        for entry_type in ("traversal", "symlink"):
            with self.subTest(entry_type=entry_type), tempfile.TemporaryDirectory() as tempdir:
                aar = os.path.join(tempdir, "sample.aar")
                output = os.path.join(tempdir, "sample-1.0")
                os.mkdir(output)
                with zipfile.ZipFile(aar, "w") as archive:
                    if entry_type == "traversal":
                        archive.writestr("../outside.txt", "outside")
                    else:
                        symlink = zipfile.ZipInfo("link")
                        symlink.create_system = 3
                        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
                        archive.writestr(symlink, "../outside.txt")

                with self.assertRaisesRegex(RuntimeError, "Unsafe AAR entry"):
                    deps._extract_aar(aar, output)

                self.assertFalse(os.path.exists(os.path.join(tempdir, "outside.txt")))
                self.assertTrue(os.path.isdir(output))
                self.assertEqual(os.listdir(output), [])
                self.assertCountEqual(os.listdir(tempdir), ["sample-1.0", "sample.aar"])

    def test_aar_extraction_rejects_missing_manifest(self):
        with tempfile.TemporaryDirectory() as tempdir:
            aar = os.path.join(tempdir, "sample.aar")
            output = os.path.join(tempdir, "sample-1.0")
            with zipfile.ZipFile(aar, "w") as archive:
                archive.writestr("res/values/strings.xml", "<resources/>")

            with self.assertRaisesRegex(RuntimeError, "missing required AndroidManifest.xml"):
                deps._extract_aar(aar, output)

            self.assertFalse(os.path.exists(output))
            self.assertCountEqual(os.listdir(tempdir), ["sample.aar"])

    def test_aar_extraction_cleans_staging_directory_after_invalid_zip(self):
        with tempfile.TemporaryDirectory() as tempdir:
            aar = os.path.join(tempdir, "broken.aar")
            output = os.path.join(tempdir, "broken-1.0")
            with open(aar, "wb") as archive:
                archive.write(b"not a zip archive")

            with self.assertRaises(zipfile.BadZipFile):
                deps._extract_aar(aar, output)

            self.assertEqual(os.listdir(tempdir), ["broken.aar"])

    def test_invalid_pom_fails_instead_of_returning_no_dependencies(self):
        with self.assertRaisesRegex(ValueError, "Invalid Maven POM"):
            deps._parse_pom_deps("<project>")

    def test_pom_parser_uses_project_dependencies_not_management_or_plugin_entries(self):
        pom = '''<project xmlns="http://maven.apache.org/POM/4.0.0">
          <dependencies>
            <dependency><groupId>app</groupId><artifactId>runtime</artifactId><version>1.0</version></dependency>
          </dependencies>
          <build><plugins><plugin><dependencies>
            <dependency><groupId>plugin</groupId><artifactId>tool-only</artifactId><version>3.0</version></dependency>
          </dependencies></plugin></plugins></build>
        </project>'''

        self.assertEqual(deps._parse_pom_deps(pom), ["app:runtime:1.0"])

    def test_pom_parser_applies_local_dependency_management_version(self):
        pom = '''<project xmlns="http://maven.apache.org/POM/4.0.0">
          <dependencyManagement><dependencies>
            <dependency><groupId>app</groupId><artifactId>runtime</artifactId><version>2.0</version></dependency>
          </dependencies></dependencyManagement>
          <dependencies><dependency><groupId>app</groupId><artifactId>runtime</artifactId></dependency></dependencies>
        </project>'''

        self.assertEqual(deps._parse_pom_deps(pom), ["app:runtime:2.0"])

    def test_local_dependency_management_applies_scope_and_exclusions(self):
        pom = '''<project xmlns="http://maven.apache.org/POM/4.0.0">
          <dependencyManagement><dependencies><dependency>
            <groupId>app</groupId><artifactId>runtime</artifactId><version>2.0</version>
            <scope>runtime</scope><exclusions><exclusion><groupId>vendor</groupId>
              <artifactId>unwanted</artifactId></exclusion></exclusions>
          </dependency></dependencies></dependencyManagement>
          <dependencies><dependency><groupId>app</groupId><artifactId>runtime</artifactId></dependency></dependencies>
        </project>'''

        self.assertEqual(
            deps._parse_pom_edges(pom),
            [("app:runtime:2.0", frozenset({("vendor", "unwanted")}), None)],
        )

    def test_pom_parser_preserves_dependency_exclusions(self):
        pom = '''<project xmlns="http://maven.apache.org/POM/4.0.0">
          <dependencies><dependency><groupId>app</groupId><artifactId>runtime</artifactId>
            <version>1.0</version><exclusions><exclusion><groupId>vendor</groupId>
              <artifactId>unwanted</artifactId></exclusion></exclusions>
          </dependency></dependencies>
        </project>'''

        self.assertEqual(
            deps._parse_pom_edges(pom),
            [("app:runtime:1.0", frozenset({("vendor", "unwanted")}), None)],
        )

    def test_pom_parser_preserves_aar_dependency_type(self):
        pom = '''<project xmlns="http://maven.apache.org/POM/4.0.0">
          <dependencies><dependency><groupId>app</groupId><artifactId>runtime</artifactId>
            <version>1.0</version><type>aar</type></dependency></dependencies>
        </project>'''

        self.assertEqual(
            deps._parse_pom_edges(pom),
            [("app:runtime:1.0", frozenset(), "aar")],
        )

    def test_dependency_management_supplies_aar_type(self):
        pom = '''<project xmlns="http://maven.apache.org/POM/4.0.0">
          <dependencyManagement><dependencies><dependency>
            <groupId>app</groupId><artifactId>runtime</artifactId><version>1.0</version>
            <type>aar</type>
          </dependency></dependencies></dependencyManagement>
          <dependencies><dependency><groupId>app</groupId><artifactId>runtime</artifactId></dependency></dependencies>
        </project>'''

        self.assertEqual(
            deps._parse_pom_edges(pom),
            [("app:runtime:1.0", frozenset(), "aar")],
        )

    def test_cached_dependency_edges_preserve_exclusions(self):
        edges = [("app:runtime:1.0", frozenset({("vendor", "unwanted")}), "aar")]
        with tempfile.TemporaryDirectory() as tempdir:
            deps._save_transitive(tempdir, edges)

            self.assertEqual(deps._read_cached_edges(tempdir), edges)

    def test_cached_edge_reader_rejects_symlink_metadata(self):
        with tempfile.TemporaryDirectory() as tempdir:
            target = os.path.join(tempdir, "external.json")
            metadata = os.path.join(tempdir, ".termux-builder-transitive.json")
            with open(target, "w") as file:
                file.write("[]")
            os.symlink(target, metadata)

            with self.assertRaisesRegex(RuntimeError, "Refusing symlink dependency metadata"):
                deps._read_cached_edges(tempdir)

    def test_transitive_writer_replaces_symlink_without_touching_target(self):
        with tempfile.TemporaryDirectory() as tempdir:
            target = os.path.join(tempdir, "external.txt")
            transitive = os.path.join(tempdir, ".transitive")
            with open(target, "w") as file:
                file.write("preserve")
            os.symlink(target, transitive)

            deps._save_transitive(tempdir, [("app:runtime:1.0", frozenset())])

            with open(target) as file:
                self.assertEqual(file.read(), "preserve")
            self.assertFalse(os.path.islink(transitive))
            with open(transitive) as file:
                self.assertEqual(file.read(), "app:runtime:1.0")

    def test_pom_parser_rejects_bom_import(self):
        pom = '''<project xmlns="http://maven.apache.org/POM/4.0.0">
          <dependencyManagement><dependencies><dependency>
            <groupId>org.example</groupId><artifactId>bom</artifactId><version>1.0</version>
            <type>pom</type><scope>import</scope>
          </dependency></dependencies></dependencyManagement>
        </project>'''

        with self.assertRaisesRegex(ValueError, "BOM imports require repository resolution"):
            deps._parse_pom_deps(pom)

    def test_pom_parser_rejects_parent_inheritance(self):
        pom = '''<project xmlns="http://maven.apache.org/POM/4.0.0">
          <parent><groupId>org.example</groupId><artifactId>parent</artifactId><version>1.0</version></parent>
          <artifactId>child</artifactId>
        </project>'''

        with self.assertRaisesRegex(ValueError, "parent POM inheritance requires repository resolution"):
            deps._parse_pom_deps(pom)

    def test_pom_parser_fails_on_dependency_version_requiring_maven_interpolation(self):
        pom = '''<project xmlns="http://maven.apache.org/POM/4.0.0">
          <dependencies>
            <dependency><groupId>app</groupId><artifactId>runtime</artifactId><version>${runtime.version}</version></dependency>
          </dependencies>
        </project>'''

        with self.assertRaisesRegex(ValueError, "requires unsupported Maven version resolution"):
            deps._parse_pom_deps(pom)

    def test_pom_parser_resolves_properties_declared_in_the_same_pom(self):
        pom = '''<project xmlns="http://maven.apache.org/POM/4.0.0">
          <groupId>app</groupId><artifactId>sample</artifactId><version>1.0</version>
          <properties><hamcrestVersion>1.3</hamcrestVersion><runtime.version>${hamcrestVersion}</runtime.version></properties>
          <dependencies>
            <dependency><groupId>org.hamcrest</groupId><artifactId>hamcrest-core</artifactId><version>${runtime.version}</version></dependency>
          </dependencies>
        </project>'''

        self.assertEqual(deps._parse_pom_deps(pom), ["org.hamcrest:hamcrest-core:1.3"])

    def test_pom_parser_fails_on_unimplemented_dependency_semantics(self):
        dependency_variants = [
            ('<scope>system</scope>', "Unsupported Maven dependency scope"),
            ('<classifier>sources</classifier>', "Maven dependency classifiers are not supported"),
            ('<type>pom</type>', "Unsupported Maven dependency type"),
        ]
        for extra, error in dependency_variants:
            with self.subTest(extra=extra):
                pom = f'''<project xmlns="http://maven.apache.org/POM/4.0.0">
                  <dependencies><dependency><groupId>app</groupId><artifactId>sample</artifactId>
                  <version>1.0</version>{extra}</dependency></dependencies>
                </project>'''
                with self.assertRaisesRegex(ValueError, error):
                    deps._parse_pom_deps(pom)

    def test_declared_dependency_missing_from_repositories_fails_resolution(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = SimpleNamespace(
                dependencies=["com.example:sample:1.0"],
                cache_dir=os.path.join(tempdir, "cache"),
                libs_dir=os.path.join(tempdir, "libs"),
            )
            with patch.object(deps, "_find_artifact", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "Dependency not found: com.example:sample:1.0"):
                    deps.resolve(config)

    def test_non_jar_packaging_fails_instead_of_copying_a_pom_as_a_jar(self):
        pom_url = "https://repo1.maven.org/maven2/org/example/metadata/1.0/metadata-1.0.pom"
        response = _pom_response(
            '<project xmlns="http://maven.apache.org/POM/4.0.0"><packaging>pom</packaging></project>'
        )
        response.raise_for_status.return_value = None
        with tempfile.TemporaryDirectory() as tempdir:
            config = SimpleNamespace(
                dependencies=["org.example:metadata:1.0"],
                cache_dir=os.path.join(tempdir, "cache"),
                libs_dir=os.path.join(tempdir, "libs"),
            )
            with patch.object(deps, "_find_artifact", return_value=pom_url) as find_artifact, patch.object(
                deps.requests, "get", return_value=response
            ):
                with self.assertRaisesRegex(RuntimeError, "Unsupported Maven packaging: pom"):
                    deps.resolve(config)
            find_artifact.assert_called_once_with("org/example", "metadata", "1.0", "pom")

    def test_unsupported_transitive_pom_reports_dependency_and_source_url(self):
        pom_url = "https://repo1.maven.org/maven2/org/example/sample/1.0/sample-1.0.pom"
        response = _pom_response(
            '<project xmlns="http://maven.apache.org/POM/4.0.0"><parent /></project>'
        )
        response.raise_for_status.return_value = None
        with tempfile.TemporaryDirectory() as tempdir:
            config = SimpleNamespace(
                dependencies=["org.example:sample:1.0"],
                cache_dir=os.path.join(tempdir, "cache"),
                libs_dir=os.path.join(tempdir, "libs"),
            )
            with patch.object(deps, "_find_artifact", return_value=pom_url), patch.object(
                deps.requests, "get", return_value=response
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    r"org.example:sample:1.0.*sample-1.0.pom.*Maven parent POM requires explicit groupId",
                ):
                    deps.resolve(config)

    def test_invalid_dependency_coordinate_fails_without_network_access(self):
        with tempfile.TemporaryDirectory() as tempdir:
            config = SimpleNamespace(
                dependencies=["../../example:sample:1.0"],
                cache_dir=os.path.join(tempdir, "cache"),
                libs_dir=os.path.join(tempdir, "libs"),
            )
            with patch.object(deps, "_find_artifact") as find_artifact:
                with self.assertRaisesRegex(ValueError, "Unsafe dependency coordinate"):
                    deps.resolve(config)
            find_artifact.assert_not_called()

    def test_exact_maven_version_range_normalizes_to_artifact_version(self):
        self.assertEqual(deps._normalize_maven_version("[2.1.0]"), "2.1.0")

    def test_open_maven_version_range_fails_with_supported_range_guidance(self):
        with self.assertRaisesRegex(ValueError, r"only exact versions and \[version\]"):
            deps._normalize_maven_version("[1.0,2.0)")

    def test_resolve_selects_nearest_transitive_version(self):
        namespace = "http://maven.apache.org/POM/4.0.0"
        pom_by_url = {}

        def find_artifact(group_path, artifact, version, extension):
            url = (
                f"https://repo1.maven.org/maven2/{group_path}/{artifact}/{version}/"
                f"{artifact}-{version}.{extension}"
            )
            if extension == "pom":
                dependency = ""
                if artifact == "branch-one":
                    dependency = (
                        '<dependency><groupId>shared</groupId><artifactId>common</artifactId>'
                        '<version>1.0</version></dependency>'
                    )
                elif artifact == "branch-two":
                    dependency = (
                        '<dependency><groupId>shared</groupId><artifactId>common</artifactId>'
                        '<version>2.0</version></dependency>'
                    )
                pom_by_url[url] = (
                    f'<project xmlns="{namespace}"><dependencies>{dependency}</dependencies></project>'
                )
            return url

        def get_pom(url, **kwargs):
            return _pom_response(pom_by_url[url])

        def write_artifact(url, destination):
            with open(destination, "wb") as artifact_file:
                artifact_file.write(b"jar")

        with tempfile.TemporaryDirectory() as tempdir:
            config = SimpleNamespace(
                dependencies=["org.example:branch-one:1.0", "org.example:branch-two:1.0"],
                cache_dir=os.path.join(tempdir, "cache"),
                libs_dir=os.path.join(tempdir, "libs"),
            )
            with patch.object(deps, "_find_artifact", side_effect=find_artifact), patch.object(
                deps.requests, "get", side_effect=get_pom
            ), patch.object(deps, "_download", side_effect=write_artifact), patch.object(
                deps, "_verify_checksum", return_value=None
            ):
                deps.resolve(config)

            selected = os.path.join(
                config.libs_dir, ".termux-builder", "maven", "shared", "common-1.0",
                "common-1.0.jar"
            )
            ignored = os.path.join(
                config.libs_dir, ".termux-builder", "maven", "shared", "common-2.0",
                "common-2.0.jar"
            )
            self.assertTrue(os.path.isfile(selected))
            self.assertFalse(os.path.exists(ignored))
            self.assertEqual(
                {os.path.basename(path) for path in config.resolved_dependency_dirs},
                {"branch-one-1.0", "branch-two-1.0", "common-1.0"},
            )
            with open(os.path.join(
                config.libs_dir, ".termux-builder", "maven", "shared", "common-1.0",
                ".termux-builder-coordinate"
            )) as marker:
                self.assertEqual(marker.read(), "shared:common:1.0")

    def test_implicit_and_explicit_jar_edges_share_one_resolved_library(self):
        namespace = "http://maven.apache.org/POM/4.0.0"
        pom_by_url = {}

        def find_artifact(group_path, artifact, version, extension):
            url = (
                f"https://repo1.maven.org/maven2/{group_path}/{artifact}/{version}/"
                f"{artifact}-{version}.{extension}"
            )
            if extension == "pom":
                dependency = (
                    '<dependency><groupId>org.example</groupId><artifactId>shared</artifactId>'
                    '<version>1.0</version><type>jar</type></dependency>'
                    if artifact == "branch" else ""
                )
                pom_by_url[url] = (
                    f'<project xmlns="{namespace}"><packaging>jar</packaging>'
                    f'<dependencies>{dependency}</dependencies></project>'
                )
            return url

        def get_pom(url, **kwargs):
            return _pom_response(pom_by_url[url])

        def write_artifact(url, destination):
            with open(destination, "wb") as artifact_file:
                artifact_file.write(b"jar")

        with tempfile.TemporaryDirectory() as tempdir:
            config = SimpleNamespace(
                dependencies=["org.example:shared:1.0", "org.example:branch:1.0"],
                cache_dir=os.path.join(tempdir, "cache"),
                libs_dir=os.path.join(tempdir, "libs"),
            )
            with patch.object(deps, "_find_artifact", side_effect=find_artifact), patch.object(
                deps.requests, "get", side_effect=get_pom
            ), patch.object(deps, "_download", side_effect=write_artifact), patch.object(
                deps, "_verify_checksum", return_value=None
            ):
                deps.resolve(config)

            common_dirs = [
                path for path in config.resolved_dependency_dirs
                if os.path.basename(path).startswith("shared-1.0")
            ]
            self.assertEqual(len(common_dirs), 1)
            self.assertEqual(
                len([name for name in os.listdir(common_dirs[0]) if name.endswith(".jar")]),
                1,
            )

    def test_resolve_cleans_stale_aar_staging_for_removed_dependencies(self):
        with tempfile.TemporaryDirectory() as tempdir:
            maven_root = os.path.join(tempdir, "libs", ".termux-builder", "maven")
            stale = os.path.join(maven_root, "org", "example", ".aar-extract-2147483647-dead")
            active = os.path.join(maven_root, "org", "example", f".aar-extract-{os.getpid()}-active")
            os.makedirs(stale)
            os.makedirs(active)
            config = SimpleNamespace(
                dependencies=[],
                cache_dir=os.path.join(tempdir, "cache"),
                libs_dir=os.path.join(tempdir, "libs"),
            )

            deps.resolve(config)

            self.assertFalse(os.path.exists(stale))
            self.assertTrue(os.path.isdir(active))

    def test_implicit_and_explicit_aar_edges_share_one_resolved_library(self):
        namespace = "http://maven.apache.org/POM/4.0.0"
        pom_by_url = {}

        def find_artifact(group_path, artifact, version, extension):
            url = (
                f"https://repo1.maven.org/maven2/{group_path}/{artifact}/{version}/"
                f"{artifact}-{version}.{extension}"
            )
            if extension == "pom":
                dependency = (
                    '<dependency><groupId>org.example</groupId><artifactId>shared</artifactId>'
                    '<version>1.0</version><type>aar</type></dependency>'
                    if artifact == "branch" else ""
                )
                packaging = "aar" if artifact == "shared" else "jar"
                pom_by_url[url] = (
                    f'<project xmlns="{namespace}"><packaging>{packaging}</packaging>'
                    f'<dependencies>{dependency}</dependencies></project>'
                )
            return url

        def write_artifact(url, destination):
            if destination.endswith(".aar"):
                with zipfile.ZipFile(destination, "w") as archive:
                    archive.writestr("AndroidManifest.xml", '<manifest package="org.example"/>')
                    archive.writestr("classes.jar", b"jar")
            else:
                with open(destination, "wb") as artifact_file:
                    artifact_file.write(b"jar")

        with tempfile.TemporaryDirectory() as tempdir:
            config = SimpleNamespace(
                dependencies=["org.example:shared:1.0", "org.example:branch:1.0"],
                cache_dir=os.path.join(tempdir, "cache"),
                libs_dir=os.path.join(tempdir, "libs"),
            )
            with patch.object(deps, "_find_artifact", side_effect=find_artifact), patch.object(
                deps.requests, "get", side_effect=lambda url, **kwargs: _pom_response(
                    pom_by_url[url]
                )
            ), patch.object(deps, "_download", side_effect=write_artifact), patch.object(
                deps, "_verify_checksum", return_value=None
            ):
                deps.resolve(config)

            common_dirs = [
                path for path in config.resolved_dependency_dirs
                if os.path.basename(path).startswith("shared-1.0")
            ]
            self.assertEqual(len(common_dirs), 1)
            self.assertTrue(os.path.isfile(os.path.join(common_dirs[0], "shared-1.0-aar.jar")))

    def test_resolve_applies_exclusions_only_to_the_declaring_path(self):
        namespace = "http://maven.apache.org/POM/4.0.0"
        pom_by_url = {}

        def find_artifact(group_path, artifact, version, extension):
            url = (
                f"https://repo1.maven.org/maven2/{group_path}/{artifact}/{version}/"
                f"{artifact}-{version}.{extension}"
            )
            if extension == "pom":
                if artifact == "root":
                    dependencies = (
                        "<dependency><groupId>org.example</groupId><artifactId>branch-a</artifactId>"
                        "<version>1.0</version><exclusions><exclusion><groupId>shared</groupId>"
                        "<artifactId>common</artifactId></exclusion></exclusions></dependency>"
                        "<dependency><groupId>org.example</groupId><artifactId>branch-b</artifactId>"
                        "<version>1.0</version></dependency>"
                    )
                elif artifact == "branch-a":
                    dependencies = (
                        "<dependency><groupId>shared</groupId><artifactId>common</artifactId>"
                        "<version>1.0</version></dependency>"
                    )
                elif artifact == "branch-b":
                    dependencies = (
                        "<dependency><groupId>shared</groupId><artifactId>common</artifactId>"
                        "<version>2.0</version></dependency>"
                    )
                else:
                    dependencies = ""
                pom_by_url[url] = f'<project xmlns="{namespace}"><dependencies>{dependencies}</dependencies></project>'
            return url

        def get_pom(url, **kwargs):
            return _pom_response(pom_by_url[url])

        def write_artifact(url, destination):
            with open(destination, "wb") as artifact_file:
                artifact_file.write(b"jar")

        with tempfile.TemporaryDirectory() as tempdir:
            config = SimpleNamespace(
                dependencies=["org.example:root:1.0"],
                cache_dir=os.path.join(tempdir, "cache"),
                libs_dir=os.path.join(tempdir, "libs"),
            )
            with patch.object(deps, "_find_artifact", side_effect=find_artifact), patch.object(
                deps.requests, "get", side_effect=get_pom
            ), patch.object(deps, "_download", side_effect=write_artifact), patch.object(
                deps, "_verify_checksum", return_value=None
            ):
                deps.resolve(config)

            self.assertFalse(os.path.exists(os.path.join(
                config.libs_dir, ".termux-builder", "maven", "shared", "common-1.0"
            )))
            self.assertTrue(os.path.isfile(os.path.join(
                config.libs_dir, ".termux-builder", "maven", "shared", "common-2.0",
                "common-2.0.jar"
            )))
            with patch.object(deps, "_find_artifact", side_effect=AssertionError("network lookup")), patch.object(
                deps, "_maven_request", side_effect=AssertionError("network request")
            ):
                deps.resolve(config)
            with patch.object(deps.log, "info") as log_info:
                deps.tree(config)
            displayed = {call.args[2] for call in log_info.call_args_list if len(call.args) > 2}
            self.assertIn("shared:common:2.0", displayed)
            self.assertNotIn("shared:common:1.0", displayed)

    def test_resolve_imports_bom_to_supply_managed_dependency_version(self):
        namespace = "http://maven.apache.org/POM/4.0.0"
        poms = {}

        def find_artifact(group_path, artifact, version, extension):
            url = (
                f"https://repo1.maven.org/maven2/{group_path}/{artifact}/{version}/"
                f"{artifact}-{version}.{extension}"
            )
            if extension == "pom":
                poms.setdefault(url, f'<project xmlns="{namespace}"/>')
            return url

        def get_pom(url, **kwargs):
            return _pom_response(poms[url])

        def write_artifact(url, destination):
            with open(destination, "wb") as artifact_file:
                artifact_file.write(b"jar")

        with tempfile.TemporaryDirectory() as tempdir:
            root_url = "https://repo1.maven.org/maven2/org/example/starter/1.0/starter-1.0.pom"
            bom_url = "https://repo1.maven.org/maven2/org/example/catalog/1.0/catalog-1.0.pom"
            poms[root_url] = f'''<project xmlns="{namespace}">
              <dependencyManagement><dependencies><dependency>
                <groupId>org.example</groupId><artifactId>catalog</artifactId><version>1.0</version>
                <type>pom</type><scope>import</scope>
              </dependency></dependencies></dependencyManagement>
              <dependencies><dependency><groupId>org.example</groupId><artifactId>runtime</artifactId></dependency></dependencies>
            </project>'''
            poms[bom_url] = f'''<project xmlns="{namespace}">
              <dependencyManagement><dependencies><dependency>
                <groupId>org.example</groupId><artifactId>runtime</artifactId><version>2.1</version>
              </dependency></dependencies></dependencyManagement>
            </project>'''
            config = SimpleNamespace(
                dependencies=["org.example:starter:1.0"],
                cache_dir=os.path.join(tempdir, "cache"),
                libs_dir=os.path.join(tempdir, "libs"),
            )
            with patch.object(deps, "_find_artifact", side_effect=find_artifact), patch.object(
                deps.requests, "get", side_effect=get_pom
            ), patch.object(deps, "_download", side_effect=write_artifact), patch.object(
                deps, "_verify_checksum", return_value=None
            ):
                deps.resolve(config)

            self.assertTrue(os.path.isfile(os.path.join(
                config.libs_dir, ".termux-builder", "maven", "org", "example",
                "runtime-2.1", "runtime-2.1.jar"
            )))

    def test_resolve_inherits_parent_properties_management_and_dependencies(self):
        namespace = "http://maven.apache.org/POM/4.0.0"
        poms = {}

        def find_artifact(group_path, artifact, version, extension):
            url = (
                f"https://repo1.maven.org/maven2/{group_path}/{artifact}/{version}/"
                f"{artifact}-{version}.{extension}"
            )
            if extension == "pom":
                poms.setdefault(url, f'<project xmlns="{namespace}"/>')
            return url

        def get_pom(url, **kwargs):
            return _pom_response(poms[url])

        def write_artifact(url, destination):
            with open(destination, "wb") as artifact_file:
                artifact_file.write(b"jar")

        with tempfile.TemporaryDirectory() as tempdir:
            child_url = "https://repo1.maven.org/maven2/org/example/child/1.0/child-1.0.pom"
            parent_url = "https://repo1.maven.org/maven2/org/example/parent/1.0/parent-1.0.pom"
            poms[child_url] = f'''<project xmlns="{namespace}">
              <parent><groupId>org.example</groupId><artifactId>parent</artifactId><version>1.0</version></parent>
              <artifactId>child</artifactId>
              <dependencies><dependency><groupId>org.example</groupId><artifactId>runtime</artifactId></dependency></dependencies>
            </project>'''
            poms[parent_url] = f'''<project xmlns="{namespace}">
              <groupId>org.example</groupId><artifactId>parent</artifactId><version>1.0</version>
              <properties><runtime.version>3.0</runtime.version></properties>
              <dependencyManagement><dependencies><dependency>
                <groupId>org.example</groupId><artifactId>runtime</artifactId><version>${{runtime.version}}</version>
              </dependency></dependencies></dependencyManagement>
              <dependencies><dependency><groupId>org.example</groupId><artifactId>shared</artifactId><version>1.0</version></dependency></dependencies>
            </project>'''
            config = SimpleNamespace(
                dependencies=["org.example:child:1.0"],
                cache_dir=os.path.join(tempdir, "cache"),
                libs_dir=os.path.join(tempdir, "libs"),
            )
            with patch.object(deps, "_find_artifact", side_effect=find_artifact), patch.object(
                deps.requests, "get", side_effect=get_pom
            ), patch.object(deps, "_download", side_effect=write_artifact), patch.object(
                deps, "_verify_checksum", return_value=None
            ):
                deps.resolve(config)

            self.assertTrue(os.path.isfile(os.path.join(
                config.libs_dir, ".termux-builder", "maven", "org", "example",
                "runtime-3.0", "runtime-3.0.jar"
            )))
            self.assertTrue(os.path.isfile(os.path.join(
                config.libs_dir, ".termux-builder", "maven", "org", "example",
                "shared-1.0", "shared-1.0.jar"
            )))

    def test_artifact_discovery_does_not_follow_redirects(self):
        redirect = Mock(status_code=302)
        with patch.object(deps.requests, "head", return_value=redirect) as head, patch.object(
            deps.requests, "get", return_value=redirect
        ) as get:
            with self.assertRaisesRegex(RuntimeError, "Refusing Maven repository redirect"):
                deps._find_artifact("com/example", "sample", "1.0", "jar")

        self.assertTrue(all(call.kwargs["allow_redirects"] is False for call in head.call_args_list))
        self.assertTrue(all(call.kwargs["allow_redirects"] is False for call in get.call_args_list))

    def test_artifact_absent_from_repositories_returns_none(self):
        missing = Mock(status_code=404)
        with patch.object(deps.requests, "head", return_value=missing), patch.object(
            deps.requests, "get", return_value=missing
        ):
            self.assertIsNone(deps._find_artifact("com/example", "sample", "1.0", "jar"))

    def test_artifact_discovery_reports_network_failure(self):
        with patch.object(
            deps.requests, "head", side_effect=deps.requests.ConnectionError("offline")
        ), patch.object(deps.requests, "get", side_effect=deps.requests.ConnectionError("offline")):
            with self.assertRaisesRegex(RuntimeError, "offline"):
                deps._find_artifact("com/example", "sample", "1.0", "jar")

    def test_download_rejects_unconfigured_http_origin_before_request(self):
        with tempfile.TemporaryDirectory() as tempdir:
            destination = os.path.join(tempdir, "sample.jar")
            with patch.object(deps.requests, "get") as get:
                with self.assertRaisesRegex(ValueError, "configured HTTPS Maven repository"):
                    deps._download("http://127.0.0.1/sample.jar", destination)

        get.assert_not_called()

    def test_download_refuses_redirect_and_leaves_no_artifact(self):
        response = Mock(status_code=302)
        response.raise_for_status.return_value = None
        with tempfile.TemporaryDirectory() as tempdir:
            destination = os.path.join(tempdir, "sample.jar")
            with patch.object(deps.requests, "get", return_value=response) as get:
                with self.assertRaisesRegex(RuntimeError, "redirect"):
                    deps._download("https://repo1.maven.org/maven2/sample.jar", destination)

            self.assertFalse(os.path.exists(destination))
            self.assertEqual(os.listdir(tempdir), [])
        self.assertIs(get.call_args.kwargs["allow_redirects"], False)

    def test_download_does_not_follow_preexisting_temp_symlink(self):
        response = Mock(status_code=200)
        response.iter_content.return_value = [b"artifact"]
        response.raise_for_status.return_value = None
        with tempfile.TemporaryDirectory() as tempdir:
            destination = os.path.join(tempdir, "sample.jar")
            victim = os.path.join(tempdir, "user-file.txt")
            with open(victim, "wb") as file:
                file.write(b"keep")
            os.symlink(victim, destination + ".tmp")

            with patch.object(deps.requests, "get", return_value=response):
                deps._download("https://repo1.maven.org/maven2/sample.jar", destination)

            with open(victim, "rb") as file:
                self.assertEqual(file.read(), b"keep")
            with open(destination, "rb") as file:
                self.assertEqual(file.read(), b"artifact")
            self.assertTrue(os.path.islink(destination + ".tmp"))

    def test_resolve_rejects_oversized_pom_response(self):
        namespace = "http://maven.apache.org/POM/4.0.0"
        pom = f'<project xmlns="{namespace}"/>'
        response = Mock(status_code=200, text=pom)
        response.iter_content.return_value = iter(
            [b"x" * (16 * 1024 * 1024), b"x"]
        )

        def write_artifact(url, destination):
            with open(destination, "wb") as artifact_file:
                artifact_file.write(b"jar")

        downloader = Mock(side_effect=write_artifact)

        with tempfile.TemporaryDirectory() as tempdir:
            config = SimpleNamespace(
                dependencies=["org.example:library:1.0"],
                cache_dir=os.path.join(tempdir, "cache"),
                libs_dir=os.path.join(tempdir, "libs"),
            )
            with patch.object(
                deps, "_find_artifact", return_value="https://repo1.maven.org/maven2/org/example/library/1.0/library-1.0.pom"
            ), patch.object(deps.requests, "get", return_value=response), patch.object(
                deps, "_download", downloader
            ), patch.object(deps, "_verify_checksum", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "POM.*16 MiB"):
                    deps.resolve(config)

        downloader.assert_not_called()
        response.close.assert_called_once()

    def test_checksum_verification_rejects_malformed_digest(self):
        response = Mock(status_code=200, text="not-a-digest")
        response.raise_for_status.return_value = None
        with tempfile.TemporaryDirectory() as tempdir:
            artifact = os.path.join(tempdir, "sample.jar")
            with open(artifact, "wb") as file:
                file.write(b"artifact")
            with patch.object(deps.requests, "get", return_value=response):
                with self.assertRaisesRegex(RuntimeError, "Invalid SHA-1 checksum"):
                    deps._verify_checksum(
                        "https://repo1.maven.org/maven2/sample.jar", artifact, "sample:1.0"
                    )

    def test_checksum_verification_rejects_mismatch_and_removes_artifact(self):
        response = Mock(status_code=200, text="0" * 40)
        response.raise_for_status.return_value = None
        with tempfile.TemporaryDirectory() as tempdir:
            artifact = os.path.join(tempdir, "sample.jar")
            with open(artifact, "wb") as file:
                file.write(b"artifact")
            with patch.object(deps.requests, "get", return_value=response):
                with self.assertRaisesRegex(RuntimeError, "Checksum mismatch"):
                    deps._verify_checksum(
                        "https://repo1.maven.org/maven2/sample.jar", artifact, "sample:1.0"
                    )
            self.assertFalse(os.path.exists(artifact))

    def test_checksum_verification_accepts_matching_digest(self):
        digest = hashlib.sha1(b"artifact").hexdigest()
        response = Mock(status_code=200, text=digest)
        response.raise_for_status.return_value = None
        with tempfile.TemporaryDirectory() as tempdir:
            artifact = os.path.join(tempdir, "sample.jar")
            with open(artifact, "wb") as file:
                file.write(b"artifact")
            with patch.object(deps.requests, "get", return_value=response):
                deps._verify_checksum(
                    "https://repo1.maven.org/maven2/sample.jar", artifact, "sample:1.0"
                )

    def test_checksum_verification_skips_only_when_digest_is_absent(self):
        response = Mock(status_code=404)
        with tempfile.TemporaryDirectory() as tempdir:
            artifact = os.path.join(tempdir, "sample.jar")
            with open(artifact, "wb") as file:
                file.write(b"artifact")
            with patch.object(deps.requests, "get", return_value=response):
                deps._verify_checksum(
                    "https://repo1.maven.org/maven2/sample.jar", artifact, "sample:1.0"
                )

    def test_checksum_verification_fails_when_digest_server_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tempdir:
            artifact = os.path.join(tempdir, "sample.jar")
            with open(artifact, "wb") as file:
                file.write(b"artifact")
            with patch.object(
                deps.requests, "get", side_effect=deps.requests.ConnectionError("offline")
            ):
                with self.assertRaisesRegex(RuntimeError, "Failed to fetch checksum.*offline"):
                    deps._verify_checksum(
                        "https://repo1.maven.org/maven2/sample.jar", artifact, "sample:1.0"
                    )


if __name__ == "__main__":
    unittest.main()
