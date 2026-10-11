import os
import hashlib
import tempfile
import unittest
import zipfile
from types import SimpleNamespace

from builder.packager import package
from pathlib import Path
from unittest.mock import patch


class ProcessorResourceTests(unittest.TestCase):
    def test_processor_resource_collision_recovers_without_stale_staging(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'bin').mkdir()
            (root / 'dex').mkdir()
            for directory in ('kapt/classes', 'ksp/resources'):
                output = root / directory
                output.mkdir(parents=True)
                (output / 'shared.txt').write_bytes(b'shared')
            (root / 'dex/classes.dex').write_bytes(b'dex')
            previous = root / 'bin/unsigned.apk'
            previous.write_bytes(b'previous')
            with zipfile.ZipFile(root / 'bin/gen.apk.res', 'w') as archive:
                archive.writestr('AndroidManifest.xml', b'manifest')
            config = SimpleNamespace(build_dir=temp, bin_dir=str(root / 'bin'),
                dex_dir=str(root / 'dex'), kapt_enabled=True, ksp_enabled=True,
                find_native_libs=lambda: [])
            with self.assertRaisesRegex(RuntimeError, 'Duplicate APK entry: shared.txt'):
                package(config)
            self.assertEqual(previous.read_bytes(), b'previous')
            self.assertEqual(list((root / 'bin').glob('.unsigned-*')), [])
            from builder.aab import _prepare_base_module
            proto = root / 'proto.apk'
            with zipfile.ZipFile(proto, 'w') as archive:
                archive.writestr('AndroidManifest.xml', b'manifest')
                archive.writestr('resources.pb', b'resources')
            base = root / 'bundle/base'
            with self.assertRaisesRegex(RuntimeError, 'Duplicate AAB processor resource: shared.txt'):
                _prepare_base_module(config, str(base), str(proto))
            (root / 'ksp/resources/shared.txt').unlink()
            with zipfile.ZipFile(package(config)) as archive:
                self.assertEqual(archive.read('shared.txt'), b'shared')
                self.assertEqual(archive.namelist().count('shared.txt'), 1)
                self.assertIsNone(archive.testzip())
            self.assertEqual(list((root / 'bin').glob('.unsigned-*')), [])
            _prepare_base_module(config, str(base), str(proto))
            self.assertEqual((base / 'root/shared.txt').read_bytes(), b'shared')

    def test_resource_scan_failure_preserves_previous_apk(self):
        for processor, output_dir in [("kapt", "kapt/classes"), ("ksp", "ksp/resources")]:
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root / 'bin').mkdir()
                (root / 'dex').mkdir()
                resources = root / output_dir
                resources.mkdir(parents=True)
                (root / 'dex/classes.dex').write_bytes(b'dex')
                previous = root / 'bin/unsigned.apk'
                previous.write_bytes(b'previous')
                with zipfile.ZipFile(root / 'bin/gen.apk.res', 'w') as archive:
                    archive.writestr('AndroidManifest.xml', b'manifest')
                config = SimpleNamespace(build_dir=temp, bin_dir=str(root / 'bin'),
                    dex_dir=str(root / 'dex'), kapt_enabled=processor == "kapt", ksp_enabled=processor == "ksp", find_native_libs=lambda: [])
                original_scandir = os.scandir
                def scan(path):
                    if os.fspath(path) == str(resources):
                        raise PermissionError('resource directory inaccessible')
                    return original_scandir(path)
                with patch('os.scandir', side_effect=scan):
                    with self.assertRaisesRegex(RuntimeError, 'Cannot read ' + processor.upper() + ' resources'):
                        package(config)
                self.assertEqual(previous.read_bytes(), b'previous')

    def test_unsafe_or_conflicting_resources_preserve_previous_apk(self):
        for processor, output_dir in [("kapt", "kapt/classes"), ("ksp", "ksp/resources")]:
            for kind in ('symlink', 'directory-symlink', 'reserved', 'signature', 'conflict', 'backslash', 'root-file', 'fifo'):
                with self.subTest(processor=processor, kind=kind), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    (root / 'bin').mkdir()
                    (root / 'dex').mkdir()
                    resources = root / output_dir
                    resources.mkdir(parents=True)
                    (root / 'dex/classes.dex').write_bytes(b'dex')
                    previous = root / 'bin/unsigned.apk'
                    previous.write_bytes(b'previous')
                    names = {'reserved': 'AndroidManifest.xml', 'signature': 'META-INF/CERT.RSA', 'backslash': 'bad\\name'}
                    resource = resources / names.get(kind, 'data.txt')
                    resource.parent.mkdir(parents=True, exist_ok=True)
                    if kind == 'root-file':
                        resources.rmdir()
                        resources.write_bytes(b'invalid directory')
                    elif kind == 'fifo':
                        os.mkfifo(resource)
                    elif kind in ('symlink', 'directory-symlink'):
                        outside = root / 'outside'
                        if kind == 'directory-symlink':
                            outside.mkdir()
                            (outside / 'data.txt').write_bytes(b'outside')
                            resource.symlink_to(outside, target_is_directory=True)
                        else:
                            outside.write_bytes(b'outside')
                            resource.symlink_to(outside)
                    else:
                        resource.write_bytes(b'resource')
                    with zipfile.ZipFile(root / 'bin/gen.apk.res', 'w') as archive:
                        archive.writestr('AndroidManifest.xml', b'manifest')
                        if kind == 'conflict':
                            archive.writestr('data.txt', b'existing')
                    config = SimpleNamespace(build_dir=temp, bin_dir=str(root / 'bin'),
                        dex_dir=str(root / 'dex'), kapt_enabled=processor == "kapt", ksp_enabled=processor == "ksp", find_native_libs=lambda: [])
                    with self.assertRaises((ValueError, RuntimeError)):
                        package(config)
                    self.assertEqual(previous.read_bytes(), b'previous')

    def test_processor_resources_reach_apk_and_aab_without_bytecode(self):
        for kind, output_dir in [('kapt', 'kapt/classes'), ('ksp', 'ksp/resources')]:
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root / 'bin').mkdir()
                (root / 'dex').mkdir()
                resource = root / output_dir / 'META-INF/services/example.Service'
                resource.parent.mkdir(parents=True)
                resource.write_text('example.Generated\n')
                (root / output_dir / 'Generated.class').write_bytes(b'bytecode')
                (root / 'dex/classes.dex').write_bytes(b'dex')
                with zipfile.ZipFile(root / 'bin/gen.apk.res', 'w') as archive:
                    archive.writestr('AndroidManifest.xml', b'manifest')
                config = SimpleNamespace(build_dir=temp, bin_dir=str(root / 'bin'),
                    dex_dir=str(root / 'dex'), kapt_enabled=kind == 'kapt', ksp_enabled=kind == 'ksp', find_native_libs=lambda: [])
                apk = Path(package(config))
                first_apk = apk.read_bytes()
                with zipfile.ZipFile(apk) as archive:
                    self.assertEqual(archive.read('META-INF/services/example.Service'), b'example.Generated\n')
                    self.assertNotIn('Generated.class', archive.namelist())
                from builder.aab import _prepare_base_module, _zip_directory
                proto = root / 'proto.apk'
                with zipfile.ZipFile(proto, 'w') as archive:
                    archive.writestr('AndroidManifest.xml', b'manifest')
                    archive.writestr('resources.pb', b'resources')
                base = root / 'bundle/base'
                _prepare_base_module(config, str(base), str(proto))
                self.assertEqual((base / 'root/META-INF/services/example.Service').read_bytes(), b'example.Generated\n')
                module_zip = root / 'base.zip'
                _zip_directory(str(base), str(module_zip))
                first_module = module_zip.read_bytes()
                for source in (resource, root / 'dex/classes.dex'):
                    os.utime(source, (946684800, 946684800))
                self.assertEqual(Path(package(config)).read_bytes(), first_apk)
                _prepare_base_module(config, str(base), str(proto))
                _zip_directory(str(base), str(module_zip))
                self.assertEqual(module_zip.read_bytes(), first_module)

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
