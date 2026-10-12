import argparse
import os
import secrets
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
import zlib
from contextlib import ExitStack
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch

from builder import cli


class AabBuildCommandTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.config = SimpleNamespace(
            project_dir=self.tempdir.name,
            build_dir=self.tempdir.name,
            bin_dir=self.tempdir.name,
            name="sample",
            build_type="debug",
            view_binding=False,
            aab_enabled=False,
            bin_aapt2=sys.executable,
            bin_javac=sys.executable,
            find_kotlin_files=lambda: [],
            abi_splits=False,
            android_jar=os.path.join(self.tempdir.name, 'android.jar'),
        )
        with zipfile.ZipFile(self.config.android_jar, 'w') as archive:
            archive.writestr('android/app/Activity.class', b'unit class fixture')
        self.addCleanup(self.tempdir.cleanup)
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)

        for target in (
            "builder.deps.resolve",
            "builder.manifest.merge",
            "builder.resources.compile_resources",
            "builder.buildconfig.generate",
            "builder.aidl.compile",
            "builder.compiler.compile_java",
            "builder.compiler.compile_kotlin",
            "builder.dexer.dex",
        ):
            self.patches.enter_context(patch(target))
        self.link_resources = self.patches.enter_context(
            patch("builder.resources.link_resources", return_value=[])
        )
        self.package_apk = self.patches.enter_context(patch("builder.packager.package"))
        self.sign_apk = self.patches.enter_context(patch("builder.signer.sign"))
        self.patches.enter_context(patch("builder.config.Config", return_value=self.config))

    def build_args(self, aab=False, install=False):
        return argparse.Namespace(
            project=self.tempdir.name,
            clean=False,
            install=install,
            flavor=None,
            device=None,
            aab=aab,
        )

    def patch_build_bundle(self):
        self.build_bundle = self.patches.enter_context(
            patch("builder.aab.build_bundle", return_value="sample-debug.aab")
        )

    def test_missing_java_compiler_fails_before_clean_and_dependencies(self):
        self.patch_build_bundle()
        for aab in (False, True):
            with self.subTest(aab=aab), patch('builder.resources._has_aapt2', return_value=True), \
                 patch('builder.cli.find_bin', return_value=sys.executable), \
                 patch('builder.compiler.shutil.which', return_value=None), \
                 patch('builder.compiler._can_use_ecj', return_value=False), \
                 patch('builder.cli._do_clean') as clean, patch('builder.deps.resolve') as resolve:
                args = self.build_args(aab=aab)
                args.clean = True
                with self.assertRaisesRegex(RuntimeError, 'Java compiler.*bins.javac'):
                    cli._build(args)
                clean.assert_not_called()
                resolve.assert_not_called()

    def test_java_apt_requires_javac_before_clean_even_with_ecj(self):
        self.config.annotation_processors = ['fixture-processor.jar']
        for kapt in (False, True):
            self.config.kapt_enabled = kapt
            with self.subTest(kapt=kapt), patch('builder.resources._has_aapt2', return_value=True), \
                 patch('builder.compiler.shutil.which', return_value=None), \
                 patch('builder.compiler._can_use_ecj', return_value=True), \
                 patch('builder.cli._do_clean') as clean, patch('builder.deps.resolve') as resolve:
                args = self.build_args()
                args.clean = True
                with self.assertRaisesRegex(RuntimeError, 'annotation processors require javac'):
                    cli._build(args)
                clean.assert_not_called()
                resolve.assert_not_called()

    def test_ecj_remains_available_for_plain_java_and_kotlin_processor_routes(self):
        for route in ('plain', 'kapt', 'ksp'):
            self.config.annotation_processors = [] if route == 'plain' else ['fixture-processor.jar']
            self.config.kapt_enabled = route == 'kapt'
            self.config.ksp_enabled = route == 'ksp'
            self.config.find_kotlin_files = lambda: ['Value.kt'] if route == 'kapt' else []
            with self.subTest(route=route), patch('builder.resources._has_aapt2', return_value=True), \
                 patch('builder.compiler.shutil.which', return_value=None), \
                 patch('builder.compiler._can_use_ecj', return_value=True), \
                 patch('builder.compiler._effective_java_version', return_value=8), \
                 patch('builder.compiler._compile_java_ecj') as compile_ecj:
                cli._build(self.build_args())
                compile_ecj.assert_called_once()
                source, = compile_ecj.call_args.args[0]
                self.assertEqual(compile_ecj.call_args.args[2], 8)
                self.assertFalse(os.path.exists(source))
        self.assertEqual(self.package_apk.call_count, 3)

    def test_incompatible_ecj_fails_before_clean_and_dependencies(self):
        self.patch_build_bundle()
        for aab in (False, True):
            with self.subTest(aab=aab), patch('builder.resources._has_aapt2', return_value=True), \
                 patch('builder.cli.find_bin', return_value=sys.executable), \
                 patch('builder.compiler.shutil.which', return_value=None), \
                 patch('builder.compiler._can_use_ecj', return_value=True), \
                 patch('builder.compiler._effective_java_version', return_value=17), \
                 patch('builder.compiler._compile_java_ecj', side_effect=subprocess.CalledProcessError(255, ['dalvikvm'])), \
                 patch('builder.cli._do_clean') as clean, patch('builder.deps.resolve') as resolve:
                args = self.build_args(aab=aab)
                args.clean = True
                with self.assertRaisesRegex(RuntimeError, 'ECJ.*Java 17.*javac'):
                    cli._build(args)
                clean.assert_not_called()
                resolve.assert_not_called()

    def test_missing_aab_tools_fail_before_clean_or_dependency_resolution(self):
        self.patch_build_bundle()
        for missing in ('java', 'jarsigner'):
            with self.subTest(missing=missing), \
                 patch('builder.cli.find_bin', create=True, side_effect=lambda tool: None if tool == missing else '/fixture/' + tool), \
                 patch('builder.cli._do_clean') as clean, \
                 patch('builder.deps.resolve') as resolve:
                args = self.build_args(aab=True)
                args.clean = True
                with self.assertRaisesRegex(RuntimeError, missing + ' not found'):
                    cli._build(args)
                clean.assert_not_called()
                resolve.assert_not_called()
                self.build_bundle.assert_not_called()

    def test_missing_release_r8_fails_before_clean_or_dependency_resolution(self):
        self.config.r8_enabled = True
        self.config.build_type = 'release'
        args = self.build_args()
        args.clean = True
        with patch('builder.cli.shutil.which', return_value=None), \
             patch('builder.cli._do_clean') as clean, patch('builder.deps.resolve') as resolve:
            with self.assertRaisesRegex(RuntimeError, 'r8 enabled'):
                cli._build(args)
            clean.assert_not_called()
            resolve.assert_not_called()

    def test_combined_abi_and_density_splits_fail_before_clean(self):
        self.config.abi_splits = True
        self.config.density_splits = True
        args = self.build_args()
        args.clean = True
        with patch('builder.cli._do_clean') as clean, patch('builder.deps.resolve') as resolve, \
             patch('builder.packager.available_abis', return_value=['arm64-v8a']):
            with self.assertRaisesRegex(ValueError, 'abi-splits.*density-splits'):
                cli._build(args)
            clean.assert_not_called()
            resolve.assert_not_called()
            self.package_apk.assert_not_called()

    def test_missing_apk_resource_tools_fail_before_clean_or_dependencies(self):
        self.config.bin_aapt2 = '/nonexistent/configured-aapt2'
        args = self.build_args()
        args.clean = True
        with patch('builder.resources.shutil.which', return_value=None), \
             patch('builder.cli._do_clean') as clean, patch('builder.deps.resolve') as resolve:
            with self.assertRaisesRegex(RuntimeError, 'aapt2.*aapt'):
                cli._build(args)
            clean.assert_not_called()
            resolve.assert_not_called()
            self.package_apk.assert_not_called()

    def test_apk_keeps_aapt1_fallback_when_configured_aapt2_is_absent(self):
        self.config.bin_aapt2 = '/nonexistent/configured-aapt2'
        with patch('builder.resources.shutil.which', side_effect=lambda tool: sys.executable if tool in ('aapt', self.config.bin_javac) else None):
            cli._build(self.build_args())
        self.package_apk.assert_called_once_with(self.config)

    def test_missing_android_jar_fails_before_clean_or_dependency_resolution(self):
        self.patch_build_bundle()
        self.config.android_jar = os.path.join(self.tempdir.name, 'absent-android.jar')
        for aab in (False, True):
            with self.subTest(aab=aab), patch('builder.cli._do_clean') as clean, \
                 patch('builder.deps.resolve') as resolve:
                args = self.build_args(aab=aab)
                args.clean = True
                with self.assertRaisesRegex(FileNotFoundError, 'android.jar not found'):
                    cli._build(args)
                clean.assert_not_called()
                resolve.assert_not_called()

    def test_invalid_android_jar_fails_before_clean_or_dependency_resolution(self):
        self.patch_build_bundle()
        jar = Path(self.config.android_jar)
        for damage in ('not-zip', 'empty', 'missing-framework', 'crc', 'duplicate', 'compression',
                       'oversized', 'hidden-payload', 'encrypted', 'empty-class', 'null-name'):
            for aab in (False, True):
                with self.subTest(damage=damage, aab=aab):
                    with zipfile.ZipFile(jar, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                        if damage != 'empty':
                            name = 'other.class' if damage == 'missing-framework' else 'android/app/Activity.class'
                            if damage == 'null-name':
                                name += 'X'
                            archive.writestr(name, b'' if damage == 'empty-class' else b'unit class fixture')
                            if damage == 'duplicate':
                                archive.writestr(name, b'duplicate class fixture')
                    data = bytearray(jar.read_bytes())
                    if damage == 'not-zip':
                        data = b'invalid SDK fixture'
                    elif damage == 'crc':
                        data[30 + len('android/app/Activity.class')] ^= 1
                    elif damage == 'null-name':
                        data = data.replace(b'android/app/Activity.classX', b'android/app/Activity.class\x00')
                    elif damage == 'hidden-payload':
                        checksum = zlib.crc32(b'unit')
                        central = data.index(b'PK\x01\x02')
                        struct.pack_into('<I', data, 14, checksum)
                        struct.pack_into('<I', data, 22, 4)
                        struct.pack_into('<I', data, central + 16, checksum)
                        struct.pack_into('<I', data, central + 24, 4)
                        jar.write_bytes(data)
                        with zipfile.ZipFile(jar) as archive:
                            self.assertIsNone(archive.testzip())
                    elif damage == 'encrypted':
                        struct.pack_into('<H', data, 6, 1)
                        struct.pack_into('<H', data, data.index(b'PK\x01\x02') + 8, 1)
                    elif damage == 'compression':
                        struct.pack_into('<H', data, 8, zipfile.ZIP_BZIP2)
                        struct.pack_into('<H', data, data.index(b'PK\x01\x02') + 10, zipfile.ZIP_BZIP2)
                    elif damage == 'oversized':
                        struct.pack_into('<I', data, data.index(b'PK\x01\x02') + 24, 1024**3 + 1)
                    jar.write_bytes(data)
                    args = self.build_args(aab=aab)
                    args.clean = True
                    with patch('builder.cli._do_clean') as clean, patch('builder.deps.resolve') as resolve:
                        with self.assertRaisesRegex(RuntimeError, 'android.jar verification failed'):
                            cli._build(args)
                        clean.assert_not_called()
                        resolve.assert_not_called()

    def test_sdk_zip_directory_is_bounded_before_zipfile_parsing(self):
        from builder.resources import _resolve_android_jar
        with zipfile.ZipFile(self.config.android_jar, 'w') as archive:
            archive.writestr('android/app/Activity.class', b'class fixture')
            for index in range(65535):
                archive.writestr(str(index), b'')
        with patch('zipfile.ZipFile', side_effect=AssertionError('ZIP parsed before directory bounds')):
            with self.assertRaisesRegex(RuntimeError, 'android.jar verification failed'):
                _resolve_android_jar(self.config)

    def test_sdk_payload_verification_accepts_stored_and_deflated_chunks(self):
        from builder.resources import _resolve_android_jar
        for compression in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            for size in (1, 65535, 65536, 65537, 4 * 1024**2):
                with self.subTest(compression=compression, size=size):
                    with zipfile.ZipFile(self.config.android_jar, 'w', compression=compression) as archive:
                        archive.writestr('android/app/Activity.class', b'x' * size)
                        archive.writestr('android/app/', b'')
                    self.assertEqual(_resolve_android_jar(self.config), self.config.android_jar)

    def test_sdk_zip_end_record_matches_zipfile_parser(self):
        from builder.resources import _resolve_android_jar
        for damage in ('embedded-end-record', 'zip64-locator'):
            with self.subTest(damage=damage):
                with zipfile.ZipFile(self.config.android_jar, 'w') as archive:
                    member = zipfile.ZipInfo('android/app/Activity.class')
                    if damage == 'zip64-locator':
                        member.comment = struct.pack('<4sQ2H2L4Q', b'PK\x06\x06', 44, 45, 45,
                                                     0, 0, 0, 0, 0, 0)
                        member.comment += struct.pack('<4sLQL', b'PK\x06\x07', 0, 0, 1)
                    archive.writestr(member, b'class fixture')
                    if damage == 'embedded-end-record':
                        archive.comment = struct.pack('<4s4H2IH', b'PK\x05\x06', 0, 0,
                                                      0, 0, 0, 0, 1) + b'xx'
                with patch('zipfile.ZipFile', side_effect=AssertionError('ZIP parsed ambiguous end record')):
                    with self.assertRaisesRegex(RuntimeError, 'android.jar verification failed'):
                        _resolve_android_jar(self.config)

    def test_sdk_zip_end_record_fast_path_ignores_magic_in_numeric_fields(self):
        from builder.resources import _resolve_android_jar
        jar = Path(self.config.android_jar)
        with zipfile.ZipFile(jar, 'w') as archive:
            archive.writestr('android/app/Activity.class', b'class fixture')
            for index in range(19279):
                archive.writestr(str(index), b'')
        data = jar.read_bytes()
        directory_size = struct.unpack_from('<I', data, len(data) - 10)[0]
        padding = (1541 - directory_size) % 65536
        with zipfile.ZipFile(jar) as archive:
            entries = [(member, archive.read(member)) for member in archive.infolist()]
        with zipfile.ZipFile(jar, 'w') as archive:
            entries[0][0].comment = b'x' * padding
            for member, content in entries:
                archive.writestr(member, content)
        data = jar.read_bytes()
        self.assertEqual(data[-12:-8], b'PK\x05\x06')
        with zipfile.ZipFile(jar) as archive:
            self.assertEqual(len(archive.infolist()), 19280)
            self.assertIsNone(archive.testzip())
        self.assertEqual(_resolve_android_jar(self.config), self.config.android_jar)

    def test_unusable_aapt2_fails_before_aab_clean(self):
        self.patch_build_bundle()
        for binary in (None, '/nonexistent/aapt2'):
            with self.subTest(binary=binary), patch('builder.cli._do_clean') as clean, \
                 patch('builder.deps.resolve') as resolve:
                self.config.bin_aapt2 = binary
                self.config.aab_enabled = True
                args = self.build_args(aab=False)
                args.clean = True
                with self.assertRaisesRegex(RuntimeError, 'aapt2 not found'):
                    cli._build(args)
                clean.assert_not_called()
                resolve.assert_not_called()
                self.build_bundle.assert_not_called()

    def test_aab_flag_routes_build_to_bundle_pipeline(self):
        self.patch_build_bundle()
        cli._build(self.build_args(aab=True))

        self.build_bundle.assert_called_once_with(self.config)
        self.link_resources.assert_not_called()
        self.package_apk.assert_not_called()
        self.sign_apk.assert_not_called()

    def test_project_aab_setting_routes_build_to_bundle_pipeline(self):
        self.patch_build_bundle()
        self.config.aab_enabled = True
        cli._build(self.build_args())

        self.build_bundle.assert_called_once_with(self.config)
        self.link_resources.assert_not_called()
        self.package_apk.assert_not_called()
        self.sign_apk.assert_not_called()

    def test_aab_cannot_be_installed_as_an_apk(self):
        self.patch_build_bundle()
        with self.assertRaisesRegex(ValueError, "AAB.*install"):
            cli._build(self.build_args(aab=True, install=True))

        self.build_bundle.assert_not_called()

    def test_default_build_still_packages_and_signs_an_apk(self):
        self.patch_build_bundle()
        self.sign_apk.return_value = "sample-debug.apk"
        cli._build(self.build_args())

        self.build_bundle.assert_not_called()
        self.link_resources.assert_called_once_with(self.config)
        self.package_apk.assert_called_once_with(self.config)
        self.sign_apk.assert_called_once_with(self.config)

    def test_density_split_output_name_includes_flavor(self):
        self.config.flavor = "paid"
        self.config.build_dir = self.tempdir.name
        self.link_resources.return_value = [("hdpi", "split-hdpi.apk")]
        args = self.build_args()
        args.flavor = "paid"

        with patch("builder.signer.sign_apk") as sign_split:
            cli._build(args)

        self.assertEqual(
            sign_split.call_args.args[2],
            os.path.join(self.tempdir.name, "sample-paid-hdpi-debug.apk"),
        )

    def test_cli_accepts_aab_flag(self):
        with patch.object(cli, "_build") as build, patch.object(
            sys, "argv", ["termux-builder", "build", self.tempdir.name, "--aab"]
        ):
            cli.main()

        self.assertTrue(build.call_args.args[0].aab)

    def test_signing_uses_key_password_from_environment(self):
        from builder.aab import _sign_aab

        keystore_path = os.path.join(self.tempdir.name, "release.keystore")
        with open(keystore_path, "wb") as keystore:
            keystore.write(b"keystore")
        config = SimpleNamespace(
            keystore_path=keystore_path,
            keystore_alias="release",
            keystore_store_pass="store-secret",
            keystore_key_pass="key-secret",
        )
        with patch("builder.aab.run") as run:
            run.return_value.stdout = "jar verified."
            _sign_aab(config, "sample.aab")

        self.assertEqual(run.call_count, 1)
        sign_args = run.call_args_list[0].args[0]
        self.assertIn("-keypass:env", sign_args)
        self.assertEqual(sign_args[sign_args.index("-keypass:env") + 1], "_TB_KEY_PASS")
        self.assertNotIn("store-secret", sign_args)
        self.assertNotIn("key-secret", sign_args)
        self.assertEqual(run.call_args_list[0].kwargs["env"]["_TB_KEY_PASS"], "key-secret")

    def test_proto_archive_rejects_path_traversal(self):
        from builder.aab import _prepare_base_module

        proto_path = os.path.join(self.tempdir.name, "proto.apk")
        base_dir = os.path.join(self.tempdir.name, "bundle", "base")
        os.makedirs(base_dir)
        with zipfile.ZipFile(proto_path, "w") as proto:
            proto.writestr("AndroidManifest.xml", "manifest")
            proto.writestr("resources.pb", "resources")
            proto.writestr("../escaped.txt", "outside bundle module")
        config = SimpleNamespace(
            dex_dir=os.path.join(self.tempdir.name, "dex"),
            jni_dir=os.path.join(self.tempdir.name, "jni"),
            assets_dir=os.path.join(self.tempdir.name, "assets"),
        )

        with self.assertRaisesRegex(ValueError, "Unsafe archive member"):
            _prepare_base_module(config, base_dir, proto_path)

        self.assertFalse(os.path.exists(os.path.join(self.tempdir.name, "bundle", "escaped.txt")))

    def test_proto_archive_rejects_symlink_entries(self):
        from builder.aab import _prepare_base_module

        proto_path = os.path.join(self.tempdir.name, "symlink-proto.apk")
        base_dir = os.path.join(self.tempdir.name, "symlink-bundle", "base")
        os.makedirs(base_dir)
        symlink = zipfile.ZipInfo("link")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(proto_path, "w") as proto:
            proto.writestr("AndroidManifest.xml", "manifest")
            proto.writestr("resources.pb", "resources")
            proto.writestr(symlink, "../outside")
        config = SimpleNamespace(
            dex_dir=os.path.join(self.tempdir.name, "dex"),
            jni_dir=os.path.join(self.tempdir.name, "jni"),
            assets_dir=os.path.join(self.tempdir.name, "assets"),
        )

        with self.assertRaisesRegex(ValueError, "Unsafe archive member symlink"):
            _prepare_base_module(config, base_dir, proto_path)

    def test_aab_verification_refuses_duplicate_and_unsafe_entries(self):
        from builder.aab import _verify_aab
        required = ('BundleConfig.pb', 'base/manifest/AndroidManifest.xml', 'base/resources.pb')
        for extra in ('BundleConfig.pb', '../escape', '/absolute', 'base/../escape', 'base\\escape', 'base//escape', 'symlink'):
            with self.subTest(extra=extra):
                aab_path = os.path.join(self.tempdir.name, 'unsafe.aab')
                with zipfile.ZipFile(aab_path, 'w') as bundle:
                    for entry in required:
                        bundle.writestr(entry, 'fixture')
                    import warnings
                    with warnings.catch_warnings():
                        warnings.simplefilter('ignore', UserWarning)
                        if extra == 'symlink':
                            member = zipfile.ZipInfo('base/assets/link')
                            member.create_system = 3
                            member.external_attr = 0o120777 << 16
                            bundle.writestr(member, '../target')
                        else:
                            bundle.writestr(extra, 'fixture')
                with patch('builder.aab.run') as execute:
                    execute.return_value.stdout = 'jar verified.'
                    with self.assertRaisesRegex(RuntimeError, 'AAB.*(duplicate|unsafe)'):
                        _verify_aab(aab_path, ['bundletool'])
                    execute.assert_not_called()

    def test_aab_verification_refuses_empty_base_manifest(self):
        from builder.aab import _verify_aab
        aab_path = os.path.join(self.tempdir.name, 'empty-manifest.aab')
        with zipfile.ZipFile(aab_path, 'w') as bundle:
            bundle.writestr('BundleConfig.pb', 'fixture')
            bundle.writestr('base/resources.pb', 'fixture')
            bundle.writestr('base/manifest/AndroidManifest.xml', b'')
        with patch('builder.aab.run') as execute:
            execute.return_value.stdout = 'jar verified.'
            with self.assertRaisesRegex(RuntimeError, 'AAB.*empty.*manifest'):
                _verify_aab(aab_path, ['bundletool'])
            execute.assert_not_called()

    def test_aab_verification_refuses_corrupted_entry_crc(self):
        from builder.aab import _verify_aab
        aab_path = os.path.join(self.tempdir.name, 'corrupt-crc.aab')
        with zipfile.ZipFile(aab_path, 'w', compression=zipfile.ZIP_STORED) as bundle:
            for entry in ('BundleConfig.pb', 'base/resources.pb', 'base/manifest/AndroidManifest.xml'):
                bundle.writestr(entry, 'fixture')
            bundle.writestr('base/assets/data.txt', b'unique CRC payload')
        with open(aab_path, 'rb') as archive:
            original = archive.read()
        self.assertEqual(original.count(b'unique CRC payload'), 1)
        with open(aab_path, 'wb') as archive:
            archive.write(original.replace(b'unique CRC payload', b'broken CRC payload'))
        with patch('builder.aab.run') as execute:
            execute.return_value.stdout = 'jar verified.'
            with self.assertRaisesRegex(RuntimeError, 'AAB.*CRC'):
                _verify_aab(aab_path, ['bundletool'])
            execute.assert_not_called()

    def test_aab_verification_requires_structure_and_valid_signature(self):
        from builder.aab import _verify_aab

        aab_path = os.path.join(self.tempdir.name, "sample.aab")
        with zipfile.ZipFile(aab_path, "w") as bundle:
            for entry in (
                "BundleConfig.pb",
                "base/manifest/AndroidManifest.xml",
                "base/resources.pb",
            ):
                bundle.writestr(entry, "valid")

        with patch("builder.aab.run") as run:
            run.return_value.stdout = "jar verified."
            run.return_value.returncode = 0
            _verify_aab(aab_path, ["bundletool"])
            self.assertEqual(
                run.call_args_list[1].args[0],
                ["bundletool", "validate", "--bundle", aab_path],
            )
            self.assertIn("-verify", run.call_args_list[2].args[0])

            run.return_value.stdout = "jar is unsigned."
            with self.assertRaisesRegex(RuntimeError, "signature verification failed"):
                _verify_aab(aab_path, ["bundletool"])

        with zipfile.ZipFile(aab_path, "w") as bundle:
            bundle.writestr("BundleConfig.pb", "valid")
        with self.assertRaisesRegex(RuntimeError, "missing required entries"):
            _verify_aab(aab_path, ["bundletool"])

    def test_aab_verification_checks_strict_warning_exit_bits(self):
        from builder.aab import _verify_aab
        aab_path = os.path.join(self.tempdir.name, 'strict.aab')
        with zipfile.ZipFile(aab_path, 'w') as archive:
            for name in ('BundleConfig.pb', 'base/manifest/AndroidManifest.xml', 'base/resources.pb'):
                archive.writestr(name, b'fixture')
        for code in (0, 4):
            with self.subTest(code=code), patch('builder.aab.run', side_effect=[
                SimpleNamespace(returncode=0),
                SimpleNamespace(returncode=code, stdout='jar verified, with signer errors.'),
            ]) as execute:
                _verify_aab(aab_path)
                self.assertIn('-strict', execute.call_args_list[1].args[0])
                self.assertFalse(execute.call_args_list[1].kwargs['check'])
        for code in (1, 8, 12, 16, 20, 24, 32, 36, 64, 68, 128):
            with self.subTest(code=code), patch('builder.aab.run', side_effect=[
                SimpleNamespace(returncode=0),
                SimpleNamespace(returncode=code, stdout='jar verified, with signer errors.'),
            ]) as execute:
                with self.assertRaisesRegex(RuntimeError, 'signature verification failed'):
                    _verify_aab(aab_path)
                self.assertEqual(execute.call_count, 2)

    def test_signature_coverage_failure_redacts_child_diagnostics(self):
        from builder.aab import _verify_aab
        aab_path = os.path.join(self.tempdir.name, 'coverage.aab')
        with zipfile.ZipFile(aab_path, 'w') as archive:
            for name in ('BundleConfig.pb', 'base/manifest/AndroidManifest.xml', 'base/resources.pb'):
                archive.writestr(name, b'fixture')
        secret = secrets.token_hex(16)
        for code in (1, 2, 3, 4, 5):
            with self.subTest(code=code), patch('builder.aab.run',
                return_value=SimpleNamespace(returncode=code, stderr='Picked up JAVA_TOOL_OPTIONS: password=' + secret)):
                with self.assertRaisesRegex(RuntimeError, 'signature coverage verification failed') as error:
                    _verify_aab(aab_path)
            self.assertNotIn(secret, str(error.exception))
            self.assertNotIn('JAVA_TOOL_OPTIONS', str(error.exception))

    def test_bundle_build_verifies_the_signed_output(self):
        from builder.aab import build_bundle

        self.config.cache_dir = os.path.join(self.tempdir.name, "cache")
        self.config.flavor = "paid"
        linked = os.path.join(self.config.bin_dir, "gen.apk.res")
        with patch("builder.aab._find_bundletool", return_value=["bundletool"]), patch(
            "builder.resources.link_resources", side_effect=lambda config, **kwargs: open(linked, "wb").close()
        ), patch("builder.aab._prepare_base_module"), patch("builder.aab._sign_aab") as sign, patch(
            "builder.aab._verify_aab"
        ) as verify, patch("builder.aab.run") as run:
            def create_bundle(args):
                output = args[args.index("--output") + 1]
                with zipfile.ZipFile(output, "w") as bundle:
                    bundle.writestr("BundleConfig.pb", "valid")
                    bundle.writestr("base/manifest/AndroidManifest.xml", "valid")
                    bundle.writestr("base/resources.pb", "valid")

            run.side_effect = create_bundle
            aab_path = build_bundle(self.config)

        staging_path = sign.call_args.args[1]
        self.assertEqual(os.path.dirname(staging_path), self.config.build_dir)
        sign.assert_called_once_with(self.config, staging_path)
        verify.assert_called_once_with(staging_path, ["bundletool"])
        self.assertTrue(os.path.isfile(aab_path))
        self.assertEqual(os.path.basename(aab_path), "sample-paid-debug.aab")

    def test_failed_bundle_verification_preserves_previous_aab(self):
        from builder.aab import build_bundle

        self.config.cache_dir = os.path.join(self.tempdir.name, "cache")
        self.config.flavor = "paid"
        existing = os.path.join(self.config.build_dir, "sample-paid-debug.aab")
        with open(existing, "wb") as previous:
            previous.write(b"previous verified bundle")
        linked = os.path.join(self.config.bin_dir, "gen.apk.res")

        with patch("builder.aab._find_bundletool", return_value=["bundletool"]), patch(
            "builder.resources.link_resources", side_effect=lambda config, **kwargs: open(linked, "wb").close()
        ), patch("builder.aab._prepare_base_module"), patch("builder.aab._sign_aab"), patch(
            "builder.aab._verify_aab", side_effect=RuntimeError("invalid bundle")
        ), patch("builder.aab.run") as run:
            def create_bundle(args):
                output = args[args.index("--output") + 1]
                with zipfile.ZipFile(output, "w") as bundle:
                    bundle.writestr("BundleConfig.pb", "invalid")

            run.side_effect = create_bundle
            with self.assertRaisesRegex(RuntimeError, "invalid bundle"):
                build_bundle(self.config)

        with open(existing, "rb") as previous:
            self.assertEqual(previous.read(), b"previous verified bundle")

    def test_prepare_base_module_clears_stale_entries_between_builds(self):
        from builder.aab import _prepare_base_module

        base_dir = os.path.join(self.tempdir.name, "bundle", "base")
        proto_path = os.path.join(self.tempdir.name, "proto.apk")
        os.makedirs(base_dir)
        config = SimpleNamespace(
            dex_dir=os.path.join(self.tempdir.name, "dex"),
            jni_dir=os.path.join(self.tempdir.name, "jni"),
            assets_dir=os.path.join(self.tempdir.name, "assets"),
        )
        for resource in ("old", "new"):
            with zipfile.ZipFile(proto_path, "w") as proto:
                proto.writestr("AndroidManifest.xml", "manifest")
                proto.writestr("resources.pb", "resources")
                proto.writestr(f"res/{resource}.xml", resource)
            _prepare_base_module(config, base_dir, proto_path)

        self.assertFalse(os.path.exists(os.path.join(base_dir, "res", "old.xml")))
        self.assertTrue(os.path.isfile(os.path.join(base_dir, "res", "new.xml")))

    def test_prepare_base_module_refuses_to_clear_paths_outside_build_directory(self):
        from builder.aab import _prepare_base_module

        build_dir = os.path.join(self.tempdir.name, "build")
        outside_dir = os.path.join(self.tempdir.name, "outside", "base")
        os.makedirs(outside_dir)
        sentinel = os.path.join(outside_dir, "user-data")
        with open(sentinel, "w") as output:
            output.write("preserve")
        proto_path = os.path.join(self.tempdir.name, "proto.apk")
        with zipfile.ZipFile(proto_path, "w") as proto:
            proto.writestr("AndroidManifest.xml", "manifest")
            proto.writestr("resources.pb", "resources")
        config = SimpleNamespace(
            build_dir=build_dir,
            dex_dir=os.path.join(self.tempdir.name, "dex"),
            jni_dir=os.path.join(self.tempdir.name, "jni"),
            assets_dir=os.path.join(self.tempdir.name, "assets"),
        )

        with self.assertRaisesRegex(ValueError, "outside the configured build directory"):
            _prepare_base_module(config, outside_dir, proto_path)

        with open(sentinel) as output:
            self.assertEqual(output.read(), "preserve")

    def test_bundle_build_does_not_create_base_through_external_symlink(self):
        from builder import aab

        build_dir = os.path.join(self.tempdir.name, "build")
        outside_dir = os.path.join(self.tempdir.name, "outside")
        os.makedirs(build_dir)
        os.makedirs(outside_dir)
        os.symlink(outside_dir, os.path.join(build_dir, "bundle"))
        config = SimpleNamespace(
            build_dir=build_dir,
            bin_dir=os.path.join(build_dir, "bin"),
        )

        with patch.object(aab, "_find_bundletool", return_value=["bundletool"]), patch(
            "builder.resources.link_resources"
        ) as link_resources:
            with self.assertRaisesRegex(ValueError, "symlink|inside the build directory"):
                aab.build_bundle(config)

        link_resources.assert_not_called()
        self.assertFalse(os.path.exists(os.path.join(outside_dir, "base")))

    def test_bundle_build_rejects_external_base_symlink_before_linking_resources(self):
        from builder import aab

        build_dir = os.path.join(self.tempdir.name, "build")
        bundle_dir = os.path.join(build_dir, "bundle")
        outside_dir = os.path.join(self.tempdir.name, "outside")
        os.makedirs(bundle_dir)
        os.makedirs(outside_dir)
        os.symlink(outside_dir, os.path.join(bundle_dir, "base"))
        config = SimpleNamespace(
            build_dir=build_dir,
            bin_dir=os.path.join(build_dir, "bin"),
        )

        with patch.object(aab, "_find_bundletool", return_value=["bundletool"]), patch(
            "builder.resources.link_resources"
        ) as link_resources:
            with self.assertRaisesRegex(ValueError, "symlink|inside the build directory"):
                aab.build_bundle(config)

        link_resources.assert_not_called()
        self.assertEqual(os.listdir(outside_dir), [])

    def test_prepare_base_module_assigns_unique_names_to_duplicate_dex_basenames(self):
        from builder.aab import _prepare_base_module

        base_dir = os.path.join(self.tempdir.name, "bundle", "base")
        proto_path = os.path.join(self.tempdir.name, "proto.apk")
        dex_dir = os.path.join(self.tempdir.name, "dex")
        os.makedirs(os.path.join(dex_dir, "first"))
        os.makedirs(os.path.join(dex_dir, "second"))
        with open(os.path.join(dex_dir, "first", "classes.dex"), "wb") as dex:
            dex.write(b"first")
        with open(os.path.join(dex_dir, "second", "classes.dex"), "wb") as dex:
            dex.write(b"second")
        with zipfile.ZipFile(proto_path, "w") as proto:
            proto.writestr("AndroidManifest.xml", "manifest")
            proto.writestr("resources.pb", "resources")
        config = SimpleNamespace(
            dex_dir=dex_dir,
            jni_dir=os.path.join(self.tempdir.name, "jni"),
            assets_dir=os.path.join(self.tempdir.name, "assets"),
        )

        _prepare_base_module(config, base_dir, proto_path)

        dex_module = os.path.join(base_dir, "dex")
        self.assertEqual(sorted(os.listdir(dex_module)), ["classes.dex", "classes2.dex"])
        dex_contents = set()
        for name in os.listdir(dex_module):
            with open(os.path.join(dex_module, name), "rb") as dex:
                dex_contents.add(dex.read())
        self.assertEqual(dex_contents, {b"first", b"second"})

    def test_prepare_base_module_includes_library_dex_outputs(self):
        from builder.aab import _prepare_base_module

        base_dir = os.path.join(self.tempdir.name, "bundle", "base")
        proto_path = os.path.join(self.tempdir.name, "proto.apk")
        dex_dir = os.path.join(self.tempdir.name, "dex")
        library_dex_dir = os.path.join(self.tempdir.name, "cache", "dex-libraries", "fingerprint")
        os.makedirs(dex_dir)
        os.makedirs(os.path.join(library_dex_dir, "lib-0000"))
        with open(os.path.join(dex_dir, "classes.dex"), "wb") as dex:
            dex.write(b"app")
        with open(os.path.join(library_dex_dir, "lib-0000", "classes.dex"), "wb") as dex:
            dex.write(b"library")
        with zipfile.ZipFile(proto_path, "w") as proto:
            proto.writestr("AndroidManifest.xml", "manifest")
            proto.writestr("resources.pb", "resources")
        config = SimpleNamespace(
            dex_dir=dex_dir,
            library_dex_dir=library_dex_dir,
            jni_dir=os.path.join(self.tempdir.name, "jni"),
            assets_dir=os.path.join(self.tempdir.name, "assets"),
        )

        _prepare_base_module(config, base_dir, proto_path)

        dex_module = os.path.join(base_dir, "dex")
        contents = {}
        for name in sorted(os.listdir(dex_module)):
            with open(os.path.join(dex_module, name), "rb") as dex:
                contents[name] = dex.read()
        self.assertEqual(contents, {"classes.dex": b"app", "classes2.dex": b"library"})

    def test_bundletool_download_does_not_follow_a_preexisting_temp_symlink(self):
        from builder import aab

        cache_dir = os.path.join(self.tempdir.name, "cache")
        out_dir = os.path.join(cache_dir, "bundletool")
        os.makedirs(out_dir)
        external_file = os.path.join(self.tempdir.name, "outside")
        with open(external_file, "wb") as target:
            target.write(b"keep")
        tmp_path = os.path.join(out_dir, f"bundletool-all-{aab._BUNDLETOOL_VERSION}.jar.tmp")
        os.symlink(external_file, tmp_path)
        response = SimpleNamespace(
            status_code=200,
            raise_for_status=lambda: None,
            iter_content=lambda size: [b"jar-bytes"],
            url=aab._BUNDLETOOL_URL,
            close=lambda: None,
        )

        with patch("builder.aab.find_bin", return_value="java"), patch(
            "builder.aab.requests.get", return_value=response
        ), patch("builder.aab._BUNDLETOOL_SHA256", aab.hashlib.sha256(b"jar-bytes").hexdigest()):
            command = aab._download_bundletool(SimpleNamespace(cache_dir=cache_dir))

        self.assertEqual(command[:2], ["java", "-jar"])
        with open(external_file, "rb") as target:
            self.assertEqual(target.read(), b"keep")
        with open(command[2], "rb") as downloaded:
            self.assertEqual(downloaded.read(), b"jar-bytes")

    def test_bundletool_download_rejects_a_checksum_mismatch(self):
        from builder import aab

        cache_dir = os.path.join(self.tempdir.name, "cache")
        response = SimpleNamespace(
            status_code=200,
            raise_for_status=lambda: None,
            iter_content=lambda size: [b"unexpected bytes"],
            url=aab._BUNDLETOOL_URL,
            close=lambda: None,
        )
        with patch("builder.aab.find_bin", return_value="java"), patch(
            "builder.aab.requests.get", return_value=response
        ), patch("builder.aab._BUNDLETOOL_SHA256", "0" * 64):
            with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
                aab._download_bundletool(SimpleNamespace(cache_dir=cache_dir))

        out_dir = os.path.join(cache_dir, "bundletool")
        self.assertEqual(os.listdir(out_dir), [])

    def test_bundletool_rejects_redirect_before_contacting_untrusted_origin(self):
        from builder import aab
        response = SimpleNamespace(status_code=302, headers={'Location': 'https://example.invalid/private'},
            url=aab._BUNDLETOOL_URL, iter_content=lambda size: [b'jar'],
            raise_for_status=lambda: None, close=Mock())
        with patch('builder.aab.find_bin', return_value='java'), patch(
            'builder.aab.requests.get', return_value=response
        ) as get:
            with self.assertRaisesRegex(RuntimeError, 'trusted HTTPS'):
                aab._download_bundletool(SimpleNamespace(cache_dir=self.tempdir.name))
        get.assert_called_once()
        self.assertFalse(get.call_args.kwargs['allow_redirects'])
        response.close.assert_called_once()

    def test_bundletool_download_size_failure_preserves_existing_cache(self):
        from builder import aab
        directory = os.path.join(self.tempdir.name, 'bundletool')
        os.makedirs(directory)
        cached = os.path.join(directory, 'bundletool-all-' + aab._BUNDLETOOL_VERSION + '.jar')
        Path(cached).write_bytes(b'keep')
        response = SimpleNamespace(status_code=200, url=aab._BUNDLETOOL_URL,
            raise_for_status=lambda: None, iter_content=lambda size: [b'123', b'45'], close=Mock())
        with patch('builder.aab.find_bin', return_value='java'), patch(
            'builder.aab.requests.get', return_value=response
        ), patch('builder.aab._BUNDLETOOL_MAX_BYTES', 4):
            with self.assertRaisesRegex(RuntimeError, 'size limit'):
                aab._download_bundletool(SimpleNamespace(cache_dir=self.tempdir.name))
        self.assertEqual(Path(cached).read_bytes(), b'keep')
        self.assertEqual(os.listdir(directory), [os.path.basename(cached)])
        response.close.assert_called_once()

    def test_bundletool_redirect_policy_rejects_ambiguous_urls(self):
        from builder import aab
        for location in ('http://github.com/file', 'https://user:pass@github.com/file',
                'https://@github.com/file', 'https://:@github.com/file',
                'https://github.com:8443/file', 'https://github.com/file#fragment', 'https://[invalid'):
            with self.subTest(location=location):
                response = SimpleNamespace(status_code=302, headers={'Location': location},
                    raise_for_status=lambda: None, close=Mock())
                with patch('builder.aab.find_bin', return_value='java'), patch(
                    'builder.aab.requests.get', return_value=response
                ) as get:
                    with self.assertRaises(RuntimeError):
                        aab._download_bundletool(SimpleNamespace(cache_dir=self.tempdir.name))
                get.assert_called_once()
                self.assertFalse(get.call_args.kwargs['allow_redirects'])
                response.close.assert_called_once()

    def test_bundletool_authorized_redirect_downloads_and_closes_responses(self):
        from builder import aab
        redirected = SimpleNamespace(status_code=302,
            headers={'Location': 'https://release-assets.githubusercontent.com/file?token=temporary'},
            raise_for_status=lambda: None, close=Mock())
        downloaded = SimpleNamespace(status_code=200, url='https://release-assets.githubusercontent.com/file',
            raise_for_status=lambda: None, iter_content=lambda size: [b'jar'], close=Mock())
        with patch('builder.aab.find_bin', return_value='java'), patch(
            'builder.aab.requests.get', side_effect=[redirected, downloaded]
        ) as get, patch('builder.aab._BUNDLETOOL_SHA256', aab.hashlib.sha256(b'jar').hexdigest()):
            command = aab._download_bundletool(SimpleNamespace(cache_dir=self.tempdir.name))
        self.assertEqual(Path(command[-1]).read_bytes(), b'jar')
        self.assertEqual(get.call_count, 2)
        self.assertTrue(all(not call.kwargs['allow_redirects'] for call in get.call_args_list))
        redirected.close.assert_called_once()
        downloaded.close.assert_called_once()

    def test_bundletool_network_error_does_not_expose_signed_url(self):
        from builder import aab
        import traceback
        token = 'SECRET_SIGNED_QUERY'
        with patch('builder.aab.find_bin', return_value='java'), patch(
            'builder.aab.requests.get', side_effect=aab.requests.ConnectionError('https://release-assets.githubusercontent.com/file?token=' + token)
        ):
            try:
                aab._download_bundletool(SimpleNamespace(cache_dir=self.tempdir.name))
            except RuntimeError:
                self.assertNotIn(token, traceback.format_exc())
            else:
                self.fail('Expected an explicit network failure')

    def test_bundletool_redirect_limit_closes_every_response(self):
        from builder import aab
        responses = [SimpleNamespace(status_code=302, headers={'Location': aab._BUNDLETOOL_URL},
            raise_for_status=lambda: None, close=Mock()) for _ in range(6)]
        with patch('builder.aab.find_bin', return_value='java'), patch(
            'builder.aab.requests.get', side_effect=responses
        ) as get:
            with self.assertRaisesRegex(RuntimeError, 'five redirects'):
                aab._download_bundletool(SimpleNamespace(cache_dir=self.tempdir.name))
        self.assertEqual(get.call_count, 6)
        for response in responses:
            response.close.assert_called_once()

    def test_bundletool_download_rejects_an_insecure_redirect(self):
        from builder import aab

        cache_dir = os.path.join(self.tempdir.name, "cache")
        response = SimpleNamespace(
            status_code=200,
            raise_for_status=lambda: None,
            iter_content=lambda size: [b"unexpected bytes"],
            url="http://release-assets.githubusercontent.com/bundletool.jar",
            close=lambda: None,
        )
        with patch("builder.aab.find_bin", return_value="java"), patch(
            "builder.aab.requests.get", return_value=response
        ):
            with self.assertRaisesRegex(RuntimeError, "redirected outside trusted HTTPS hosts"):
                aab._download_bundletool(SimpleNamespace(cache_dir=cache_dir))

        self.assertEqual(os.listdir(os.path.join(cache_dir, "bundletool")), [])

    def test_cached_bundletool_checksum_is_checked_before_execution(self):
        from builder import aab

        cache_dir = os.path.join(self.tempdir.name, "cache")
        out_dir = os.path.join(cache_dir, "bundletool")
        os.makedirs(out_dir)
        cached = os.path.join(out_dir, f"bundletool-all-{aab._BUNDLETOOL_VERSION}.jar")
        with open(cached, "wb") as jar:
            jar.write(b"unexpected bytes")

        with patch("builder.aab.find_bin", side_effect=[None, "java"]), patch(
            "builder.aab._BUNDLETOOL_SHA256", "0" * 64
        ):
            with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
                aab._find_bundletool(SimpleNamespace(cache_dir=cache_dir))

    def test_bundle_module_zip_is_stable_across_source_mtime_changes(self):
        from builder.aab import _zip_directory

        source_dir = os.path.join(self.tempdir.name, "module")
        os.makedirs(source_dir)
        for name, content in (("z.txt", b"z"), ("a.txt", b"a")):
            with open(os.path.join(source_dir, name), "wb") as item:
                item.write(content)
        first_zip = os.path.join(self.tempdir.name, "first.zip")
        second_zip = os.path.join(self.tempdir.name, "second.zip")
        _zip_directory(source_dir, first_zip)
        os.utime(os.path.join(source_dir, "a.txt"), (1_700_000_000, 1_700_000_000))
        _zip_directory(source_dir, second_zip)

        with open(first_zip, "rb") as first, open(second_zip, "rb") as second:
            self.assertEqual(first.read(), second.read())
        with zipfile.ZipFile(first_zip) as archive:
            self.assertEqual(archive.namelist(), ["a.txt", "z.txt"])
            self.assertTrue(all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist()))


@unittest.skipUnless(all(shutil.which(tool) for tool in ('java', 'keytool', 'jarsigner', 'javac')), 'Real JDK signing tools required')
class AabSignatureCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from builder.aab import _sign_aab
        cls.tempdir = tempfile.TemporaryDirectory(prefix='termux-builder-signature-coverage-')
        cls.addClassCleanup(cls.tempdir.cleanup)
        cls.root = Path(cls.tempdir.name)
        cls.signed = cls.root / 'signed.aab'
        password = secrets.token_hex(16)
        environment = dict(os.environ, TB_FIXTURE_PASSWORD=password)
        keystore = cls.root / 'fixture.p12'
        subprocess.run(['keytool', '-genkeypair', '-noprompt', '-keystore', str(keystore),
            '-storepass:env', 'TB_FIXTURE_PASSWORD', '-alias', 'fixture', '-dname', 'CN=Signing Coverage',
            '-keyalg', 'RSA', '-keysize', '2048', '-validity', '2'],
            env=environment, check=True, capture_output=True)
        with zipfile.ZipFile(cls.signed, 'w') as archive:
            for name in ('BundleConfig.pb', 'base/manifest/AndroidManifest.xml', 'base/resources.pb',
                         'base/assets/signed-payload.txt', 'META-INF/signed-payload.txt'):
                archive.writestr(name, b'signed fixture payload')
            archive.writestr('base/assets/', b'')
        cls.config = SimpleNamespace(keystore_path=str(keystore), keystore_alias='fixture',
            keystore_store_pass=password, keystore_key_pass=password)
        _sign_aab(cls.config, str(cls.signed))

    def test_embedded_signature_file_cannot_authenticate_changed_external_sf(self):
        from builder.aab import _verify_aab
        internal = self.root / 'embedded-sf.aab'
        shutil.copyfile(self.signed, internal)
        subprocess.run(['jarsigner', '-internalsf', '-keystore', self.config.keystore_path,
            '-storepass:env', 'TB_FIXTURE_PASSWORD', '-digestalg', 'SHA-256', str(internal), 'fixture'],
            env=dict(os.environ, TB_FIXTURE_PASSWORD=self.config.keystore_store_pass),
            check=True, capture_output=True)
        altered = self.root / 'changed-external-sf.aab'
        with zipfile.ZipFile(internal) as source, zipfile.ZipFile(altered, 'w') as archive:
            for member in source.infolist():
                data = source.read(member)
                if member.filename == 'META-INF/FIXTURE.SF':
                    data += b'Name: unused\r\nUnsigned-Payload: tampered\r\n\r\n'
                archive.writestr(member, data)
        with self.assertRaisesRegex(RuntimeError, 'embedded signature files are unsupported'):
            _verify_aab(str(altered))

    def hide_entry_contents(self, path, name, declared_size=0):
        with zipfile.ZipFile(path) as archive:
            member = archive.getinfo(name)
            local = member.header_offset
            central = archive.start_dir
            with archive.open(member) as content:
                checksum = zlib.crc32(content.read(declared_size))
        data = bytearray(path.read_bytes())
        while data[central:central + 4] == b'PK\x01\x02':
            name_size, extra_size, comment_size = struct.unpack_from('<HHH', data, central + 28)
            if data[central + 46:central + 46 + name_size] == name.encode():
                break
            central += 46 + name_size + extra_size + comment_size
        self.assertEqual(data[central + 46:central + 46 + name_size], name.encode())
        struct.pack_into('<I', data, local + 14, checksum)
        struct.pack_into('<I', data, local + 22, declared_size)
        struct.pack_into('<I', data, central + 16, checksum)
        struct.pack_into('<I', data, central + 24, declared_size)
        path.write_bytes(data)

    def test_directory_payload_hidden_by_zero_size_and_crc_is_rejected(self):
        from builder.aab import _verify_aab, run as actual_run
        for name in ('base/assets/hidden/', 'META-INF/hidden/'):
            with self.subTest(name=name):
                altered = self.root / 'hidden-directory-payload.aab'
                shutil.copyfile(self.signed, altered)
                with zipfile.ZipFile(altered, 'a', compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr(name, b'unsigned directory payload')
                self.hide_entry_contents(altered, name)
                with zipfile.ZipFile(altered) as archive:
                    self.assertEqual(archive.getinfo(name).file_size, 0)
                    self.assertEqual(archive.getinfo(name).CRC, 0)
                    self.assertIsNone(archive.testzip())
                with patch('builder.aab.run', wraps=actual_run) as execute:
                    with self.assertRaisesRegex(RuntimeError, 'directory entries must be empty'):
                        _verify_aab(str(altered))
                    self.assertEqual(execute.call_count, 1)
                    self.assertIn('--source', execute.call_args.args[0])

    def test_self_signed_bundle_with_signed_meta_inf_payload_is_accepted(self):
        from builder.aab import _verify_aab
        _verify_aab(str(self.signed))

    def test_appended_unsigned_payload_is_rejected(self):
        from builder.aab import _verify_aab
        for name in ('base/assets/unsigned.txt', 'META-INF/unsigned.txt',
                     'base/assets/unsigned/', 'META-INF/unsigned/'):
            with self.subTest(name=name):
                altered = self.root / 'unsigned.aab'
                shutil.copyfile(self.signed, altered)
                with zipfile.ZipFile(altered, 'a') as archive:
                    archive.writestr(name, b'unsigned fixture payload')
                with self.assertRaisesRegex(RuntimeError, 'signature.*(verification|coverage).*failed'):
                    _verify_aab(str(altered))

    def test_changed_signed_entries_are_rejected_after_crc_is_recomputed(self):
        from builder.aab import _verify_aab
        for name in ('base/resources.pb', 'META-INF/signed-payload.txt', 'META-INF/MANIFEST.MF',
                     'META-INF/FIXTURE.SF', 'META-INF/FIXTURE.RSA'):
            with self.subTest(name=name):
                altered = self.root / 'changed.aab'
                with zipfile.ZipFile(self.signed) as source, zipfile.ZipFile(altered, 'w') as archive:
                    for member in source.infolist():
                        archive.writestr(member, b'changed fixture payload' if member.filename == name
                                         else source.read(member))
                with self.assertRaisesRegex(RuntimeError, 'signature.*(verification|coverage).*failed'):
                    _verify_aab(str(altered))

    def test_appended_signature_metadata_payload_is_rejected(self):
        from builder.aab import _verify_aab
        for names in (('META-INF/UNSIGNED.SF',), ('META-INF/UNSIGNED.RSA',),
                      ('META-INF/UNSIGNED.DSA',), ('META-INF/UNSIGNED.EC',),
                      ('META-INF/SIG-UNSIGNED',), ('META-INF/manifest.mf',),
                      ('META-INF/UNSIGNED.SF', 'META-INF/UNSIGNED.RSA')):
            with self.subTest(names=names):
                altered = self.root / 'unsigned-metadata.aab'
                shutil.copyfile(self.signed, altered)
                with zipfile.ZipFile(altered, 'a') as archive:
                    for name in names:
                        archive.writestr(name, b'unsigned fixture payload')
                with self.assertRaisesRegex(RuntimeError, 'signature.*(verification|coverage).*failed'):
                    _verify_aab(str(altered))

    def test_unsigned_sections_appended_to_signed_manifest_are_rejected(self):
        from builder.aab import _verify_aab
        altered = self.root / 'manifest-unsigned-section.aab'
        with zipfile.ZipFile(self.signed) as source, zipfile.ZipFile(altered, 'w') as archive:
            for member in source.infolist():
                data = source.read(member)
                if member.filename == 'META-INF/MANIFEST.MF':
                    data += b'Name: unsigned-metadata-payload\r\nX-Payload: malicious\r\n\r\n'
                archive.writestr(member, data)
        with self.assertRaisesRegex(RuntimeError, 'signature.*(verification|coverage).*failed'):
            _verify_aab(str(altered))

    def test_unsigned_bytes_appended_to_genuine_signature_block_are_rejected(self):
        from builder.aab import _verify_aab
        altered = self.root / 'block-unsigned-bytes.aab'
        with zipfile.ZipFile(self.signed) as source, zipfile.ZipFile(altered, 'w') as archive:
            for member in source.infolist():
                data = source.read(member)
                if member.filename == 'META-INF/FIXTURE.RSA':
                    data += b'arbitrary unsigned payload'
                archive.writestr(member, data)
        with self.assertRaisesRegex(RuntimeError, 'signature.*(verification|coverage).*failed'):
            _verify_aab(str(altered))

    def test_removed_signed_payload_is_rejected(self):
        from builder.aab import _verify_aab
        for name in ('base/assets/signed-payload.txt', 'META-INF/signed-payload.txt'):
            with self.subTest(name=name):
                altered = self.root / 'removed-payload.aab'
                with zipfile.ZipFile(self.signed) as source, zipfile.ZipFile(altered, 'w') as archive:
                    for member in source.infolist():
                        if member.filename != name:
                            archive.writestr(member, source.read(member))
                with self.assertRaisesRegex(RuntimeError, 'signature.*(verification|coverage).*failed'):
                    _verify_aab(str(altered))

    def test_oversized_signature_metadata_is_rejected_with_size_diagnostic(self):
        from builder.aab import _verify_aab
        altered = self.root / 'oversized-metadata.aab'
        with zipfile.ZipFile(self.signed) as source, zipfile.ZipFile(altered, 'w') as archive:
            for member in source.infolist():
                data = source.read(member)
                if member.filename == 'META-INF/FIXTURE.RSA':
                    data += b'x' * (16 * 1024 * 1024)
                archive.writestr(member, data)
        with self.assertRaisesRegex(RuntimeError, 'signature metadata exceeds 16 MiB limit'):
            _verify_aab(str(altered))

    def test_actual_metadata_size_is_bounded_when_zip_declares_small_size(self):
        from builder.aab import _verify_aab, run as actual_run
        altered = self.root / 'hidden-metadata-size.aab'
        shutil.copyfile(self.signed, altered)
        with zipfile.ZipFile(altered, 'a', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('META-INF/PAYLOAD.RSA', b'x' * (16 * 1024 * 1024 + 1))
        self.hide_entry_contents(altered, 'META-INF/PAYLOAD.RSA', declared_size=65536)
        with zipfile.ZipFile(altered) as archive:
            self.assertEqual(archive.getinfo('META-INF/PAYLOAD.RSA').file_size, 65536)
            self.assertIsNone(archive.testzip())
        with patch('builder.aab.run', wraps=actual_run) as execute:
            with self.assertRaisesRegex(RuntimeError, 'signature metadata exceeds 16 MiB limit'):
                _verify_aab(str(altered))
            self.assertEqual(execute.call_count, 1)
            self.assertIn('--source', execute.call_args.args[0])

    def test_aggregate_signature_metadata_size_is_bounded_before_verification(self):
        from builder.aab import _verify_aab, run as actual_run
        altered = self.root / 'aggregate-metadata.aab'
        shutil.copyfile(self.signed, altered)
        with zipfile.ZipFile(altered, 'a', compression=zipfile.ZIP_DEFLATED) as archive:
            for index in range(5):
                with archive.open('META-INF/EXTRA' + str(index) + '.SF', 'w') as entry:
                    for _ in range(13):
                        entry.write(b'x' * (1024 * 1024))
        with patch('builder.aab.run', wraps=actual_run) as execute:
            with self.assertRaisesRegex(RuntimeError, 'total signature metadata exceeds 64 MiB limit'):
                _verify_aab(str(altered))
            self.assertEqual(execute.call_count, 1)
            self.assertIn('--source', execute.call_args.args[0])


class AabSigningKeyCompatibilityTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('keytool') and shutil.which('jarsigner'), 'Real JDK signing tools required')
    def test_rsa_and_ec_keys_produce_verified_jar_signatures(self):
        from builder.aab import _sign_aab, _verify_aab
        for algorithm in ('RSA', 'EC'):
            with self.subTest(algorithm=algorithm), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                password = secrets.token_hex(16)
                environment = os.environ.copy()
                environment['TB_FIXTURE_PASSWORD'] = password
                keystore = root / 'fixture.p12'
                subprocess.run(['keytool', '-genkeypair', '-keystore', str(keystore),
                    '-storepass:env', 'TB_FIXTURE_PASSWORD', '-keypass:env', 'TB_FIXTURE_PASSWORD',
                    '-alias', 'fixture', '-dname', 'CN=Signing Fixture', '-keyalg', algorithm, '-validity', '1'],
                    env=environment, check=True, capture_output=True)
                artifact = root / 'fixture.aab'
                with zipfile.ZipFile(artifact, 'w') as archive:
                    archive.writestr('payload.txt', b'unchanged payload')
                    for name in ('BundleConfig.pb', 'base/manifest/AndroidManifest.xml', 'base/resources.pb'):
                        archive.writestr(name, b'signed fixture payload')
                config = SimpleNamespace(keystore_path=str(keystore), keystore_alias='fixture',
                    keystore_store_pass=password, keystore_key_pass=password)
                _sign_aab(config, str(artifact))
                verified = subprocess.run(['jarsigner', '-J-Duser.language=en', '-verify', str(artifact)],
                    check=True, capture_output=True, text=True)
                self.assertIn('jar verified.', verified.stdout)
                _verify_aab(str(artifact))
                with zipfile.ZipFile(artifact) as archive:
                    self.assertEqual(archive.read('payload.txt'), b'unchanged payload')
                    self.assertIn('META-INF/FIXTURE.SF', archive.namelist())
                    self.assertIn('META-INF/FIXTURE.' + ('RSA' if algorithm == 'RSA' else 'EC'), archive.namelist())


if __name__ == "__main__":
    unittest.main()
