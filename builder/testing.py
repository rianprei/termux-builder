import os
import hashlib
import shutil
import stat
import tempfile
import requests
from builder.utils import run, find_files, find_bin, log, ensure_dir

JACOCO_VERSION = "0.8.12"
JACOCO_BASE = "https://repo.maven.apache.org/maven2/org/jacoco"
JACOCO_MAX_BYTES = 8 * 1024 * 1024
JACOCO_SHA256 = {
    "agent": "115e8e6e6593ca3a9892dfef695df4d487c706e59e71e64dc0ab95716ee02622",
    "cli": "594c01125b84864a7fc5a9efab19b71b7de36b27346863f6d7cd0cd45400ceb0",
}


def _verify_jacoco(path, kind):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > JACOCO_MAX_BYTES:
                raise RuntimeError("JaCoCo cache must be a regular file within the size limit")
            digest = hashlib.sha256()
            total = 0
            while chunk := os.read(fd, 64 * 1024):
                total += len(chunk)
                if total > JACOCO_MAX_BYTES:
                    raise RuntimeError("JaCoCo cache exceeds the size limit")
                digest.update(chunk)
            if digest.hexdigest() != JACOCO_SHA256[kind]:
                raise RuntimeError(f"JaCoCo cache checksum mismatch; remove only this file and retry: {path}")
        finally:
            os.close(fd)
    except OSError:
        raise RuntimeError(f"Cannot read JaCoCo cache safely: {path}") from None


def run_tests(config, coverage=False, coverage_report=None):
    exec_file = os.path.join(config.build_dir, "jacoco.exec") if coverage else None
    if exec_file and os.path.lexists(exec_file):
        existing = os.lstat(exec_file)
        if not stat.S_ISREG(existing.st_mode) or existing.st_nlink != 1:
            raise RuntimeError("JaCoCo execution output must be a regular file without symlinks or hard links")
    test_classes_dir = os.path.join(config.build_dir, "test-classes")
    if os.path.lexists(test_classes_dir):
        if os.path.islink(test_classes_dir) or not os.path.isdir(test_classes_dir):
            raise RuntimeError("Test class output must be a directory, not a symlink or file")
        shutil.rmtree(test_classes_dir)
    test_dirs = [
        os.path.join(config.project_dir, "src", "test"),
        os.path.join(config.project_dir, "src", "androidTest"),
    ]
    test_dirs = [d for d in test_dirs if os.path.isdir(d)]
    if not test_dirs:
        log.info("No test directory (src/test or src/androidTest) — skipping")
        return True

    test_java = [f for d in test_dirs for f in find_files(d, ".java")]
    test_kt = [f for d in test_dirs for f in find_files(d, ".kt")]
    all_tests = test_java + test_kt

    if not all_tests:
        log.info("No test files found — skipping")
        return True

    log.info("Running %d test files", len(all_tests))

    junit_jar = _find_junit(config)
    if not junit_jar:
        log.warning("JUnit not found in libs — download junit-4.13.2 or add to dependencies")
        return False

    ensure_dir(test_classes_dir)

    lib_jars = config.find_lib_jars()
    classpath = os.pathsep.join([
        config.android_jar,
        config.java_classes_dir,
        config.kotlin_classes_dir,
        junit_jar,
        *lib_jars,
    ])

    if test_kt:
        kt_cp = os.pathsep.join([classpath, test_classes_dir])
        run([
            config.bin_kotlinc,
            *test_kt,
            *test_java,
            "-classpath", kt_cp,
            "-d", test_classes_dir,
            "-jvm-target", "1.8" if config.java_version == 8 else str(config.java_version),
            "-no-reflect",
            "-no-stdlib",
        ])

    if test_java:
        run([
            config.bin_javac,
            "-source", str(config.java_version),
            "-target", str(config.java_version),
            "-classpath", os.pathsep.join([classpath, test_classes_dir]),
            "-proc:none",
            "-d", test_classes_dir,
            *test_java,
        ])

    test_classes = _find_test_classes(test_classes_dir)
    if not test_classes:
        log.warning("No test classes compiled")
        return False

    java = find_bin("java")
    if not java:
        log.error("java not found in PATH")
        return False

    run_cp = os.pathsep.join([
        test_classes_dir,
        config.java_classes_dir,
        config.kotlin_classes_dir,
        config.android_jar,
        junit_jar,
        *lib_jars,
    ])

    java_args = [java, "-cp", run_cp]
    if coverage:
        agent_jar = _find_jacoco(config, "agent", "org.jacoco.agent", "runtime")
        java_args.append(f"-javaagent:{agent_jar}=destfile={exec_file},append=false")
    java_args += ["org.junit.runner.JUnitCore", *test_classes]

    result = run(java_args, check=False)

    if result.returncode != 0:
        log.error("Tests FAILED")
        return False

    log.info("Tests PASSED")

    if coverage:
        _write_coverage_report(config, exec_file, coverage_report)

    return True


def _find_jacoco(config, kind, group, classifier):
    """Download jacoco agent/cli jar from Maven Central, cached in .cache/deps."""
    if (kind, group, classifier) not in (('agent', 'org.jacoco.agent', 'runtime'), ('cli', 'org.jacoco.cli', 'nodeps')):
        raise ValueError("Unsupported JaCoCo artifact")
    artifact = group
    filename = f"{artifact}-{JACOCO_VERSION}-{classifier}.jar"
    cache_root = os.path.normpath(config.cache_dir)
    if os.path.realpath(cache_root) != os.path.realpath(config.cache_dir):
        raise RuntimeError("JaCoCo cache path has ambiguous parent traversal through a symlink")
    cache_deps = os.path.join(cache_root, "deps")
    if any(os.path.islink(path) for path in (cache_root, cache_deps)):
        raise RuntimeError("JaCoCo cache directories must not be symlinks")
    dest = os.path.join(cache_deps, filename)
    if os.path.lexists(dest):
        _verify_jacoco(dest, kind)
        return dest
    try:
        ensure_dir(os.path.dirname(dest))
        fd, staging = tempfile.mkstemp(prefix='.jacoco-', dir=os.path.dirname(dest))
    except OSError:
        raise RuntimeError(f"Cannot prepare JaCoCo cache directory: {os.path.dirname(dest)}") from None
    url = f"{JACOCO_BASE}/{artifact}/{JACOCO_VERSION}/{filename}"
    log.info("Downloading %s", filename)
    try:
        with os.fdopen(fd, 'wb') as output:
            response = requests.get(url, timeout=60, stream=True, allow_redirects=False)
            try:
                if response.status_code != 200:
                    raise RuntimeError("JaCoCo download requires a direct HTTP 200 response")
                total = 0
                for chunk in response.iter_content(64 * 1024):
                    total += len(chunk)
                    if total > JACOCO_MAX_BYTES:
                        raise RuntimeError("JaCoCo download exceeds the size limit")
                    output.write(chunk)
            finally:
                response.close()
        _verify_jacoco(staging, kind)
        os.replace(staging, dest)
    except (requests.RequestException, OSError) as exc:
        raise RuntimeError(f"JaCoCo download failed ({type(exc).__name__}); network is required when the verified cache is missing") from None
    finally:
        if os.path.exists(staging):
            os.unlink(staging)
    return dest


def _write_coverage_report(config, exec_file, report_dir):
    requested = report_dir or os.path.join(config.build_dir, "coverage")
    report_dir = os.path.abspath(requested)
    if os.path.realpath(requested) != os.path.realpath(report_dir):
        raise RuntimeError("Coverage report path has ambiguous symlink traversal")
    if os.path.realpath(report_dir) != report_dir:
        raise RuntimeError("Coverage report path must not contain symlinks")
    if os.path.lexists(report_dir):
        if not os.path.isdir(report_dir):
            raise RuntimeError("Coverage report output must be a directory")
        def fail_walk(error):
            raise RuntimeError("Coverage report directory cannot be inspected safely") from error
        for directory, dirs, files in os.walk(report_dir, onerror=fail_walk):
            for name in dirs + files:
                metadata = os.lstat(os.path.join(directory, name))
                if not (stat.S_ISDIR(metadata.st_mode) or
                        (stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1)):
                    raise RuntimeError("Coverage report must not contain symlinks, special files or hard links")
    java = find_bin("java")
    cli_jar = _find_jacoco(config, "cli", "org.jacoco.cli", "nodeps")
    ensure_dir(report_dir)
    run([
        java, "-jar", cli_jar, "report", exec_file,
        "--classfiles", config.java_classes_dir,
        "--classfiles", config.kotlin_classes_dir,
        "--sourcefiles", config.sources_dir,
        "--html", report_dir,
        "--xml", os.path.join(report_dir, "coverage.xml"),
    ])
    log.info("Coverage report: %s", report_dir)


def _find_junit(config):
    for jar in config.find_lib_jars():
        if "junit" in os.path.basename(jar).lower():
            return jar

    cache_junit = os.path.join(config.cache_dir, "deps", "junit-4.13.2.jar")
    if os.path.isfile(cache_junit):
        return cache_junit

    return None


def _find_test_classes(classes_dir):
    classes = []
    for cls in find_files(classes_dir, ".class"):
        if "$" in os.path.basename(cls):
            continue
        rel = os.path.relpath(cls, classes_dir)
        name = rel[:-len(".class")].replace(os.sep, ".")
        base = name.rsplit(".", 1)[-1]
        if base.endswith("Test") or base.startswith("Test"):
            classes.append(name)
    return classes
