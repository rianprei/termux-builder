import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from builder import dexer


class D8ToolDetectionTests(unittest.TestCase):
    def test_resolved_d8_path_does_not_require_tool_to_be_on_path(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            d8 = root / "sdk" / "build-tools" / "37.0.0" / "d8"
            d8.parent.mkdir(parents=True)
            d8.write_text("#!/bin/sh\n", encoding="utf-8")
            d8.chmod(0o755)
            path_dir = root / "empty-path"
            path_dir.mkdir()
            config = SimpleNamespace(bin_d8=str(d8))

            with patch.dict(os.environ, {"PATH": str(path_dir)}):
                self.assertTrue(dexer._has_d8(config))


class LibraryDexCacheTests(unittest.TestCase):
    def test_library_dex_cache_is_outside_dependency_and_reused_only_when_valid(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            libs_dir = root / ".libs"
            library_dir = libs_dir / ".termux-builder" / "maven" / "com" / "example" / "runtime-1.0"
            library_dir.mkdir(parents=True)
            jar = library_dir / "runtime-1.0.jar"
            jar.write_bytes(b"library jar")
            android_jar = root / "android.jar"
            android_jar.write_bytes(b"android api")
            d8 = root / "d8"
            d8.write_bytes(b"d8 toolchain")
            cache_root = root / ".cache" / "library-dex"
            cache_root.mkdir(parents=True)
            dead_pid = 2_000_000_000
            while True:
                try:
                    os.kill(dead_pid, 0)
                except ProcessLookupError:
                    break
                dead_pid += 1
            stale_stage = cache_root / f".library-dex-{dead_pid}-orphan"
            stale_stage.mkdir()
            active_stage = cache_root / f".library-dex-{os.getpid()}-active"
            active_stage.mkdir()
            config = SimpleNamespace(
                libs_dir=str(libs_dir),
                cache_dir=str(root / ".cache"),
                build_type="debug",
                min_sdk=21,
                android_jar=str(android_jar),
                bin_d8=str(d8),
                find_lib_jars=lambda: [str(jar)],
            )

            def write_dex(args):
                output_dir = Path(args[args.index("--output") + 1])
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "classes.dex").write_bytes(b"dex output")

            with patch.object(dexer, "run", side_effect=write_dex) as run:
                dexer._dex_libraries(config, use_d8=True)
                run.assert_called_once()
                self.assertTrue(Path(config.library_dex_dir).is_dir())
                self.assertTrue(Path(config.library_dex_dir).is_relative_to(root / ".cache"))
                self.assertFalse(stale_stage.exists())
                self.assertTrue(active_stage.is_dir())
                self.assertFalse((library_dir / "classes.dex").exists())
                self.assertFalse((library_dir / "runtime-1.0.dex").exists())
                cached_dex = next(Path(config.library_dex_dir).rglob("*.dex"))
                self.assertEqual(cached_dex.read_bytes(), b"dex output")

                run.reset_mock()
                dexer._dex_libraries(config, use_d8=True)
                run.assert_not_called()

                cached_dex.write_bytes(b"tampered dex")
                dexer._dex_libraries(config, use_d8=True)
                run.assert_called_once()
                self.assertEqual(cached_dex.read_bytes(), b"dex output")

                run.reset_mock()
                jar.write_bytes(b"updated library jar")
                dexer._dex_libraries(config, use_d8=True)
                run.assert_called_once()

    def test_other_classpath_fingerprints_remain_available_for_active_builds(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            libs_dir = root / ".libs"
            jar_a = libs_dir / "a" / "a.jar"
            jar_b = libs_dir / "b" / "b.jar"
            jar_a.parent.mkdir(parents=True)
            jar_b.parent.mkdir(parents=True)
            jar_a.write_bytes(b"library a")
            jar_b.write_bytes(b"library b")
            android_jar = root / "android.jar"
            android_jar.write_bytes(b"android api")
            d8 = root / "d8"
            d8.write_bytes(b"d8 toolchain")

            def make_config(jar):
                return SimpleNamespace(
                    libs_dir=str(libs_dir),
                    cache_dir=str(root / ".cache"),
                    build_type="debug",
                    min_sdk=21,
                    android_jar=str(android_jar),
                    bin_d8=str(d8),
                    find_lib_jars=lambda: [str(jar)],
                )

            def write_dex(args):
                output_dir = Path(args[args.index("--output") + 1])
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "classes.dex").write_bytes(b"dex output")

            first = make_config(jar_a)
            second = make_config(jar_b)
            with patch.object(dexer, "run", side_effect=write_dex):
                dexer._dex_libraries(first, use_d8=True)
                first_cache = Path(first.library_dex_dir)
                dexer._dex_libraries(second, use_d8=True)

            self.assertTrue(first_cache.is_dir())
            self.assertTrue(Path(first.library_dex_dir).is_dir())


if __name__ == "__main__":
    unittest.main()
