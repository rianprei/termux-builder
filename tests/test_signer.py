import os
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from builder.signer import sign, sign_apk


class ApkSigningTests(unittest.TestCase):
    def test_signer_success_without_output_does_not_publish_empty_staging(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            keystore = os.path.join(temp_dir, 'debug.keystore')
            unsigned = os.path.join(temp_dir, 'unsigned.apk')
            signed = os.path.join(temp_dir, 'signed.apk')
            for path in (keystore, unsigned):
                open(path, 'wb').close()
            with open(signed, 'wb') as previous:
                previous.write(b'previous APK')
            config = SimpleNamespace(keystore_path=keystore,
                keystore_store_pass='fixture', keystore_key_pass='fixture',
                keystore_alias='debug', bin_apksigner='apksigner',
                sign_v1=True, sign_v2=True, sign_v3=True, sign_v4=False)
            with patch('builder.signer.run') as execute:
                with self.assertRaisesRegex(RuntimeError, 'without producing'):
                    sign_apk(config, unsigned, signed)
                self.assertEqual(execute.call_count, 1)
            with open(signed, 'rb') as previous:
                self.assertEqual(previous.read(), b'previous APK')
            self.assertFalse(any(name.startswith('.signed-') for name in os.listdir(temp_dir)))

    def test_signed_apk_is_verified_before_returning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            keystore = os.path.join(temp_dir, "debug.keystore")
            unsigned = os.path.join(temp_dir, "unsigned.apk")
            signed = os.path.join(temp_dir, "signed.apk")
            open(keystore, "wb").close()
            open(unsigned, "wb").close()
            config = SimpleNamespace(
                keystore_path=keystore,
                keystore_store_pass="store-pass",
                keystore_key_pass="key-pass",
                bin_apksigner="apksigner",
                keystore_alias="debug",
                sign_v1=True,
                sign_v2=True,
                sign_v3=True,
                sign_v4=False,
            )

            def fake_run(args, **kwargs):
                if args[1] == "sign":
                    with open(args[args.index("--out") + 1], "wb") as output:
                        output.write(b"signed apk")

            with patch("builder.signer.run", side_effect=fake_run) as run:
                self.assertEqual(sign_apk(config, unsigned, signed), signed)

            self.assertEqual(run.call_count, 2)
            staging_path = run.call_args_list[1].args[0][2]
            self.assertEqual(run.call_args_list[1].args[0], ["apksigner", "verify", staging_path])
            self.assertTrue(os.path.isfile(signed))
            self.assertEqual(os.path.dirname(staging_path), temp_dir)

    def test_sign_apk_accepts_relative_paths_without_build_dir(self):
        original_dir = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                os.chdir(temp_dir)
                open("debug.keystore", "wb").close()
                open("unsigned.apk", "wb").close()
                config = SimpleNamespace(
                    keystore_path="debug.keystore",
                    keystore_store_pass="store-pass",
                    keystore_key_pass="key-pass",
                    bin_apksigner="apksigner",
                    keystore_alias="debug",
                    sign_v1=True,
                    sign_v2=True,
                    sign_v3=True,
                    sign_v4=False,
                )

                def fake_run(args, **kwargs):
                    if args[1] == "sign":
                        staging = args[args.index("--out") + 1]
                        with open(staging, "wb") as output:
                            output.write(b"signed apk")

                with patch("builder.signer.run", side_effect=fake_run):
                    self.assertEqual(
                        sign_apk(config, "unsigned.apk", "signed.apk"), "signed.apk"
                    )
                self.assertTrue(os.path.isfile("signed.apk"))
        finally:
            os.chdir(original_dir)

    def test_v4_sidecar_is_published_with_signed_apk(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            keystore = os.path.join(temp_dir, "debug.keystore")
            unsigned = os.path.join(temp_dir, "unsigned.apk")
            signed = os.path.join(temp_dir, "signed.apk")
            open(keystore, "wb").close()
            open(unsigned, "wb").close()
            config = SimpleNamespace(
                keystore_path=keystore,
                keystore_store_pass="store-pass",
                keystore_key_pass="key-pass",
                bin_apksigner="apksigner",
                keystore_alias="debug",
                sign_v1=True,
                sign_v2=True,
                sign_v3=True,
                sign_v4=True,
            )

            def fake_run(args, **kwargs):
                if args[1] == "sign":
                    staging = args[args.index("--out") + 1]
                    with open(staging, "wb") as output:
                        output.write(b"signed apk")
                    with open(staging + ".idsig", "wb") as output:
                        output.write(b"v4 signature")

            with patch("builder.signer.run", side_effect=fake_run) as run:
                sign_apk(config, unsigned, signed)

            with open(signed + ".idsig", "rb") as signature:
                self.assertEqual(signature.read(), b"v4 signature")
            self.assertEqual(os.path.getsize(signed), len(b"signed apk"))
            staging_path = run.call_args_list[1].args[0][-1]
            self.assertEqual(
                run.call_args_list[1].args[0],
                [
                    "apksigner",
                    "verify",
                    "-v4-signature-file",
                    staging_path + ".idsig",
                    staging_path,
                ],
            )

    def test_signing_without_v4_removes_a_stale_sidecar_after_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            keystore = os.path.join(temp_dir, "debug.keystore")
            unsigned = os.path.join(temp_dir, "unsigned.apk")
            signed = os.path.join(temp_dir, "signed.apk")
            open(keystore, "wb").close()
            open(unsigned, "wb").close()
            with open(signed, "wb") as output:
                output.write(b"previous apk")
            with open(signed + ".idsig", "wb") as output:
                output.write(b"stale signature")
            config = SimpleNamespace(
                keystore_path=keystore,
                keystore_store_pass="store-pass",
                keystore_key_pass="key-pass",
                bin_apksigner="apksigner",
                keystore_alias="debug",
                sign_v1=True,
                sign_v2=True,
                sign_v3=True,
                sign_v4=False,
            )

            def fake_run(args, **kwargs):
                if args[1] == "sign":
                    with open(args[args.index("--out") + 1], "wb") as output:
                        output.write(b"new apk")

            with patch("builder.signer.run", side_effect=fake_run):
                sign_apk(config, unsigned, signed)

            with open(signed, "rb") as output:
                self.assertEqual(output.read(), b"new apk")
            self.assertFalse(os.path.lexists(signed + ".idsig"))
            self.assertEqual(
                sorted(os.listdir(temp_dir)),
                ["debug.keystore", "signed.apk", "unsigned.apk"],
            )

    def test_v4_signing_requires_sidecar_before_replacing_existing_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            keystore = os.path.join(temp_dir, "debug.keystore")
            unsigned = os.path.join(temp_dir, "unsigned.apk")
            signed = os.path.join(temp_dir, "signed.apk")
            open(keystore, "wb").close()
            open(unsigned, "wb").close()
            with open(signed, "wb") as output:
                output.write(b"previous apk")
            with open(signed + ".idsig", "wb") as output:
                output.write(b"previous signature")
            config = SimpleNamespace(
                keystore_path=keystore,
                keystore_store_pass="store-pass",
                keystore_key_pass="key-pass",
                bin_apksigner="apksigner",
                keystore_alias="debug",
                sign_v1=True,
                sign_v2=True,
                sign_v3=True,
                sign_v4=True,
            )

            def fake_run(args, **kwargs):
                if args[1] == "sign":
                    with open(args[args.index("--out") + 1], "wb") as output:
                        output.write(b"incomplete apk")

            with patch("builder.signer.run", side_effect=fake_run):
                with self.assertRaisesRegex(RuntimeError, "v4 signature sidecar"):
                    sign_apk(config, unsigned, signed)

            with open(signed, "rb") as output:
                self.assertEqual(output.read(), b"previous apk")
            with open(signed + ".idsig", "rb") as output:
                self.assertEqual(output.read(), b"previous signature")

    def test_failed_v4_sidecar_publication_restores_previous_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            keystore = os.path.join(temp_dir, "debug.keystore")
            unsigned = os.path.join(temp_dir, "unsigned.apk")
            signed = os.path.join(temp_dir, "signed.apk")
            open(keystore, "wb").close()
            open(unsigned, "wb").close()
            with open(signed, "wb") as output:
                output.write(b"previous apk")
            with open(signed + ".idsig", "wb") as output:
                output.write(b"previous signature")
            config = SimpleNamespace(
                keystore_path=keystore,
                keystore_store_pass="store-pass",
                keystore_key_pass="key-pass",
                bin_apksigner="apksigner",
                keystore_alias="debug",
                sign_v1=True,
                sign_v2=True,
                sign_v3=True,
                sign_v4=True,
            )

            def fake_run(args, **kwargs):
                if args[1] == "sign":
                    staging = args[args.index("--out") + 1]
                    with open(staging, "wb") as output:
                        output.write(b"new apk")
                    with open(staging + ".idsig", "wb") as output:
                        output.write(b"new signature")

            real_replace = os.replace

            def fail_sidecar_publish(source, destination):
                if destination == signed + ".idsig" and source.endswith(".apk.idsig"):
                    raise OSError("injected sidecar publication failure")
                real_replace(source, destination)

            with patch("builder.signer.run", side_effect=fake_run):
                with patch("builder.signer.os.replace", side_effect=fail_sidecar_publish):
                    with self.assertRaisesRegex(OSError, "injected sidecar publication failure"):
                        sign_apk(config, unsigned, signed)

            with open(signed, "rb") as output:
                self.assertEqual(output.read(), b"previous apk")
            with open(signed + ".idsig", "rb") as output:
                self.assertEqual(output.read(), b"previous signature")
            self.assertEqual(
                sorted(os.listdir(temp_dir)),
                ["debug.keystore", "signed.apk", "signed.apk.idsig", "unsigned.apk"],
            )

    def test_v4_signing_rejects_directory_output_before_removing_sidecar(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            keystore = os.path.join(temp_dir, "debug.keystore")
            unsigned = os.path.join(temp_dir, "unsigned.apk")
            signed = os.path.join(temp_dir, "signed.apk")
            open(keystore, "wb").close()
            open(unsigned, "wb").close()
            os.mkdir(signed)
            with open(signed + ".idsig", "wb") as output:
                output.write(b"previous signature")
            config = SimpleNamespace(
                keystore_path=keystore,
                keystore_store_pass="store-pass",
                keystore_key_pass="key-pass",
                bin_apksigner="apksigner",
                keystore_alias="debug",
                sign_v1=True,
                sign_v2=True,
                sign_v3=True,
                sign_v4=True,
            )

            with patch("builder.signer.run") as run:
                with self.assertRaisesRegex(RuntimeError, "Invalid signed APK output path"):
                    sign_apk(config, unsigned, signed)

            run.assert_not_called()
            with open(signed + ".idsig", "rb") as output:
                self.assertEqual(output.read(), b"previous signature")

    def test_interruption_during_output_backup_restores_previous_files(self):
        for interrupted_path in ("apk", "idsig"):
            with self.subTest(interrupted_path=interrupted_path):
                with tempfile.TemporaryDirectory() as temp_dir:
                    keystore = os.path.join(temp_dir, "debug.keystore")
                    unsigned = os.path.join(temp_dir, "unsigned.apk")
                    signed = os.path.join(temp_dir, "signed.apk")
                    open(keystore, "wb").close()
                    open(unsigned, "wb").close()
                    with open(signed, "wb") as output:
                        output.write(b"previous apk")
                    with open(signed + ".idsig", "wb") as output:
                        output.write(b"previous signature")
                    config = SimpleNamespace(
                        keystore_path=keystore,
                        keystore_store_pass="store-pass",
                        keystore_key_pass="key-pass",
                        bin_apksigner="apksigner",
                        keystore_alias="debug",
                        sign_v1=True,
                        sign_v2=True,
                        sign_v3=True,
                        sign_v4=True,
                    )

                    def fake_run(args, **kwargs):
                        if args[1] == "sign":
                            staging = args[args.index("--out") + 1]
                            with open(staging, "wb") as output:
                                output.write(b"new apk")
                            with open(staging + ".idsig", "wb") as output:
                                output.write(b"new signature")

                    interrupt_source = signed if interrupted_path == "apk" else signed + ".idsig"
                    real_replace = os.replace

                    def interrupt_after_backup(source, destination):
                        real_replace(source, destination)
                        if source == interrupt_source:
                            raise KeyboardInterrupt("injected interruption after backup rename")

                    with patch("builder.signer.run", side_effect=fake_run):
                        with patch("builder.signer.os.replace", side_effect=interrupt_after_backup):
                            with self.assertRaisesRegex(KeyboardInterrupt, "after backup rename"):
                                sign_apk(config, unsigned, signed)

                    with open(signed, "rb") as output:
                        self.assertEqual(output.read(), b"previous apk")
                    with open(signed + ".idsig", "rb") as output:
                        self.assertEqual(output.read(), b"previous signature")
                    self.assertEqual(
                        sorted(os.listdir(temp_dir)),
                        ["debug.keystore", "signed.apk", "signed.apk.idsig", "unsigned.apk"],
                    )

    def test_interrupted_sidecar_rollback_still_restores_apk_and_reports_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            keystore = os.path.join(temp_dir, "debug.keystore")
            unsigned = os.path.join(temp_dir, "unsigned.apk")
            signed = os.path.join(temp_dir, "signed.apk")
            idsig = signed + ".idsig"
            open(keystore, "wb").close()
            open(unsigned, "wb").close()
            with open(signed, "wb") as output:
                output.write(b"previous apk")
            with open(idsig, "wb") as output:
                output.write(b"previous signature")
            config = SimpleNamespace(
                keystore_path=keystore,
                keystore_store_pass="store-pass",
                keystore_key_pass="key-pass",
                bin_apksigner="apksigner",
                keystore_alias="debug",
                sign_v1=True,
                sign_v2=True,
                sign_v3=True,
                sign_v4=True,
            )

            def fake_run(args, **kwargs):
                if args[1] == "sign":
                    staging = args[args.index("--out") + 1]
                    with open(staging, "wb") as output:
                        output.write(b"new apk")
                    with open(staging + ".idsig", "wb") as output:
                        output.write(b"new signature")

            real_replace = os.replace

            def fail_publication_and_interrupt_rollback(source, destination):
                if source.endswith(".apk.idsig") and destination == idsig:
                    raise OSError("injected sidecar publication failure")
                if os.path.basename(source).startswith(".previous-") and destination == idsig:
                    raise KeyboardInterrupt("injected sidecar rollback interruption")
                return real_replace(source, destination)

            with patch("builder.signer.run", side_effect=fake_run):
                with patch(
                    "builder.signer.os.replace",
                    side_effect=fail_publication_and_interrupt_rollback,
                ):
                    with self.assertRaisesRegex(RuntimeError, "rollback was incomplete") as raised:
                        sign_apk(config, unsigned, signed)

            with open(signed, "rb") as output:
                self.assertEqual(output.read(), b"previous apk")
            self.assertFalse(os.path.exists(idsig))
            backups = [name for name in os.listdir(temp_dir) if name.endswith(".idsig")]
            self.assertEqual(len(backups), 1)
            backup = os.path.join(temp_dir, backups[0])
            with open(backup, "rb") as output:
                self.assertEqual(output.read(), b"previous signature")
            self.assertIn(backup, str(raised.exception))

    def test_interruption_after_sidecar_restore_rename_keeps_rollback_complete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            keystore = os.path.join(temp_dir, "debug.keystore")
            unsigned = os.path.join(temp_dir, "unsigned.apk")
            signed = os.path.join(temp_dir, "signed.apk")
            idsig = signed + ".idsig"
            open(keystore, "wb").close()
            open(unsigned, "wb").close()
            with open(signed, "wb") as output:
                output.write(b"previous apk")
            with open(idsig, "wb") as output:
                output.write(b"previous signature")
            config = SimpleNamespace(
                keystore_path=keystore,
                keystore_store_pass="store-pass",
                keystore_key_pass="key-pass",
                bin_apksigner="apksigner",
                keystore_alias="debug",
                sign_v1=True,
                sign_v2=True,
                sign_v3=True,
                sign_v4=True,
            )

            def fake_run(args, **kwargs):
                if args[1] == "sign":
                    staging = args[args.index("--out") + 1]
                    with open(staging, "wb") as output:
                        output.write(b"new apk")
                    with open(staging + ".idsig", "wb") as output:
                        output.write(b"new signature")

            real_replace = os.replace

            def interrupt_after_sidecar_restore(source, destination):
                if source.endswith(".apk.idsig") and destination == idsig:
                    raise OSError("injected sidecar publication failure")
                if os.path.basename(source).startswith(".previous-") and destination == idsig:
                    real_replace(source, destination)
                    raise KeyboardInterrupt("injected interruption after sidecar restore")
                return real_replace(source, destination)

            with patch("builder.signer.run", side_effect=fake_run):
                with patch(
                    "builder.signer.os.replace",
                    side_effect=interrupt_after_sidecar_restore,
                ):
                    with self.assertRaisesRegex(OSError, "sidecar publication failure"):
                        sign_apk(config, unsigned, signed)

            with open(signed, "rb") as output:
                self.assertEqual(output.read(), b"previous apk")
            with open(idsig, "rb") as output:
                self.assertEqual(output.read(), b"previous signature")
            self.assertEqual(
                sorted(os.listdir(temp_dir)),
                ["debug.keystore", "signed.apk", "signed.apk.idsig", "unsigned.apk"],
            )

    def test_failed_apk_verification_aborts_the_build(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            keystore = os.path.join(temp_dir, "debug.keystore")
            unsigned = os.path.join(temp_dir, "unsigned.apk")
            signed = os.path.join(temp_dir, "signed.apk")
            open(keystore, "wb").close()
            open(unsigned, "wb").close()
            config = SimpleNamespace(
                keystore_path=keystore,
                keystore_store_pass="store-pass",
                keystore_key_pass="key-pass",
                bin_apksigner="apksigner",
                keystore_alias="debug",
                sign_v1=True,
                sign_v2=True,
                sign_v3=True,
                sign_v4=False,
            )

            def fail_verification(args, **kwargs):
                if args[1] == "sign":
                    with open(args[args.index("--out") + 1], "wb") as output:
                        output.write(b"bad signature")
                else:
                    raise subprocess.CalledProcessError(1, args)

            with patch("builder.signer.run", side_effect=fail_verification):
                with self.assertRaises(subprocess.CalledProcessError):
                    sign_apk(config, unsigned, signed)

    def test_signer_rejects_signed_output_symlink(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            keystore = os.path.join(temp_dir, "debug.keystore")
            unsigned = os.path.join(temp_dir, "unsigned.apk")
            signed = os.path.join(temp_dir, "signed.apk")
            outside = os.path.join(temp_dir, "outside.apk")
            for path in (keystore, unsigned):
                open(path, "wb").close()
            with open(outside, "wb") as output:
                output.write(b"keep")
            os.symlink(outside, signed)
            config = SimpleNamespace(
                build_dir=temp_dir,
                keystore_path=keystore,
                keystore_store_pass="store-pass",
                keystore_key_pass="key-pass",
                bin_apksigner="apksigner",
                keystore_alias="debug",
                sign_v1=True,
                sign_v2=True,
                sign_v3=True,
                sign_v4=False,
            )

            with patch("builder.signer.run") as run:
                with self.assertRaisesRegex(ValueError, "symlink"):
                    sign_apk(config, unsigned, signed)

            run.assert_not_called()
            with open(outside, "rb") as output:
                self.assertEqual(output.read(), b"keep")

    def test_failed_verification_preserves_existing_signed_apk(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            keystore = os.path.join(temp_dir, "debug.keystore")
            unsigned = os.path.join(temp_dir, "unsigned.apk")
            signed = os.path.join(temp_dir, "signed.apk")
            open(keystore, "wb").close()
            open(unsigned, "wb").close()
            with open(signed, "wb") as output:
                output.write(b"previous valid build")
            config = SimpleNamespace(
                build_dir=temp_dir,
                keystore_path=keystore,
                keystore_store_pass="store-pass",
                keystore_key_pass="key-pass",
                bin_apksigner="apksigner",
                keystore_alias="debug",
                sign_v1=True,
                sign_v2=True,
                sign_v3=True,
                sign_v4=False,
            )

            def fail_verification(args, **kwargs):
                if args[1] == "sign":
                    with open(args[args.index("--out") + 1], "wb") as output:
                        output.write(b"bad signature")
                else:
                    raise subprocess.CalledProcessError(1, args)

            with patch("builder.signer.run", side_effect=fail_verification):
                with self.assertRaises(subprocess.CalledProcessError):
                    sign_apk(config, unsigned, signed)

            with open(signed, "rb") as output:
                self.assertEqual(output.read(), b"previous valid build")

    def test_signed_apk_name_includes_flavor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bin_dir = os.path.join(temp_dir, "bin")
            os.makedirs(bin_dir)
            unsigned = os.path.join(bin_dir, "unsigned.apk")
            open(unsigned, "wb").close()
            config = SimpleNamespace(
                build_dir=temp_dir,
                bin_dir=bin_dir,
                name="sample",
                flavor="paid",
                build_type="release",
            )

            with patch("builder.signer.sign_apk", return_value="signed") as sign_apk_mock:
                self.assertEqual(sign(config), "signed")

            self.assertEqual(sign_apk_mock.call_args.args[2], os.path.join(temp_dir, "sample-paid-release.apk"))
            self.assertFalse(os.path.exists(unsigned))


if __name__ == "__main__":
    unittest.main()
