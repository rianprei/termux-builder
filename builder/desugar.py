import os
import zipfile
import requests
from builder.utils import ensure_dir, log

_GROUP = "com.android.tools"
_LIB_VERSION = "2.1.5"
_MAVEN_BASE = "https://dl.google.com/dl/android/maven2"


def setup_desugar_lib(config):
    """Download desugar_jdk_libs (real Google Maven artifact) and extract its
    d8 desugar.json config. Returns (json_path, jar_path) or (None, None) if
    the download fails — caller must handle the None case with a precise
    error, not silently skip desugaring."""
    cache_dir = ensure_dir(os.path.join(config.cache_dir, "desugar"))
    jar_path = os.path.join(cache_dir, f"desugar_jdk_libs-{_LIB_VERSION}.jar")
    json_path = os.path.join(cache_dir, "desugar.json")

    if os.path.isfile(jar_path) and os.path.isfile(json_path):
        return json_path, jar_path

    jar_url = f"{_MAVEN_BASE}/com/android/tools/desugar_jdk_libs/{_LIB_VERSION}/desugar_jdk_libs-{_LIB_VERSION}.jar"
    cfg_url = f"{_MAVEN_BASE}/com/android/tools/desugar_jdk_libs_configuration/{_LIB_VERSION}/desugar_jdk_libs_configuration-{_LIB_VERSION}.jar"

    try:
        log.info("Downloading desugar_jdk_libs %s", _LIB_VERSION)
        _download(jar_url, jar_path)

        cfg_jar = os.path.join(cache_dir, "config.jar")
        _download(cfg_url, cfg_jar)
        with zipfile.ZipFile(cfg_jar) as z:
            with z.open("META-INF/desugar/d8/desugar.json") as src, open(json_path, "wb") as dst:
                dst.write(src.read())
        os.remove(cfg_jar)
    except (requests.RequestException, KeyError, zipfile.BadZipFile) as e:
        log.error("Desugar library setup failed: %s", e)
        return None, None

    return json_path, jar_path


def _download(url, dest):
    tmp = dest + ".tmp"
    r = requests.get(url, timeout=60, stream=True)
    r.raise_for_status()
    with open(tmp, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)
    os.rename(tmp, dest)
