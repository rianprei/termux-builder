import os
import re
import subprocess
import stat
import struct
import tempfile
from urllib.parse import urljoin, urlsplit
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
    if not isinstance(kotlinc_version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?", kotlinc_version):
        raise ValueError("Invalid Kotlin compiler version")
    cache_dir = os.path.join(config.cache_dir, "kapt")
    if os.path.islink(config.cache_dir) or os.path.islink(cache_dir):
        raise RuntimeError("KAPT cache directory must not be a symlink")
    ensure_dir(cache_dir)
    jar_path = os.path.join(cache_dir, f"kapt-{kotlinc_version}.jar")
    if os.path.lexists(jar_path):
        _validate_kapt_plugin(jar_path)
        return jar_path
    url = (
        f"{_MAVEN_BASE}/org/jetbrains/kotlin/kotlin-annotation-processing-embeddable/"
        f"{kotlinc_version}/kotlin-annotation-processing-embeddable-{kotlinc_version}.jar"
    )
    with tempfile.TemporaryDirectory(prefix=".kapt-plugin-", dir=cache_dir) as staging:
        temporary = os.path.join(staging, "plugin.jar")
        try:
            response = requests.get(url, timeout=60, stream=True, allow_redirects=False)
            try:
                response.raise_for_status()
                if response.status_code != 200:
                    raise RuntimeError("KAPT plugin download requires HTTP 200; redirects are refused")
                total = 0
                with open(temporary, "wb") as output:
                    for chunk in response.iter_content(65536):
                        total += len(chunk)
                        if total > 64 * 1024 * 1024:
                            raise RuntimeError("KAPT plugin download exceeds 64 MiB")
                        output.write(chunk)
            finally:
                response.close()
        except requests.RequestException as exc:
            raise RuntimeError("KAPT plugin download failed; check network connectivity") from exc
        _validate_kapt_plugin(temporary)
        if os.path.lexists(jar_path):
            _validate_kapt_plugin(jar_path)
        else:
            os.replace(temporary, jar_path)
    return jar_path


def _validate_kapt_plugin(path):
    _validate_toolchain_jar(path, "org/jetbrains/kotlin/kapt3/Kapt3ComponentRegistrar.class", "KAPT plugin")


def _validate_toolchain_jar(path, required_class, label):
    if os.path.islink(path) or not os.path.isfile(path):
        raise RuntimeError(f"Invalid {label} cache path")
    try:
        with _bounded_zip(path, 100000) as archive:
            if sum(member.file_size for member in archive.infolist()) > 256 * 1024 * 1024:
                raise RuntimeError(f"{label} exceeds validation limits")
            if archive.testzip() is not None or required_class not in archive.namelist():
                raise RuntimeError(f"Invalid {label} JAR")
            with archive.open(required_class) as source:
                header = source.read(10)
            if (len(header) != 10 or header[:4] != b"\xca\xfe\xba\xbe" or
                    int.from_bytes(header[6:8], "big") < 45 or
                    int.from_bytes(header[8:10], "big") < 2):
                raise RuntimeError(f"Invalid {label} class header")
    except (OSError, zipfile.BadZipFile) as exc:
        raise RuntimeError(f"Invalid {label} JAR; remove the cached artifact and retry") from exc


def _k1_download_response():
    url = _K1_DIST_URL
    for _ in range(6):
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError:
            raise RuntimeError("Invalid Kotlin distribution redirect URL") from None
        if (parsed.scheme != "https" or parsed.hostname not in
                {"github.com", "release-assets.githubusercontent.com"} or
                parsed.username or parsed.password or parsed.fragment or
                port not in (None, 443)):
            raise RuntimeError("Kotlin distribution redirect requires an authorized HTTPS origin")
        response = requests.get(url, timeout=180, stream=True, allow_redirects=False)
        try:
            response.raise_for_status()
            if response.status_code == 200:
                return response
            if response.status_code not in (301, 302, 303, 307, 308):
                raise RuntimeError("Kotlin distribution download requires HTTP 200")
            location = response.headers.get("Location")
            if not location:
                raise RuntimeError("Kotlin distribution redirect is missing Location")
            url = urljoin(url, location)
        finally:
            if response.status_code != 200:
                response.close()
    raise RuntimeError("Kotlin distribution exceeded five redirects")


def setup_k1_compiler(config):
    """kapt3 crashes on the K2 frontend used by kotlinc 2.x (verified:
    AbstractMethodError on FirKaptAnalysisHandlerExtension.doAnalysis).
    Verified working alternative: the standalone Kotlin 1.9.24 compiler
    distribution (K1 frontend, official JetBrains release) loads kapt3
    cleanly with matching kapt-1.9.24 plugin — no crash on plugin load.
    Downloads+caches the ~90MB dist once, returns its full lib/ classpath
    for direct `java -cp <classpath> org.jetbrains.kotlin.cli.jvm.K2JVMCompiler`
    invocation (class name predates the K1/K2 split, applies to both)."""
    cache_dir = os.path.join(config.cache_dir, "kapt")
    if os.path.islink(config.cache_dir) or os.path.islink(cache_dir):
        raise RuntimeError("Kotlin cache directory must not be a symlink")
    ensure_dir(cache_dir)
    dist_dir = os.path.join(cache_dir, f"kotlinc-{_K1_VERSION}")
    if os.path.lexists(dist_dir):
        return _k1_classpath(dist_dir)
    log.info("Downloading Kotlin %s standalone compiler (K1, for kapt compatibility — one-time, ~90MB)", _K1_VERSION)
    with tempfile.TemporaryDirectory(prefix=".kotlin-", dir=cache_dir) as staging:
        zip_path = os.path.join(staging, "compiler.zip")
        try:
            response = _k1_download_response()
            try:
                response.raise_for_status()
                total = 0
                with open(zip_path, "wb") as output:
                    for chunk in response.iter_content(65536):
                        total += len(chunk)
                        if total > 256 * 1024 * 1024:
                            raise RuntimeError("Kotlin compiler download exceeds 256 MiB")
                        output.write(chunk)
            finally:
                response.close()
        except requests.RequestException:
            raise RuntimeError("Kotlin compiler download failed; check network connectivity") from None
        extracted = ensure_dir(os.path.join(staging, "distribution"))
        try:
            with _bounded_zip(zip_path, 10000) as archive:
                seen = set()
                total = 0
                for member in archive.infolist():
                    parts = member.filename.rstrip("/").split("/")
                    if (not parts or parts[0] != "kotlinc" or
                            any(part in ("", ".", "..") for part in parts) or
                            "\\" in member.filename or
                            stat.S_ISLNK(member.external_attr >> 16) or
                            member.filename in seen):
                        raise RuntimeError("Unsafe entry in Kotlin compiler distribution")
                    seen.add(member.filename)
                    total += member.file_size
                    if total > 512 * 1024 * 1024 or len(seen) > 10000:
                        raise RuntimeError("Kotlin compiler distribution exceeds extraction limits")
                archive.extractall(extracted)
            _k1_classpath(extracted)
        except (OSError, zipfile.BadZipFile) as exc:
            raise RuntimeError("Invalid Kotlin compiler distribution") from exc
        if os.path.lexists(dist_dir):
            return _k1_classpath(dist_dir)
        try:
            os.rename(extracted, dist_dir)
        except OSError:
            if os.path.lexists(dist_dir):
                return _k1_classpath(dist_dir)
            raise
    return _k1_classpath(dist_dir)


def _bounded_zip(path, max_entries):
    with open(path, "rb") as source:
        source.seek(0, os.SEEK_END)
        size = source.tell()
        source.seek(max(0, size - 65557))
        tail = source.read()
    end = tail.rfind(b"PK\x05\x06")
    while end >= 0:
        if end + 22 <= len(tail):
            record = struct.unpack_from("<4s4H2IH", tail, end)
            if end + 22 + record[7] == len(tail):
                break
        end = tail.rfind(b"PK\x05\x06", 0, end)
    if end < 0:
        raise RuntimeError("Invalid Kotlin ZIP end record")
    if (record[1] or record[2] or record[3] != record[4] or
            record[4] == 65535 or record[4] > max_entries or
            record[5] > 16 * 1024 * 1024 or
            record[6] + record[5] != size - len(tail) + end):
        raise RuntimeError("Kotlin ZIP exceeds directory limits or uses unsupported ZIP64/multipart format")
    with open(path, "rb") as source:
        source.seek(record[6])
        directory_end = record[6] + record[5]
        count = 0
        while source.tell() < directory_end:
            header = source.read(46)
            if len(header) != 46 or header[:4] != b"PK\x01\x02":
                raise RuntimeError("Invalid Kotlin ZIP directory entry")
            fields = struct.unpack("<4s6H3I5H2I", header)
            source.seek(sum(fields[10:13]), os.SEEK_CUR)
            count += 1
            if count > max_entries or source.tell() > directory_end:
                raise RuntimeError("Kotlin ZIP exceeds directory limits")
        if count != record[4]:
            raise RuntimeError("Kotlin ZIP entry count mismatch")
    return zipfile.ZipFile(path)


def _k1_classpath(dist_dir):
    lib_dir = os.path.join(dist_dir, "kotlinc", "lib")
    if any(os.path.islink(path) for path in (dist_dir, os.path.join(dist_dir, "kotlinc"), lib_dir)):
        raise RuntimeError("Kotlin compiler cache contains a symlink")
    required = {
        "kotlin-compiler.jar": "org/jetbrains/kotlin/cli/jvm/K2JVMCompiler.class",
        "kotlin-stdlib.jar": "kotlin/Unit.class",
    }
    try:
        names = sorted(name for name in os.listdir(lib_dir) if name.endswith(".jar"))
        if not required.keys() <= set(names):
            raise RuntimeError("Kotlin compiler cache is incomplete; remove the invalid distribution and retry")
        paths = []
        for name in names:
            path = os.path.join(lib_dir, name)
            if os.path.islink(path) or not os.path.isfile(path):
                raise RuntimeError("Kotlin compiler cache contains an invalid JAR path")
            with _bounded_zip(path, 100000) as archive:
                members = archive.infolist()
                if len(members) > 100000 or sum(member.file_size for member in members) > 512 * 1024 * 1024:
                    raise RuntimeError("Kotlin compiler JAR exceeds validation limits")
                if archive.testzip() is not None or (name in required and required[name] not in archive.namelist()):
                    raise RuntimeError("Kotlin compiler cache contains an invalid JAR")
            paths.append(path)
        return paths
    except (OSError, zipfile.BadZipFile) as exc:
        raise RuntimeError("Invalid Kotlin compiler cache; remove the invalid distribution and retry") from exc


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
