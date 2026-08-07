import os
import re
import subprocess
import requests
from builder.utils import ensure_dir, log

_MAVEN_BASE = "https://repo1.maven.org/maven2"


def _detect_kotlinc_version(config):
    result = subprocess.run(
        [config.bin_kotlinc, "-version"], capture_output=True, text=True
    )
    # kotlinc prints version to stderr: "info: kotlinc-jvm X.Y.Z (JRE ...)"
    m = re.search(r"kotlinc-jvm (\d+\.\d+\.\d+)", result.stderr or result.stdout)
    if not m:
        raise RuntimeError(f"kapt: could not detect kotlinc version from: {result.stderr!r}")
    return m.group(1)


def setup_kapt_plugin(config):
    """Download kotlin-annotation-processing-embeddable matching the exact
    installed kotlinc version — verified that a version mismatch (e.g.
    kapt 1.9.24 against kotlinc 2.4.10) fails hard with 'Plugin ... is
    incompatible with the current version of the compiler'."""
    version = _detect_kotlinc_version(config)
    cache_dir = ensure_dir(os.path.join(config.cache_dir, "kapt"))
    jar_path = os.path.join(cache_dir, f"kapt-{version}.jar")

    if os.path.isfile(jar_path):
        return jar_path

    url = (
        f"{_MAVEN_BASE}/org/jetbrains/kotlin/kotlin-annotation-processing-embeddable/"
        f"{version}/kotlin-annotation-processing-embeddable-{version}.jar"
    )
    tmp = jar_path + ".tmp"
    log.info("Downloading kapt plugin for kotlinc %s", version)
    try:
        r = requests.get(url, timeout=60, stream=True)
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        os.rename(tmp, jar_path)
    except requests.RequestException as e:
        log.error(
            "kapt plugin download failed for kotlinc %s: %s "
            "(no matching kotlin-annotation-processing-embeddable artifact "
            "on Maven Central for this exact version)", version, e
        )
        return None

    return jar_path
