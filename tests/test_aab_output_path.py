import os
import tempfile
import unittest
from types import SimpleNamespace

from builder.aab import _bundle_output_path


class AabOutputPathTests(unittest.TestCase):
    def test_aab_output_path_stays_inside_build_directory(self):
        with tempfile.TemporaryDirectory() as tempdir:
            build_dir = os.path.join(tempdir, ".build")
            config = SimpleNamespace(
                build_dir=build_dir,
                name="sample",
                build_type="debug",
                flavor="free",
            )
            self.assertEqual(
                _bundle_output_path(config),
                os.path.join(build_dir, "sample-free-debug.aab"),
            )

    def test_aab_output_path_rejects_project_and_flavor_traversal(self):
        with tempfile.TemporaryDirectory() as tempdir:
            build_dir = os.path.join(tempdir, ".build")
            for name, flavor in (("../../outside", None), ("sample", "../../outside"), ("..\\outside", None)):
                config = SimpleNamespace(
                    build_dir=build_dir,
                    name=name,
                    build_type="debug",
                    flavor=flavor,
                )
                with self.subTest(name=name, flavor=flavor):
                    with self.assertRaisesRegex(ValueError, "AAB output name"):
                        _bundle_output_path(config)


if __name__ == "__main__":
    unittest.main()
