import os
import tempfile
import requests
from builder.kapt import _validate_toolchain_jar
from builder.utils import ensure_dir, find_bin, log

_MAVEN_BASE = "https://repo1.maven.org/maven2"
_KSP_VERSION = "1.9.24-1.0.20"
_K1_KOTLIN_VERSION = "1.9.24"
_PLUGIN_CLASS = "com/google/devtools/ksp/KotlinSymbolProcessingComponentRegistrar.class"


def _download(url, dest, required_class=_PLUGIN_CLASS):
    if not url.startswith(_MAVEN_BASE + "/"):
        raise ValueError("KSP downloads require the configured HTTPS Maven origin")
    directory = os.path.dirname(os.path.abspath(dest))
    if os.path.islink(directory):
        raise RuntimeError("KSP cache directory must not be a symlink")
    if os.path.lexists(dest):
        _validate_toolchain_jar(dest, required_class, "KSP artifact")
        return
    with tempfile.TemporaryDirectory(prefix=".ksp-", dir=directory) as staging:
        temporary = os.path.join(staging, "artifact.jar")
        try:
            response = requests.get(url, timeout=120, stream=True, allow_redirects=False)
            try:
                response.raise_for_status()
                if response.status_code != 200:
                    raise RuntimeError("KSP artifact download requires HTTP 200; redirects are refused")
                total = 0
                with open(temporary, "wb") as output:
                    for chunk in response.iter_content(65536):
                        total += len(chunk)
                        if total > 128 * 1024 * 1024:
                            raise RuntimeError("KSP artifact download exceeds 128 MiB")
                        output.write(chunk)
            finally:
                response.close()
        except requests.RequestException as exc:
            raise RuntimeError("KSP artifact download failed; check network connectivity") from exc
        _validate_toolchain_jar(temporary, required_class, "KSP artifact")
        if os.path.lexists(dest):
            _validate_toolchain_jar(dest, required_class, "KSP artifact")
        else:
            os.replace(temporary, dest)


def setup_ksp_toolchain(config):
    """Resolve the pinned K1 compiler and matching KSP adapter toolchain."""
    from builder.kapt import setup_k1_compiler
    java = find_bin("java")
    if not java:
        raise RuntimeError("java not found — needed for KSP")
    cache_dir = os.path.join(config.cache_dir, "ksp")
    if os.path.islink(config.cache_dir) or os.path.islink(cache_dir):
        raise RuntimeError("KSP cache directory must not be a symlink")
    ensure_dir(cache_dir)
    embeddable_jar = os.path.join(cache_dir, f"kotlin-compiler-embeddable-{_K1_KOTLIN_VERSION}.jar")
    ksp_api_jar = os.path.join(cache_dir, f"symbol-processing-api-{_KSP_VERSION}.jar")
    ksp_plugin_jar = os.path.join(cache_dir, f"symbol-processing-{_KSP_VERSION}.jar")
    artifacts = [
        (f"org/jetbrains/kotlin/kotlin-compiler-embeddable/{_K1_KOTLIN_VERSION}/kotlin-compiler-embeddable-{_K1_KOTLIN_VERSION}.jar", embeddable_jar, "org/jetbrains/kotlin/cli/jvm/K2JVMCompiler.class"),
        (f"com/google/devtools/ksp/symbol-processing-api/{_KSP_VERSION}/symbol-processing-api-{_KSP_VERSION}.jar", ksp_api_jar, "com/google/devtools/ksp/processing/KSPLogger.class"),
        (f"com/google/devtools/ksp/symbol-processing/{_KSP_VERSION}/symbol-processing-{_KSP_VERSION}.jar", ksp_plugin_jar, _PLUGIN_CLASS),
    ]
    for coordinate, destination, required_class in artifacts:
        if os.path.lexists(destination):
            _validate_toolchain_jar(destination, required_class, "KSP artifact")
        else:
            log.info("Downloading KSP toolchain artifact: %s", os.path.basename(destination))
            _download(f"{_MAVEN_BASE}/{coordinate}", destination, required_class)
    standalone_jars = setup_k1_compiler(config)
    if not standalone_jars:
        raise RuntimeError("KSP compiler distribution is unavailable")
    deps = [jar for jar in standalone_jars if os.path.basename(jar) != "kotlin-compiler.jar"]
    classpath = os.pathsep.join([embeddable_jar, ksp_api_jar] + deps)
    return [java, "-cp", classpath, "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler"], ksp_plugin_jar
