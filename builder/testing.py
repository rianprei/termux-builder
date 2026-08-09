import os
import requests
from builder.utils import run, find_files, find_bin, log, ensure_dir

JACOCO_VERSION = "0.8.12"
JACOCO_BASE = "https://repo1.maven.org/maven2/org/jacoco"


def run_tests(config, coverage=False, coverage_report=None):
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

    java_args = [java, "-cp", run_cp]
    exec_file = None
    if coverage:
        agent_jar = _find_jacoco(config, "agent", "org.jacoco.agent", "runtime")
        exec_file = os.path.join(config.build_dir, "jacoco.exec")
        java_args.append(f"-javaagent:{agent_jar}=destfile={exec_file}")
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
    artifact = "org.jacoco.agent" if kind == "agent" else "org.jacoco.cli"
    filename = f"{artifact}-{JACOCO_VERSION}-{classifier}.jar"
    dest = os.path.join(config.cache_dir, "deps", filename)
    if os.path.isfile(dest):
        return dest
    ensure_dir(os.path.dirname(dest))
    url = f"{JACOCO_BASE}/{artifact}/{JACOCO_VERSION}/{filename}"
    log.info("Downloading %s", filename)
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    with open(dest, "wb") as f:
        f.write(r.content)
    return dest


def _write_coverage_report(config, exec_file, report_dir):
    java = find_bin("java")
    cli_jar = _find_jacoco(config, "cli", "org.jacoco.cli", "nodeps")
    report_dir = report_dir or os.path.join(config.build_dir, "coverage")
    ensure_dir(report_dir)
    run([
        java, "-jar", cli_jar, "report", exec_file,
        "--classfiles", config.java_classes_dir,
        "--classfiles", config.kotlin_classes_dir,
        "--sourcefiles", config.sources_dir,
        "--html", report_dir,
        "--xml", os.path.join(report_dir, "coverage.xml"),
    ], check=False)
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
        name = rel.replace(os.sep, ".").replace(".class", "")
        base = name.rsplit(".", 1)[-1]
        if base.endswith("Test") or base.startswith("Test"):
            classes.append(name)
    return classes
