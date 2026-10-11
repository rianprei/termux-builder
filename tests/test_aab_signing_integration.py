import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from types import SimpleNamespace

from builder.aab import _sign_aab, _verify_aab


class AabSigningIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("keytool") and shutil.which("jarsigner"), "JDK signing tools unavailable")
    def test_distinct_passwords_sign_and_verify_bundle(self):
        with tempfile.TemporaryDirectory(prefix="termux-builder-signing-") as tempdir:
            keystore_path = os.path.join(tempdir, "release.keystore")
            aab_path = os.path.join(tempdir, "sample.aab")
            env = os.environ.copy()
            env["_TB_TEST_STORE_PASS"] = "store-secret-123"
            env["_TB_TEST_KEY_PASS"] = "key-secret-456"

            subprocess.run(
                [
                    shutil.which("keytool"),
                    "-genkeypair",
                    "-noprompt",
                    "-keystore", keystore_path,
                    "-storetype", "JKS",
                    "-storepass:env", "_TB_TEST_STORE_PASS",
                    "-keypass:env", "_TB_TEST_KEY_PASS",
                    "-alias", "release",
                    "-keyalg", "RSA",
                    "-keysize", "2048",
                    "-validity", "2",
                    "-dname", "CN=termux-builder-test",
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
            with zipfile.ZipFile(aab_path, "w") as bundle:
                bundle.writestr("BundleConfig.pb", "config")
                bundle.writestr("base/manifest/AndroidManifest.xml", "manifest")
                bundle.writestr("base/resources.pb", "resources")

            config = SimpleNamespace(
                keystore_path=keystore_path,
                keystore_alias="release",
                keystore_store_pass=env["_TB_TEST_STORE_PASS"],
                keystore_key_pass=env["_TB_TEST_KEY_PASS"],
            )
            _sign_aab(config, aab_path)
            _verify_aab(aab_path)

            with zipfile.ZipFile(aab_path) as bundle:
                self.assertTrue(any(name.startswith("META-INF/") and name.endswith(".SF") for name in bundle.namelist()))


if __name__ == "__main__":
    unittest.main()
