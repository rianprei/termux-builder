import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from builder import cli


class InitCommandTests(unittest.TestCase):
    def test_absolute_destination_uses_directory_name_in_project_config(self):
        with tempfile.TemporaryDirectory() as tempdir:
            project = Path(tempdir) / "myapp"
            args = ["termux-builder", "init", str(project), "--package", "com.example.myapp"]

            with patch.object(sys, "argv", args), patch("builder.signer.generate_debug_keystore"):
                cli.main()

            config = yaml.safe_load((project / "project.yml").read_text())
            self.assertEqual(config["name"], project.name)

    def test_init_ignores_build_outputs_and_local_credentials(self):
        with tempfile.TemporaryDirectory() as tempdir:
            project = Path(tempdir) / "myapp"
            args = ["termux-builder", "init", str(project), "--package", "com.example.myapp"]

            with patch.object(sys, "argv", args), patch("builder.signer.generate_debug_keystore"):
                cli.main()

            ignored = set((project / ".gitignore").read_text().splitlines())
            self.assertTrue({".build/", ".libs/", ".cache/", ".env", ".env.*"} <= ignored)
            self.assertTrue({"*.keystore", "*.jks", "*.p12", "*.pfx", "*.pem", "*.key"} <= ignored)
            self.assertIn("!.env.example", ignored)


if __name__ == "__main__":
    unittest.main()
