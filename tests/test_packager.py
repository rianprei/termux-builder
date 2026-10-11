import os
import hashlib
import tempfile
import unittest
import zipfile
from types import SimpleNamespace

from builder.packager import package


class PackagerDependencyDexTests(unittest.TestCase):
    def test_apk_packaging_fails_when_selected_library_dex_cache_disappears(self):
        with tempfile.TemporaryDirectory() as tempdir:
            bin_dir = os.path.join(tempdir, "bin")
            dex_dir = os.path.join(tempdir, "dex")
            os.makedirs(bin_dir)
            os.makedirs(dex_dir)
            with zipfile.ZipFile(os.path.join(bin_dir, "gen.apk.res"), "w") as base:
                base.writestr("AndroidManifest.xml", b"manifest")
            with open(os.path.join(dex_dir, "classes.dex"), "wb") as dex:
                dex.write(b"app")
            config = SimpleNamespace(
                bin_dir=bin_dir,
                dex_dir=dex_dir,
                library_dex_dir=os.path.join(tempdir, "removed-cache"),
                find_native_libs=lambda: [],
            )

            with self.assertRaisesRegex(RuntimeError, "disappeared before APK packaging"):
                package(config)

    def test_apk_contains_application_and_library_dex_in_numeric_order(self):
        with tempfile.TemporaryDirectory() as tempdir:
            bin_dir = os.path.join(tempdir, "bin")
            dex_dir = os.path.join(tempdir, "dex")
            library_dex_dir = os.path.join(tempdir, "cache", "library-dex", "fingerprint")
            os.makedirs(bin_dir)
            os.makedirs(dex_dir)
            os.makedirs(os.path.join(library_dex_dir, "lib-0000"))
            with zipfile.ZipFile(os.path.join(bin_dir, "gen.apk.res"), "w") as base:
                base.writestr("AndroidManifest.xml", b"manifest")
            for name, content in (("classes.dex", b"app-1"), ("classes2.dex", b"app-2"), ("classes10.dex", b"app-10")):
                with open(os.path.join(dex_dir, name), "wb") as dex:
                    dex.write(content)
            with open(os.path.join(library_dex_dir, "lib-0000", "classes.dex"), "wb") as dex:
                dex.write(b"library")

            config = SimpleNamespace(
                bin_dir=bin_dir,
                dex_dir=dex_dir,
                library_dex_dir=library_dex_dir,
                find_native_libs=lambda: [],
            )
            apk_path = package(config)

            with zipfile.ZipFile(apk_path) as apk:
                self.assertEqual(
                    [name for name in apk.namelist() if name.endswith(".dex")],
                    ["classes.dex", "classes2.dex", "classes10.dex", "classes4.dex"],
                )
                self.assertEqual(apk.read("classes4.dex"), b"library")

    def test_packager_rejects_unsigned_output_symlink(self):
        with tempfile.TemporaryDirectory() as tempdir:
            bin_dir = os.path.join(tempdir, "bin")
            dex_dir = os.path.join(tempdir, "dex")
            os.makedirs(bin_dir)
            os.makedirs(dex_dir)
            with zipfile.ZipFile(os.path.join(bin_dir, "gen.apk.res"), "w") as base:
                base.writestr("AndroidManifest.xml", b"manifest")
            with open(os.path.join(dex_dir, "classes.dex"), "wb") as dex:
                dex.write(b"app")
            outside = os.path.join(tempdir, "outside.apk")
            with open(outside, "wb") as output:
                output.write(b"keep")
            os.symlink(outside, os.path.join(bin_dir, "unsigned.apk"))
            config = SimpleNamespace(
                build_dir=tempdir,
                bin_dir=bin_dir,
                dex_dir=dex_dir,
                find_native_libs=lambda: [],
            )

            with self.assertRaisesRegex(ValueError, "symlink"):
                package(config)

            with open(outside, "rb") as output:
                self.assertEqual(output.read(), b"keep")

    def test_apk_zip_is_stable_when_input_mtimes_change(self):
        with tempfile.TemporaryDirectory() as tempdir:
            bin_dir = os.path.join(tempdir, "bin")
            dex_dir = os.path.join(tempdir, "dex")
            jni_dir = os.path.join(tempdir, "jni", "arm64-v8a")
            os.makedirs(bin_dir)
            os.makedirs(dex_dir)
            os.makedirs(jni_dir)
            with zipfile.ZipFile(os.path.join(bin_dir, "gen.apk.res"), "w") as base:
                base.writestr("resources.arsc", b"resources")
                base.writestr("AndroidManifest.xml", b"manifest")
            dex_path = os.path.join(dex_dir, "classes.dex")
            native_path = os.path.join(jni_dir, "libsample.so")
            for path, content in ((dex_path, b"app dex"), (native_path, b"native lib")):
                with open(path, "wb") as source:
                    source.write(content)
            config = SimpleNamespace(
                build_dir=tempdir,
                bin_dir=bin_dir,
                dex_dir=dex_dir,
                find_native_libs=lambda: [("arm64-v8a", native_path)],
            )

            apk_path = package(config)
            with open(apk_path, "rb") as apk:
                first_hash = hashlib.sha256(apk.read()).hexdigest()
            os.utime(dex_path, (1_700_000_000, 1_700_000_000))
            os.utime(native_path, (1_600_000_000, 1_600_000_000))
            package(config)
            with open(apk_path, "rb") as apk:
                second_hash = hashlib.sha256(apk.read()).hexdigest()

            self.assertEqual(first_hash, second_hash)


if __name__ == "__main__":
    unittest.main()
