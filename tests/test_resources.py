import hashlib
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from builder import resources


class ResourceCompilationTests(unittest.TestCase):
    def test_aapt1_density_splits_are_requested_and_returned(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = SimpleNamespace(
                build_dir=temp_dir, bin_dir=temp_dir, gen_dir=os.path.join(temp_dir, 'gen'),
                assets_dir=os.path.join(temp_dir, 'assets'), manifest_path='AndroidManifest.xml',
                res_dir=os.path.join(temp_dir, 'res'), min_sdk=21, target_sdk=34,
                version_code=1, version_name='1.0', bin_aapt2='', density_splits=True,
            )
            with patch.object(resources, 'run') as run, patch.object(
                resources, '_get_lib_packages', return_value=''
            ), patch.object(resources, '_resolve_android_jar', return_value='android.jar'):
                result = resources.link_resources(config)
            expected = [(density, os.path.join(temp_dir, 'gen.apk.res_' + density + '-v4'))
                        for density in resources._DENSITY_BUCKETS]
            self.assertEqual(result, expected)
            command = run.call_args.args[0]
            requested = [command[index + 1] for index, value in enumerate(command) if value == '--split']
            self.assertEqual(requested, [density + '-v4' for density in resources._DENSITY_BUCKETS])

    def test_aapt1_refuses_symlinked_density_split_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = os.path.join(temp_dir, 'outside.apk')
            with open(target, 'wb') as output:
                output.write(b'preserve me')
            os.symlink(target, os.path.join(temp_dir, 'gen.apk.res_hdpi-v4'))
            config = SimpleNamespace(
                build_dir=temp_dir, bin_dir=temp_dir, gen_dir=os.path.join(temp_dir, 'gen'),
                assets_dir=os.path.join(temp_dir, 'assets'), manifest_path='AndroidManifest.xml',
                res_dir=os.path.join(temp_dir, 'res'), min_sdk=21, target_sdk=34,
                version_code=1, version_name='1.0', density_splits=True,
            )
            with patch.object(resources, 'run') as run, patch.object(
                resources, '_get_lib_packages', return_value=''
            ):
                with self.assertRaisesRegex(ValueError, 'must not be a symlink'):
                    resources._link_aapt1(config, 'android.jar')
            run.assert_not_called()
            with open(target, 'rb') as input_file:
                self.assertEqual(input_file.read(), b'preserve me')

    def test_aapt2_detection_respects_configured_executable(self):
        config = SimpleNamespace(bin_aapt2='/nonexistent/configured-aapt2')
        with patch.object(resources.shutil, 'which', side_effect=lambda tool: sys.executable if tool == 'aapt2' else None):
            self.assertFalse(resources._has_aapt2(config))
        config.bin_aapt2 = sys.executable
        self.assertTrue(resources._has_aapt2(config))

    def test_aapt2_detection_rejects_non_executable_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            binary = os.path.join(temp_dir, 'aapt2')
            with open(binary, 'w') as output:
                output.write('not executable')
            os.chmod(binary, 0o600)
            with patch.dict(os.environ, {'PATH': ''}):
                self.assertFalse(resources._has_aapt2(SimpleNamespace(bin_aapt2=binary)))

    def test_invalid_configured_aapt2_uses_aapt1_for_apk_resources(self):
        config = SimpleNamespace(bin_aapt2='/nonexistent/configured-aapt2')
        with patch.object(resources.shutil, 'which', side_effect=lambda tool: sys.executable if tool == 'aapt2' else None), \
             patch.object(resources, '_compile_aapt1') as aapt1, patch.object(resources, '_compile_aapt2') as aapt2:
            resources.compile_resources(config)
        aapt1.assert_called_once_with(config)
        aapt2.assert_not_called()

    def test_aapt2_compiles_same_named_libraries_to_distinct_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            compiled_res_dir = os.path.join(temp_dir, "compiled")
            libs_dir = os.path.join(temp_dir, "libs")
            main_res_dir = os.path.join(temp_dir, "app-res")
            os.makedirs(compiled_res_dir)
            os.makedirs(main_res_dir)

            library_res_dirs = []
            for group in ("group-one", "group-two"):
                lib_dir = os.path.join(libs_dir, group, "common-1.0")
                os.makedirs(os.path.join(lib_dir, "res"))
                library_res_dirs.append(os.path.join(lib_dir, "res"))

            stale_output = os.path.join(compiled_res_dir, "common-1.0.zip")
            with open(stale_output, "wb") as output:
                output.write(b"stale")

            config = SimpleNamespace(
                build_dir=temp_dir,
                bin_aapt2="aapt2",
                compiled_res_dir=compiled_res_dir,
                libs_dir=libs_dir,
                res_dir=main_res_dir,
                find_res_dirs=lambda: [main_res_dir],
                find_lib_resource_dirs=lambda: library_res_dirs,
            )

            with patch.object(resources, "run") as run:
                resources._compile_aapt2(config)

            outputs = [call.args[0][-1] for call in run.call_args_list]
            library_outputs = outputs[1:]
            self.assertEqual(len(library_outputs), 2)
            self.assertEqual(len(set(library_outputs)), 2)
            self.assertTrue(os.path.exists(stale_output))

    def test_aapt2_refuses_symlinked_resource_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            compiled_res_dir = os.path.join(temp_dir, "compiled")
            main_res_dir = os.path.join(temp_dir, "app-res")
            os.makedirs(compiled_res_dir)
            os.makedirs(main_res_dir)
            target = os.path.join(temp_dir, "outside.zip")
            with open(target, "wb") as output:
                output.write(b"outside")
            os.symlink(target, os.path.join(compiled_res_dir, "res.zip"))
            config = SimpleNamespace(
                build_dir=temp_dir,
                bin_aapt2="aapt2",
                compiled_res_dir=compiled_res_dir,
                res_dir=main_res_dir,
                find_res_dirs=lambda: [main_res_dir],
                find_lib_resource_dirs=lambda: [],
            )

            with patch.object(resources, "run") as run:
                with self.assertRaisesRegex(ValueError, "resource output must not be a symlink"):
                    resources._compile_aapt2(config)

            run.assert_not_called()
            with open(target, "rb") as output:
                self.assertEqual(output.read(), b"outside")

    def test_aapt2_does_not_create_compiled_resource_dir_through_symlink(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            build_dir = os.path.join(temp_dir, ".build")
            outside_dir = os.path.join(temp_dir, "outside")
            bin_dir = os.path.join(build_dir, "bin")
            compiled_res_dir = os.path.join(bin_dir, "compiled")
            main_res_dir = os.path.join(temp_dir, "app-res")
            os.makedirs(build_dir)
            os.makedirs(outside_dir)
            os.makedirs(main_res_dir)
            os.symlink(outside_dir, bin_dir)
            config = SimpleNamespace(
                build_dir=build_dir,
                bin_aapt2="aapt2",
                compiled_res_dir=compiled_res_dir,
                res_dir=main_res_dir,
                find_res_dirs=lambda: [main_res_dir],
                find_lib_resource_dirs=lambda: [],
            )

            with patch.object(resources, "run") as run:
                with self.assertRaisesRegex(ValueError, "inside the build directory"):
                    resources._compile_aapt2(config)

            run.assert_not_called()
            self.assertFalse(os.path.exists(os.path.join(outside_dir, "compiled")))

    def test_aapt2_link_refuses_symlinked_resource_archive_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            build_dir = os.path.join(temp_dir, ".build")
            bin_dir = os.path.join(build_dir, "bin")
            compiled_res_dir = os.path.join(bin_dir, "res")
            os.makedirs(compiled_res_dir)
            target = os.path.join(temp_dir, "outside.apk")
            with open(target, "wb") as output:
                output.write(b"outside")
            os.symlink(target, os.path.join(bin_dir, "gen.apk.res"))
            config = SimpleNamespace(
                build_dir=build_dir,
                bin_dir=bin_dir,
                compiled_res_dir=compiled_res_dir,
                gen_dir=os.path.join(build_dir, "gen"),
                bin_aapt2="aapt2",
                assets_dir=os.path.join(temp_dir, "assets"),
                libs_dir=os.path.join(temp_dir, ".libs"),
                manifest_path=os.path.join(temp_dir, "AndroidManifest.xml"),
                min_sdk=21,
                target_sdk=34,
                version_code=1,
                version_name="1.0",
                density_splits=False,
                find_res_dirs=lambda: [],
                find_lib_resource_dirs=lambda: [],
                find_lib_asset_dirs=lambda: [],
            )

            with patch.object(resources, "run") as run, patch.object(
                resources, "_get_lib_packages", return_value=""
            ):
                with self.assertRaisesRegex(ValueError, "symlink"):
                    resources._link_aapt2(config, "android.jar")

            run.assert_not_called()
            with open(target, "rb") as output:
                self.assertEqual(output.read(), b"outside")

    def test_aapt2_link_refuses_symlinked_split_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            build_dir = os.path.join(temp_dir, ".build")
            bin_dir = os.path.join(build_dir, "bin")
            compiled_res_dir = os.path.join(bin_dir, "res")
            split_target = os.path.join(temp_dir, "outside-splits")
            os.makedirs(compiled_res_dir)
            os.makedirs(split_target)
            os.symlink(split_target, os.path.join(bin_dir, "splits"))
            config = SimpleNamespace(
                build_dir=build_dir,
                bin_dir=bin_dir,
                compiled_res_dir=compiled_res_dir,
                gen_dir=os.path.join(build_dir, "gen"),
                bin_aapt2="aapt2",
                assets_dir=os.path.join(temp_dir, "assets"),
                libs_dir=os.path.join(temp_dir, ".libs"),
                manifest_path=os.path.join(temp_dir, "AndroidManifest.xml"),
                min_sdk=21,
                target_sdk=34,
                version_code=1,
                version_name="1.0",
                density_splits=True,
                find_res_dirs=lambda: [],
                find_lib_resource_dirs=lambda: [],
                find_lib_asset_dirs=lambda: [],
            )

            with patch.object(resources, "run") as run, patch.object(
                resources, "_get_lib_packages", return_value=""
            ):
                with self.assertRaisesRegex(ValueError, "inside the build directory"):
                    resources._link_aapt2(config, "android.jar")

            run.assert_not_called()

    def test_aapt1_link_refuses_symlinked_resource_archive_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            build_dir = os.path.join(temp_dir, ".build")
            bin_dir = os.path.join(build_dir, "bin")
            os.makedirs(bin_dir)
            target = os.path.join(temp_dir, "outside.apk")
            with open(target, "wb") as output:
                output.write(b"outside")
            os.symlink(target, os.path.join(bin_dir, "gen.apk.res"))
            config = SimpleNamespace(
                build_dir=build_dir,
                bin_dir=bin_dir,
                gen_dir=os.path.join(build_dir, "gen"),
                assets_dir=os.path.join(temp_dir, "assets"),
                libs_dir=os.path.join(temp_dir, ".libs"),
                manifest_path=os.path.join(temp_dir, "AndroidManifest.xml"),
                min_sdk=21,
                target_sdk=34,
                version_code=1,
                version_name="1.0",
                res_dir=os.path.join(temp_dir, "res"),
                find_res_dirs=lambda: [],
                find_lib_resource_dirs=lambda: [],
                find_lib_asset_dirs=lambda: [],
            )

            with patch.object(resources, "run") as run, patch.object(
                resources, "_get_lib_packages", return_value=""
            ):
                with self.assertRaisesRegex(ValueError, "symlink"):
                    resources._link_aapt1(config, "android.jar")

            run.assert_not_called()

    def test_aapt2_link_ignores_stale_archives_and_orders_current_inputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            compiled_res_dir = os.path.join(temp_dir, "compiled")
            libs_dir = os.path.join(temp_dir, "libs")
            os.makedirs(compiled_res_dir)

            library_res_dirs = []
            for group in ("group-two", "group-one"):
                lib_dir = os.path.join(libs_dir, group, "common-1.0")
                os.makedirs(os.path.join(lib_dir, "res"))
                library_res_dirs.append(os.path.join(lib_dir, "res"))

            library_archives = [
                os.path.join(
                    compiled_res_dir,
                    "lib-" + hashlib.sha256(f"{group}/common-1.0".encode()).hexdigest() + ".zip",
                )
                for group in ("group-one", "group-two")
            ]
            expected_archives = [
                *library_archives,
                os.path.join(compiled_res_dir, "res.zip"),
                os.path.join(compiled_res_dir, "res-flavor1.zip"),
            ]
            stale_archive = os.path.join(compiled_res_dir, "stale-library.zip")
            for archive in [*reversed(expected_archives), stale_archive]:
                with open(archive, "wb") as output:
                    output.write(b"resource")

            config = SimpleNamespace(
                build_dir=temp_dir,
                bin_aapt2="aapt2",
                compiled_res_dir=compiled_res_dir,
                gen_dir=os.path.join(temp_dir, "gen"),
                bin_dir=os.path.join(temp_dir, "bin"),
                assets_dir=os.path.join(temp_dir, "assets"),
                manifest_path=os.path.join(temp_dir, "AndroidManifest.xml"),
                libs_dir=libs_dir,
                min_sdk=21,
                target_sdk=34,
                version_code=1,
                version_name="1.0",
                find_res_dirs=lambda: ["app-res", "flavor-res"],
                find_lib_resource_dirs=lambda: library_res_dirs,
            )

            with patch.object(resources, "run") as run, patch.object(
                resources, "_get_lib_packages", return_value=""
            ):
                resources._link_aapt2(config, "android.jar")

            args = run.call_args.args[0]
            actual_archives = [
                args[index + 1]
                for index, argument in enumerate(args[:-1])
                if argument == "-R"
            ]
            self.assertEqual(actual_archives, expected_archives)

    def test_aapt2_link_preserves_direct_dependency_priority(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            compiled_res_dir = os.path.join(temp_dir, "compiled")
            libs_dir = os.path.join(temp_dir, "libs")
            os.makedirs(compiled_res_dir)
            coordinates = {
                "transitive": ("org", "helper", "org.helper:helper:1.0"),
                "first": ("com", "z-library", "com.example:z-library:1.0"),
                "second": ("com", "a-library", "com.example:a-library:1.0"),
            }
            resource_dirs = {}
            for name, (group, artifact, coordinate) in coordinates.items():
                library_dir = os.path.join(
                    libs_dir, group, f"{artifact}-1.0"
                )
                res_dir = os.path.join(library_dir, "res")
                os.makedirs(res_dir)
                with open(os.path.join(library_dir, ".termux-builder-coordinate"), "w") as marker:
                    marker.write(coordinate)
                resource_dirs[name] = res_dir

            main_res_dir = os.path.join(temp_dir, "app-res")
            flavor_res_dir = os.path.join(temp_dir, "flavor-res")
            main_archive = os.path.join(compiled_res_dir, "res.zip")
            flavor_archive = os.path.join(compiled_res_dir, "res-flavor1.zip")
            archive_for = {}
            for name, res_dir in resource_dirs.items():
                library_path = os.path.relpath(os.path.dirname(res_dir), libs_dir).replace(os.sep, "/")
                digest = hashlib.sha256(library_path.encode("utf-8")).hexdigest()
                archive_for[name] = os.path.join(compiled_res_dir, f"lib-{digest}.zip")

            config = SimpleNamespace(
                build_dir=temp_dir,
                bin_aapt2="aapt2",
                compiled_res_dir=compiled_res_dir,
                gen_dir=os.path.join(temp_dir, "gen"),
                bin_dir=os.path.join(temp_dir, "bin"),
                assets_dir=os.path.join(temp_dir, "assets"),
                manifest_path=os.path.join(temp_dir, "AndroidManifest.xml"),
                libs_dir=libs_dir,
                dependencies=["com.example:z-library:1.0", "com.example:a-library:1.0"],
                min_sdk=21,
                target_sdk=34,
                version_code=1,
                version_name="1.0",
                find_res_dirs=lambda: [main_res_dir, flavor_res_dir],
                find_lib_resource_dirs=lambda: list(resource_dirs.values()),
            )
            for archive in [
                archive_for["transitive"], archive_for["second"], archive_for["first"],
                main_archive, flavor_archive,
            ]:
                with open(archive, "wb") as output:
                    output.write(b"resource")

            with patch.object(resources, "run") as run, patch.object(
                resources, "_get_lib_packages", return_value=""
            ):
                resources._link_aapt2(config, "android.jar")

            args = run.call_args.args[0]
            actual_archives = [
                args[index + 1]
                for index, argument in enumerate(args[:-1])
                if argument == "-R"
            ]
            self.assertEqual(actual_archives, [
                archive_for["transitive"], archive_for["second"], archive_for["first"],
                main_archive, flavor_archive,
            ])

    def test_aapt2_link_includes_flavor_main_and_aar_assets_in_priority_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            libs_dir = os.path.join(temp_dir, "libs")
            library_assets = {}
            for name, group, artifact, coordinate in (
                ("transitive", "org", "helper", "org.helper:helper:1.0"),
                ("first", "com", "first", "com.example:first:1.0"),
                ("second", "com", "second", "com.example:second:1.0"),
            ):
                library_dir = os.path.join(libs_dir, group, f"{artifact}-1.0")
                assets_dir = os.path.join(library_dir, "assets")
                os.makedirs(assets_dir)
                with open(os.path.join(library_dir, ".termux-builder-coordinate"), "w") as marker:
                    marker.write(coordinate)
                library_assets[name] = assets_dir

            main_assets = os.path.join(temp_dir, "main-assets")
            flavor_assets = os.path.join(temp_dir, "flavor-assets")
            os.makedirs(main_assets)
            os.makedirs(flavor_assets)
            config = SimpleNamespace(
                build_dir=temp_dir,
                bin_aapt2="aapt2",
                compiled_res_dir=os.path.join(temp_dir, "compiled"),
                gen_dir=os.path.join(temp_dir, "gen"),
                bin_dir=os.path.join(temp_dir, "bin"),
                assets_dir=main_assets,
                flavor_assets_dir=flavor_assets,
                manifest_path=os.path.join(temp_dir, "AndroidManifest.xml"),
                libs_dir=libs_dir,
                dependencies=["com.example:first:1.0", "com.example:second:1.0"],
                min_sdk=21,
                target_sdk=34,
                version_code=1,
                version_name="1.0",
                find_res_dirs=lambda: [],
                find_lib_resource_dirs=lambda: [],
                find_lib_asset_dirs=lambda: list(library_assets.values()),
            )

            with patch.object(resources, "run") as run, patch.object(
                resources, "_get_lib_packages", return_value=""
            ):
                resources._link_aapt2(config, "android.jar")

            args = run.call_args.args[0]
            actual_asset_dirs = [
                args[index + 1]
                for index, argument in enumerate(args[:-1])
                if argument == "-A"
            ]
            self.assertEqual(actual_asset_dirs, [
                flavor_assets,
                main_assets,
                library_assets["first"],
                library_assets["second"],
                library_assets["transitive"],
            ])

    def test_aapt1_link_includes_flavor_and_active_aar_resources_assets_and_packages(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            libs_dir = os.path.join(temp_dir, "libs")
            library_paths = {}
            for name, coordinate, package in (
                ("direct", "com.example:direct:1.0", "com.example.direct"),
                ("transitive", "org.example:helper:2.0", "org.example.helper"),
            ):
                library_dir = os.path.join(libs_dir, name)
                res_dir = os.path.join(library_dir, "res")
                assets_dir = os.path.join(library_dir, "assets")
                os.makedirs(res_dir)
                os.makedirs(assets_dir)
                with open(os.path.join(library_dir, ".termux-builder-coordinate"), "w") as marker:
                    marker.write(coordinate)
                with open(os.path.join(library_dir, "AndroidManifest.xml"), "w") as manifest:
                    manifest.write(f'<manifest package="{package}"/>')
                library_paths[name] = (library_dir, res_dir, assets_dir)

            main_res = os.path.join(temp_dir, "main-res")
            flavor_res = os.path.join(temp_dir, "flavor-res")
            main_assets = os.path.join(temp_dir, "main-assets")
            flavor_assets = os.path.join(temp_dir, "flavor-assets")
            for path in (main_res, flavor_res, main_assets, flavor_assets):
                os.makedirs(path)
            config = SimpleNamespace(
                libs_dir=libs_dir,
                dependencies=["com.example:direct:1.0"],
                gen_dir=os.path.join(temp_dir, "gen"),
                bin_dir=temp_dir,
                min_sdk=21,
                target_sdk=35,
                version_code=1,
                version_name="1.0",
                manifest_path=os.path.join(temp_dir, "AndroidManifest.xml"),
                res_dir=main_res,
                flavor_res_dir=flavor_res,
                assets_dir=main_assets,
                flavor_assets_dir=flavor_assets,
                find_res_dirs=lambda: [main_res, flavor_res],
                find_lib_resource_dirs=lambda: [library_paths["transitive"][1], library_paths["direct"][1]],
                find_lib_asset_dirs=lambda: [library_paths["transitive"][2], library_paths["direct"][2]],
                _library_dirs=lambda: {library_paths["direct"][0], library_paths["transitive"][0]},
            )

            with patch.object(resources, "run") as run:
                resources._link_aapt1(config, "android.jar")

            args = run.call_args.args[0]
            resource_dirs = [
                args[index + 1]
                for index, argument in enumerate(args[:-1])
                if argument == "-S"
            ]
            asset_dirs = [
                args[index + 1]
                for index, argument in enumerate(args[:-1])
                if argument == "-A"
            ]
            self.assertEqual(resource_dirs, [
                flavor_res,
                main_res,
                library_paths["direct"][1],
                library_paths["transitive"][1],
            ])
            self.assertEqual(asset_dirs, [
                flavor_assets,
                main_assets,
                library_paths["direct"][2],
                library_paths["transitive"][2],
            ])
            self.assertIn("--auto-add-overlay", args)
            extra_packages = args.index("--extra-packages")
            self.assertEqual(args[extra_packages + 1], "com.example.direct:org.example.helper")

    def test_aab_proto_resources_fail_clearly_without_aapt2(self):
        config = SimpleNamespace()
        with patch.object(resources, "_resolve_android_jar", return_value="android.jar"), patch.object(
            resources, "_has_aapt2", return_value=False
        ), patch.object(resources, "_link_aapt1") as link_aapt1:
            with self.assertRaisesRegex(RuntimeError, "AAB builds require aapt2"):
                resources.link_resources(config, proto_format=True)
        link_aapt1.assert_not_called()


if __name__ == "__main__":
    unittest.main()
