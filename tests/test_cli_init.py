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


if __name__ == "__main__":
    unittest.main()
