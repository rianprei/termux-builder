import os
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from builder.signer import sign_apk


class ApkSigningTests(unittest.TestCase):
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
            self.assertEqual(run.call_args_list[1].args[0], ["apksigner", "verify", signed])

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


if __name__ == "__main__":
    unittest.main()
