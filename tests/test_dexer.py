import multiprocessing
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from builder import deps, dexer, utils


class KaptDexTests(unittest.TestCase):
    def test_unsafe_processor_class_is_rejected_before_dex(self):
        for kind in ('symlink', 'fifo'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                output = root / 'kapt/classes'
                output.mkdir(parents=True)
                outside = root / 'Outside.class'
                outside.write_bytes(b'keep')
                binary = output / 'Direct.class'
                if kind == 'symlink':
                    binary.symlink_to(outside)
                else:
                    os.mkfifo(binary)
                config = SimpleNamespace(build_dir=temp, java_classes_dir=str(root / 'java'),
                    kotlin_classes_dir=str(root / 'kotlin'), dex_dir=str(root / 'dex'),
                    kapt_enabled=True, r8_enabled=False, build_type='debug')
                with patch('builder.dexer._has_d8', return_value=True), patch('builder.dexer._run_d8') as d8, patch('builder.dexer._dex_libraries'):
                    with self.assertRaises(ValueError):
                        dexer.dex(config)
                d8.assert_not_called()
                self.assertEqual(outside.read_bytes(), b'keep')

    def test_symlinked_kapt_output_is_rejected_before_dex(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            build = root / 'build'
            (build / 'kapt').mkdir(parents=True)
            outside = root / 'outside'
            outside.mkdir()
            (outside / 'Direct.class').write_bytes(b'class')
            (build / 'kapt/classes').symlink_to(outside, target_is_directory=True)
            config = SimpleNamespace(build_dir=str(build), java_classes_dir=str(build / 'java'),
                kotlin_classes_dir=str(build / 'kotlin'), dex_dir=str(build / 'dex'), kapt_enabled=True)
            with patch('builder.dexer._run_d8') as d8:
                with self.assertRaises(ValueError):
                    dexer.dex(config)
            d8.assert_not_called()

    def test_direct_processor_classes_reach_dex(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / 'kapt/classes/Direct.class'
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b'class')
            config = SimpleNamespace(build_dir=temp, java_classes_dir=str(root / 'java'),
                kotlin_classes_dir=str(root / 'kotlin'), dex_dir=str(root / 'dex'),
                kapt_enabled=True, r8_enabled=False, build_type='debug')
            with patch('builder.dexer._has_d8', return_value=True), patch('builder.dexer._run_d8') as d8, patch('builder.dexer._dex_libraries'):
                dexer.dex(config)
            self.assertEqual(d8.call_args.args[1], [str(binary)])


def _build_library_cache_worker(start_barrier, results, values):
    try:
        start_barrier.wait(timeout=10)
        libs_dir, jar, android_jar, d8, cache_dir, marker = values
        os.environ["RUN_MARKER"] = marker
        config = SimpleNamespace(
            libs_dir=libs_dir,
            cache_dir=cache_dir,
            build_type="debug",
            min_sdk=21,
            android_jar=android_jar,
            bin_d8=d8,
            find_lib_jars=lambda: [jar],
        )
        dexer._dex_libraries(config, use_d8=True)
        results.put(("ok", config.library_dex_dir))
    except BaseException as exc:
        results.put(("error", repr(exc)))


def _interrupt_library_cache_worker(started, values):
    libs_dir, jar, android_jar, d8, cache_dir = values
    config = SimpleNamespace(
        libs_dir=libs_dir,
        cache_dir=cache_dir,
        build_type="debug",
        min_sdk=21,
        android_jar=android_jar,
        bin_d8=d8,
        find_lib_jars=lambda: [jar],
    )

    def block_d8(_args):
        started.set()
        time.sleep(30)

    with patch.object(dexer, "run", side_effect=block_d8):
        dexer._dex_libraries(config, use_d8=True)


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

    def test_concurrent_library_dex_builds_publish_one_valid_cache(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            libs_dir = root / ".libs"
            jar = libs_dir / "runtime.jar"
            jar.parent.mkdir(parents=True)
            jar.write_bytes(b"library jar")
            android_jar = root / "android.jar"
            android_jar.write_bytes(b"android api")
            d8 = root / "d8"
            d8.write_text(
                f"#!{sys.executable}\n"
                "import os, sys, time\n"
                "args = sys.argv[1:]\n"
                "output = args[args.index('--output') + 1]\n"
                "with open(os.environ['RUN_MARKER'], 'a') as marker: marker.write('run\\n')\n"
                "time.sleep(0.1)\n"
                "os.makedirs(output, exist_ok=True)\n"
                "with open(os.path.join(output, 'classes.dex'), 'wb') as dex: dex.write(b'dex output')\n",
                encoding="utf-8",
            )
            d8.chmod(0o755)
            marker = root / "d8-runs"
            context = multiprocessing.get_context("fork")
            start = context.Barrier(2)
            results = context.Queue()
            values = (
                str(libs_dir), str(jar), str(android_jar), str(d8), str(root / ".cache"), str(marker),
            )

            workers = [
                context.Process(target=_build_library_cache_worker, args=(start, results, values))
                for _ in range(2)
            ]
            try:
                for worker in workers:
                    worker.start()
                outputs = [results.get(timeout=10) for _ in workers]
                for worker in workers:
                    worker.join(timeout=5)

                self.assertEqual([worker.exitcode for worker in workers], [0, 0])
                self.assertTrue(all(status == "ok" for status, _ in outputs), outputs)
                self.assertEqual(outputs[0][1], outputs[1][1])
                self.assertTrue(Path(outputs[0][1]).is_dir())
                self.assertEqual(marker.read_text(encoding="utf-8").splitlines(), ["run"])

                cached = SimpleNamespace(
                    libs_dir=str(libs_dir),
                    cache_dir=str(root / ".cache"),
                    build_type="debug",
                    min_sdk=21,
                    android_jar=str(android_jar),
                    bin_d8=str(d8),
                    find_lib_jars=lambda: [str(jar)],
                )
                dexer._dex_libraries(cached, use_d8=True)
                self.assertEqual(cached.library_dex_dir, outputs[0][1])
                self.assertEqual(marker.read_text(encoding="utf-8").splitlines(), ["run"])
            finally:
                for worker in workers:
                    if worker.is_alive():
                        worker.terminate()
                    worker.join()
                results.close()
                results.join_thread()

    def test_library_dex_cache_rechecks_fingerprint_after_lock_wait(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            libs_dir = root / ".libs"
            jar = libs_dir / "runtime.jar"
            jar.parent.mkdir(parents=True)
            jar.write_bytes(b"library jar")
            android_jar = root / "android.jar"
            android_jar.write_bytes(b"android api")
            d8 = root / "d8"
            d8.write_bytes(b"d8 toolchain")
            config = SimpleNamespace(
                libs_dir=str(libs_dir),
                cache_dir=str(root / ".cache"),
                build_type="debug",
                min_sdk=21,
                android_jar=str(android_jar),
                bin_d8=str(d8),
                find_lib_jars=lambda: [str(jar)],
            )
            cache_root = root / ".cache" / "library-dex"
            cache_root.mkdir(parents=True)
            original_lock = dexer._library_dex_cache_lock
            lock_attempted = threading.Event()
            lock_acquired = threading.Event()
            completed = threading.Event()
            failures = []
            original_flock = utils.fcntl.flock
            worker = None

            def observe_flock(fd, operation):
                if threading.current_thread() is worker:
                    lock_attempted.set()
                    original_flock(fd, operation)
                    lock_acquired.set()
                    return
                original_flock(fd, operation)

            def write_dex(args):
                output_dir = Path(args[args.index("--output") + 1])
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "classes.dex").write_bytes(jar.read_bytes())

            def build():
                try:
                    dexer._dex_libraries(config, use_d8=True)
                except BaseException as exc:
                    failures.append(exc)
                finally:
                    completed.set()

            held_lock = original_lock(str(cache_root))
            held_lock.__enter__()
            lock_held = True
            try:
                with patch.object(utils.fcntl, "flock", side_effect=observe_flock):
                    with patch.object(dexer, "run", side_effect=write_dex) as run:
                        worker = threading.Thread(target=build, name="dex-cache-waiter")
                        worker.start()
                        self.assertTrue(lock_attempted.wait(5), "DEX worker never attempted the lock")
                        self.assertFalse(lock_acquired.wait(0.1), "DEX worker acquired a held cache lock")
                        jar.write_bytes(b"updated library jar")
                        held_lock.__exit__(None, None, None)
                        lock_held = False
                        self.assertTrue(lock_acquired.wait(5), "DEX worker did not acquire the released lock")
                        self.assertTrue(completed.wait(5), "DEX worker did not finish after lock release")
                        worker.join()
                        self.assertEqual(failures, [])

            finally:
                if lock_held:
                    held_lock.__exit__(None, None, None)
                if worker.is_alive():
                    worker.join(timeout=5)

            current_fingerprint = dexer._library_dex_fingerprint(config, [str(jar)], use_d8=True)
            expected_cache = root / ".cache" / "library-dex" / current_fingerprint
            self.assertEqual(Path(config.library_dex_dir), expected_cache)
            self.assertTrue(dexer._valid_library_dex_cache(str(expected_cache), current_fingerprint))
            cached_dex = next(expected_cache.rglob("*.dex"))
            self.assertEqual(cached_dex.read_bytes(), b"updated library jar")
            run.assert_called_once()

    def test_dependency_resolution_waits_for_dex_cache_lock(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            cache_root = root / ".cache" / "library-dex"
            cache_root.mkdir(parents=True)
            cache_dir = str(root / ".cache")
            config = SimpleNamespace(
                cache_dir=cache_dir,
                libs_dir=str(root / ".libs"),
                dependencies=[],
            )
            original_lock = dexer._library_dex_cache_lock
            lock_attempted = threading.Event()
            lock_acquired = threading.Event()
            resolution_entered = threading.Event()
            completed = threading.Event()
            failures = []
            original_flock = utils.fcntl.flock

            worker = None

            def observe_flock(fd, operation):
                if threading.current_thread() is worker:
                    lock_attempted.set()
                    original_flock(fd, operation)
                    lock_acquired.set()
                    return
                original_flock(fd, operation)

            def resolve():
                try:
                    deps.resolve(config)
                except BaseException as exc:
                    failures.append(exc)
                finally:
                    completed.set()

            with patch.object(utils.fcntl, "flock", side_effect=observe_flock):
                with patch.object(
                    deps,
                    "_cleanup_stale_aar_staging",
                    side_effect=lambda _path: resolution_entered.set(),
                ):
                    held_lock = original_lock(str(cache_root))
                    held_lock.__enter__()
                    lock_held = True
                    worker = threading.Thread(target=resolve, name="dependency-resolver")
                    worker.start()
                    try:
                        self.assertTrue(lock_attempted.wait(5), "resolver never attempted the DEX cache lock")
                        self.assertFalse(lock_acquired.wait(0.1), "resolver acquired a held cache lock")
                        self.assertFalse(resolution_entered.is_set())
                        self.assertFalse(completed.is_set())
                        held_lock.__exit__(None, None, None)
                        lock_held = False
                        self.assertTrue(lock_acquired.wait(5), "resolver did not acquire the released lock")
                        self.assertTrue(completed.wait(5), "resolver did not finish after lock release")
                        worker.join()
                    finally:
                        if lock_held:
                            held_lock.__exit__(None, None, None)
                        if worker.is_alive():
                            worker.join(timeout=5)

            self.assertEqual(failures, [])
            self.assertTrue(resolution_entered.is_set())

    def test_library_dex_cache_retries_when_inputs_change_during_dexing(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            libs_dir = root / ".libs"
            jar = libs_dir / "runtime.jar"
            jar.parent.mkdir(parents=True)
            jar.write_bytes(b"library jar")
            android_jar = root / "android.jar"
            android_jar.write_bytes(b"android api")
            d8 = root / "d8"
            d8.write_bytes(b"d8 toolchain")
            config = SimpleNamespace(
                libs_dir=str(libs_dir),
                cache_dir=str(root / ".cache"),
                build_type="debug",
                min_sdk=21,
                android_jar=str(android_jar),
                bin_d8=str(d8),
                find_lib_jars=lambda: [str(jar)],
            )
            changed = False

            def update_during_dex(args):
                nonlocal changed
                if not changed:
                    jar.write_bytes(b"updated library jar")
                    changed = True
                output_dir = Path(args[args.index("--output") + 1])
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "classes.dex").write_bytes(b"dex output")

            with patch.object(dexer, "run", side_effect=update_during_dex) as run:
                dexer._dex_libraries(config, use_d8=True)

            current_fingerprint = dexer._library_dex_fingerprint(config, [str(jar)], use_d8=True)
            expected_cache = root / ".cache" / "library-dex" / current_fingerprint
            self.assertEqual(Path(config.library_dex_dir), expected_cache)
            self.assertTrue(dexer._valid_library_dex_cache(str(expected_cache), current_fingerprint))
            self.assertEqual(run.call_count, 2)

    def test_library_dex_cache_failure_cleans_staging_and_allows_retry(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            libs_dir = root / ".libs"
            jar = libs_dir / "runtime.jar"
            jar.parent.mkdir(parents=True)
            jar.write_bytes(b"library jar")
            android_jar = root / "android.jar"
            android_jar.write_bytes(b"android api")
            d8 = root / "d8"
            d8.write_bytes(b"d8 toolchain")
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

            with patch.object(dexer, "run", side_effect=[RuntimeError("d8 failed"), write_dex]) as run:
                with self.assertRaisesRegex(RuntimeError, "d8 failed"):
                    dexer._dex_libraries(config, use_d8=True)

                cache_root = root / ".cache" / "library-dex"
                self.assertFalse(any(cache_root.glob(f".library-dex-{os.getpid()}-*")))
                dexer._dex_libraries(config, use_d8=True)

            self.assertTrue(Path(config.library_dex_dir).is_dir())
            self.assertEqual(run.call_count, 2)

    def test_library_dex_cache_recovers_after_process_interruption(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            libs_dir = root / ".libs"
            jar = libs_dir / "runtime.jar"
            jar.parent.mkdir(parents=True)
            jar.write_bytes(b"library jar")
            android_jar = root / "android.jar"
            android_jar.write_bytes(b"android api")
            d8 = root / "d8"
            d8.write_bytes(b"d8 toolchain")
            cache_dir = root / ".cache"
            cache_root = cache_dir / "library-dex"
            context = multiprocessing.get_context("fork")
            started = context.Event()
            worker = context.Process(
                target=_interrupt_library_cache_worker,
                args=(started, (str(libs_dir), str(jar), str(android_jar), str(d8), str(cache_dir))),
            )
            worker.start()
            try:
                self.assertTrue(started.wait(timeout=10))
                worker.terminate()
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
                self.assertTrue(any(cache_root.glob(f".library-dex-{worker.pid}-*")))

                config = SimpleNamespace(
                    libs_dir=str(libs_dir),
                    cache_dir=str(cache_dir),
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

                self.assertTrue(Path(config.library_dex_dir).is_dir())
                self.assertFalse(any(cache_root.glob(f".library-dex-{worker.pid}-*")))
                run.assert_called_once()
            finally:
                if worker.is_alive():
                    worker.terminate()
                worker.join()

    def test_library_dex_cache_lock_refuses_symlinks(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            libs_dir = root / ".libs"
            jar = libs_dir / "runtime.jar"
            jar.parent.mkdir(parents=True)
            jar.write_bytes(b"library jar")
            android_jar = root / "android.jar"
            android_jar.write_bytes(b"android api")
            d8 = root / "d8"
            d8.write_bytes(b"d8 toolchain")
            cache_root = root / ".cache" / "library-dex"
            cache_root.mkdir(parents=True)
            target = root / "lock-target"
            target.write_bytes(b"unchanged")
            config = SimpleNamespace(
                libs_dir=str(libs_dir),
                cache_dir=str(root / ".cache"),
                build_type="debug",
                min_sdk=21,
                android_jar=str(android_jar),
                bin_d8=str(d8),
                find_lib_jars=lambda: [str(jar)],
            )
            fingerprint = dexer._library_dex_fingerprint(config, [str(jar)], use_d8=True)
            lock_path = cache_root / ".library-dex.lock"
            lock_path.symlink_to(target)

            with patch.object(dexer, "run") as run:
                with self.assertRaisesRegex(RuntimeError, "Cannot open DEX cache lock safely"):
                    dexer._dex_libraries(config, use_d8=True)

            run.assert_not_called()
            self.assertEqual(target.read_bytes(), b"unchanged")


if __name__ == "__main__":
    unittest.main()
