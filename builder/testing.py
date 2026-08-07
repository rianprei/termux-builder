import os
from builder.utils import run, find_files, find_bin, log, ensure_dir


def run_tests(config):
    test_dir = os.path.join(config.project_dir, "src", "test")
    if not os.path.isdir(test_dir):
        log.info("No test directory (src/test) — skipping")
        return True

    test_java = find_files(test_dir, ".java")
    test_kt = find_files(test_dir, ".kt")
    all_tests = test_java + test_kt

    if not all_tests:
        log.info("No test files found — skipping")
        return True

    log.info("Running %d test files", len(all_tests))

    junit_jar = _find_junit(config)
    if not junit_jar:
        log.warning("JUnit not found in libs — download junit-4.13.2 or add to dependencies")
        return False

    test_classes_dir = ensure_dir(os.path.join(config.build_dir, "test-classes"))

    lib_jars = config.find_lib_jars()
    classpath = os.pathsep.join([
        config.android_jar,
        config.java_classes_dir,
        config.kotlin_classes_dir,
        junit_jar,
        *lib_jars,
    ])

    if test_java:
        run([
            config.bin_javac,
            "-source", str(config.java_version),
            "-target", str(config.java_version),
            "-classpath", classpath,
            "-proc:none",
            "-d", test_classes_dir,
            *test_java,
        ])

    if test_kt:
        kt_cp = os.pathsep.join([classpath, test_classes_dir])
        run([
            config.bin_kotlinc,
            *test_kt,
            "-classpath", kt_cp,
            "-d", test_classes_dir,
            "-jvm-target", str(config.java_version),
            "-no-reflect",
            "-no-stdlib",
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

    result = run(
        [java, "-cp", run_cp, "org.junit.runner.JUnitCore", *test_classes],
        check=False,
    )

    if result.returncode != 0:
        log.error("Tests FAILED")
        return False

    log.info("Tests PASSED")
    return True


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
        name = rel.replace(os.sep, ".").replace(".class", "")
        if "Test" in name or "test" in name:
            classes.append(name)
    return classes
