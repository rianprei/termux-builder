import argparse
import os
import stat
import sys
import tempfile
import unittest
import zipfile
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

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
            abi_splits=False,
        )
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
            _verify_aab(aab_path)
            self.assertIn("-verify", run.call_args.args[0])

            run.return_value.stdout = "jar is unsigned."
            with self.assertRaisesRegex(RuntimeError, "signature verification failed"):
                _verify_aab(aab_path)

        with zipfile.ZipFile(aab_path, "w") as bundle:
            bundle.writestr("BundleConfig.pb", "valid")
        with self.assertRaisesRegex(RuntimeError, "missing required entries"):
            _verify_aab(aab_path)

    def test_bundle_build_verifies_the_signed_output(self):
        from builder.aab import build_bundle

        self.config.cache_dir = os.path.join(self.tempdir.name, "cache")
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

        sign.assert_called_once_with(self.config, aab_path)
        verify.assert_called_once_with(aab_path)


if __name__ == "__main__":
    unittest.main()
