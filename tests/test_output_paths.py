import os
import tempfile
import unittest

from builder.utils import ensure_output_path


class OutputPathTests(unittest.TestCase):
    def test_output_path_rejects_direct_symlink(self):
        with tempfile.TemporaryDirectory() as tempdir:
            build_dir = os.path.join(tempdir, ".build")
            os.makedirs(build_dir)
            target = os.path.join(tempdir, "outside.bin")
            with open(target, "wb") as output:
                output.write(b"preserve")
            link = os.path.join(build_dir, "artifact.bin")
            os.symlink(target, link)

            with self.assertRaisesRegex(ValueError, "symlink"):
                ensure_output_path(build_dir, link, "Artifact output")

    def test_output_path_rejects_parent_symlink_outside_build(self):
        with tempfile.TemporaryDirectory() as tempdir:
            build_dir = os.path.join(tempdir, ".build")
            outside = os.path.join(tempdir, "outside")
            os.makedirs(build_dir)
            os.makedirs(outside)
            os.symlink(outside, os.path.join(build_dir, "redirect"))

            with self.assertRaisesRegex(ValueError, "inside the build directory"):
                ensure_output_path(build_dir, os.path.join(build_dir, "redirect", "artifact.bin"), "Artifact output")

    def test_output_path_allows_new_file_under_build_directory(self):
        with tempfile.TemporaryDirectory() as tempdir:
            build_dir = os.path.join(tempdir, ".build")
            path = os.path.join(build_dir, "bin", "artifact.bin")

            self.assertEqual(ensure_output_path(build_dir, path, "Artifact output"), path)


if __name__ == "__main__":
    unittest.main()
