import os
import requests
from builder.utils import ensure_dir, find_bin, log

_MAVEN_BASE = "https://repo1.maven.org/maven2"
_KSP_VERSION = "1.9.24-1.0.20"
_K1_KOTLIN_VERSION = "1.9.24"


def _download(url, dest):
    tmp = dest + ".tmp"
    r = requests.get(url, timeout=120, stream=True)
    r.raise_for_status()
    with open(tmp, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)
    os.rename(tmp, dest)


def setup_ksp_toolchain(config):
    """KSP has no release matching kotlinc 2.x (Termux package) — Maven
    Central's latest symbol-processing-cmdline covers up to kotlinc 2.2.21
    only (verified via maven-metadata.xml). Falls back to the K1 1.9.24
    toolchain (same one used for kapt), which HAS a matching KSP release
    (1.9.24-1.0.20).

    Real classpath recipe (found by trial — each swap fixed one distinct
    error): kotlin-compiler-embeddable.jar (not the standalone dist's plain
    kotlin-compiler.jar — that one throws AbstractMethodError, ComponentRegistrar
    ABI mismatch) + symbol-processing-api.jar (KSPLogger and friends,
    missing = ClassNotFoundException) + the standalone dist's other lib/*.jar
    for transitive deps (trove4j, asm, etc — embeddable alone is missing
    these, throws NoClassDefFoundError). Verified: this combination loads
    and executes the KSP plugin without crashing, reaches real processor
    discovery instead of an ABI/classpath error."""
    from builder.kapt import setup_k1_compiler
    cache_dir = ensure_dir(os.path.join(config.cache_dir, "ksp"))

    embeddable_jar = os.path.join(cache_dir, f"kotlin-compiler-embeddable-{_K1_KOTLIN_VERSION}.jar")
    if not os.path.isfile(embeddable_jar):
        log.info("Downloading kotlin-compiler-embeddable %s (for KSP)", _K1_KOTLIN_VERSION)
        try:
            _download(
                f"{_MAVEN_BASE}/org/jetbrains/kotlin/kotlin-compiler-embeddable/{_K1_KOTLIN_VERSION}/kotlin-compiler-embeddable-{_K1_KOTLIN_VERSION}.jar",
                embeddable_jar,
            )
        except requests.RequestException as e:
            log.error("kotlin-compiler-embeddable download failed: %s", e)
            return None, None

    ksp_api_jar = os.path.join(cache_dir, f"symbol-processing-api-{_KSP_VERSION}.jar")
    ksp_plugin_jar = os.path.join(cache_dir, f"symbol-processing-{_KSP_VERSION}.jar")
    for name, dest in (("symbol-processing-api", ksp_api_jar), ("symbol-processing", ksp_plugin_jar)):
        if os.path.isfile(dest):
            continue
        log.info("Downloading KSP %s %s", name, _KSP_VERSION)
        try:
            _download(f"{_MAVEN_BASE}/com/google/devtools/ksp/{name}/{_KSP_VERSION}/{name}-{_KSP_VERSION}.jar", dest)
        except requests.RequestException as e:
            log.error("KSP jar download failed (%s): %s", name, e)
            return None, None

    standalone_jars = setup_k1_compiler(config)
    if not standalone_jars:
        return None, None
    deps = [j for j in standalone_jars if not os.path.basename(j) == "kotlin-compiler.jar"]

    java = find_bin("java")
    if not java:
        raise RuntimeError("java not found — needed for KSP")
    classpath = os.pathsep.join([embeddable_jar, ksp_api_jar] + deps)
    invocation = [java, "-cp", classpath, "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler"]
    return invocation, ksp_plugin_jar
