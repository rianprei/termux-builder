import os
import tempfile
import unittest
from unittest.mock import patch

from builder.config import Config


class ConfigSecretReferenceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(prefix="termux-builder-config-")
        self.addCleanup(self.tempdir.cleanup)
        with open(os.path.join(self.tempdir.name, "AndroidManifest.xml"), "w") as manifest:
            manifest.write('<manifest package="com.example.sample"/>')
        with open(os.path.join(self.tempdir.name, "project.yml"), "w") as config:
            config.write(
                'name: sample\n'
                'android:\n'
                '  target-sdk: 34\n'
                '  min-sdk: 21\n'
                '  manifest-path: AndroidManifest.xml\n'
                '  keystore-store-pass: "env:TB_TEST_STORE_PASS"\n'
                '  keystore-key-pass: "env:TB_TEST_KEY_PASS"\n'
            )

    def test_config_resolves_password_environment_references(self):
        with patch.dict(
            os.environ,
            {"TB_TEST_STORE_PASS": "store-secret", "TB_TEST_KEY_PASS": "key-secret"},
        ):
            config = Config(self.tempdir.name)

        self.assertEqual(config.keystore_store_pass, "store-secret")
        self.assertEqual(config.keystore_key_pass, "key-secret")

    def test_missing_password_environment_reference_fails_without_revealing_secret(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "TB_TEST_STORE_PASS"):
                Config(self.tempdir.name)


if __name__ == "__main__":
    unittest.main()
