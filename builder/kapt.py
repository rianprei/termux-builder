import os
import re
import subprocess
import zipfile
import requests
from builder.utils import ensure_dir, find_bin, log

_MAVEN_BASE = "https://repo1.maven.org/maven2"
_K1_VERSION = "1.9.24"
_K1_DIST_URL = f"https://github.com/JetBrains/kotlin/releases/download/v{_K1_VERSION}/kotlin-compiler-{_K1_VERSION}.zip"


def _detect_kotlinc_version(kotlinc_bin):
    result = subprocess.run([kotlinc_bin, "-version"], capture_output=True, text=True)
    m = re.search(r"kotlinc-jvm (\d+\.\d+\.\d+)", result.stderr or result.stdout)
    if not m:
        raise RuntimeError(f"kapt: could not detect kotlinc version from: {result.stderr!r}")
    return m.group(1)


def setup_kapt_plugin(config, kotlinc_version):
    """Download kotlin-annotation-processing-embeddable matching a given
    kotlinc version. Real caveat verified: version mismatch fails hard with
    'Plugin ... is incompatible with the current version of the compiler.'"""
    cache_dir = ensure_dir(os.path.join(config.cache_dir, "kapt"))
    jar_path = os.path.join(cache_dir, f"kapt-{kotlinc_version}.jar")
    if os.path.isfile(jar_path):
        return jar_path

    url = (
        f"{_MAVEN_BASE}/org/jetbrains/kotlin/kotlin-annotation-processing-embeddable/"
        f"{kotlinc_version}/kotlin-annotation-processing-embeddable-{kotlinc_version}.jar"
    )
    tmp = jar_path + ".tmp"
    log.info("Downloading kapt plugin for kotlinc %s", kotlinc_version)
    try:
        r = requests.get(url, timeout=60, stream=True)
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        os.rename(tmp, jar_path)
    except requests.RequestException as e:
        log.error("kapt plugin download failed for kotlinc %s: %s", kotlinc_version, e)
        return None
    return jar_path


def setup_k1_compiler(config):
    """kapt3 crashes on the K2 frontend used by kotlinc 2.x (verified:
    AbstractMethodError on FirKaptAnalysisHandlerExtension.doAnalysis).
    Verified working alternative: the standalone Kotlin 1.9.24 compiler
    distribution (K1 frontend, official JetBrains release) loads kapt3
    cleanly with matching kapt-1.9.24 plugin — no crash on plugin load.
    Downloads+caches the ~90MB dist once, returns its full lib/ classpath
    for direct `java -cp <classpath> org.jetbrains.kotlin.cli.jvm.K2JVMCompiler`
    invocation (class name predates the K1/K2 split, applies to both)."""
    cache_dir = ensure_dir(os.path.join(config.cache_dir, "kapt"))
    dist_dir = os.path.join(cache_dir, f"kotlinc-{_K1_VERSION}")
    lib_dir = os.path.join(dist_dir, "kotlinc", "lib")

    if os.path.isdir(lib_dir):
        return sorted(os.path.join(lib_dir, f) for f in os.listdir(lib_dir) if f.endswith(".jar"))

    zip_path = os.path.join(cache_dir, f"kotlinc-{_K1_VERSION}.zip")
    tmp = zip_path + ".tmp"
    log.info("Downloading Kotlin %s standalone compiler (K1, for kapt compatibility — one-time, ~90MB)", _K1_VERSION)
    try:
        r = requests.get(_K1_DIST_URL, timeout=180, stream=True)
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)
        os.rename(tmp, zip_path)
        ensure_dir(dist_dir)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(dist_dir)
    except (requests.RequestException, zipfile.BadZipFile) as e:
        log.error("K1 compiler download/extract failed: %s", e)
        return None

    if not os.path.isdir(lib_dir):
        log.error("K1 compiler extracted but lib/ not found at expected path: %s", lib_dir)
        return None

    return sorted(os.path.join(lib_dir, f) for f in os.listdir(lib_dir) if f.endswith(".jar"))


def resolve_kapt_toolchain(config):
    """Returns (invocation_prefix, kapt_plugin_jar) — either the system
    kotlinc (if it's already K1, no crash) or a downloaded K1 fallback
    (if system kotlinc is K2, verified to crash kapt3)."""
    version = _detect_kotlinc_version(config.bin_kotlinc)
    major = int(version.split(".")[0])

    if major < 2:
        plugin = setup_kapt_plugin(config, version)
        if not plugin:
            return None, None
        return [config.bin_kotlinc], plugin

    log.info("System kotlinc %s uses K2 (kapt3 crashes on K2 — verified) — using K1 %s fallback", version, _K1_VERSION)
    classpath_jars = setup_k1_compiler(config)
    if not classpath_jars:
        return None, None
    plugin = setup_kapt_plugin(config, _K1_VERSION)
    if not plugin:
        return None, None

    java = find_bin("java")
    if not java:
        raise RuntimeError("java not found — needed for K1 kapt fallback")
    classpath = os.pathsep.join(classpath_jars)
    return [java, "-cp", classpath, "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler"], plugin
