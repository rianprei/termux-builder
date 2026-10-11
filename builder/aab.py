import os
import stat
import zipfile
import hashlib
import tempfile
from urllib.parse import urlsplit
import requests
from builder.utils import (
    dex_sort_key, ensure_dir, ensure_output_path, find_bin, find_files, log, run, variant_name,
)

_BUNDLETOOL_VERSION = "1.18.3"
_BUNDLETOOL_URL = f"https://github.com/google/bundletool/releases/download/{_BUNDLETOOL_VERSION}/bundletool-all-{_BUNDLETOOL_VERSION}.jar"
_BUNDLETOOL_SHA256 = "a099cfa1543f55593bc2ed16a70a7c67fe54b1747bb7301f37fdfd6d91028e29"


def _find_bundletool(config):
    local = find_bin("bundletool")
    if local:
        return [local]

    cached = os.path.join(config.cache_dir, "bundletool", f"bundletool-all-{_BUNDLETOOL_VERSION}.jar")
    if os.path.lexists(cached):
        _verify_bundletool(cached)
        java = find_bin("java")
        if not java:
            raise RuntimeError("java not found — needed to run bundletool.jar")
        return [java, "-jar", cached]

    return None


def _download_bundletool(config):
    java = find_bin("java")
    if not java:
        raise RuntimeError("java not found — needed to run bundletool.jar. Install: pkg install openjdk-17")

    out_dir = os.path.join(config.cache_dir, "bundletool")
    if os.path.islink(out_dir):
        raise RuntimeError(f"bundletool cache directory must not be a symlink: {out_dir}")
    out_dir = ensure_dir(out_dir)
    dest = os.path.join(out_dir, f"bundletool-all-{_BUNDLETOOL_VERSION}.jar")
    fd, tmp = tempfile.mkstemp(prefix=".bundletool-", suffix=".tmp", dir=out_dir)

    log.info("Downloading bundletool %s", _BUNDLETOOL_VERSION)
    response = None
    try:
        response = requests.get(_BUNDLETOOL_URL, timeout=120, stream=True, allow_redirects=True)
        response.raise_for_status()
        parsed_url = urlsplit(response.url or _BUNDLETOOL_URL)
        if parsed_url.scheme != "https" or parsed_url.hostname not in {
            "github.com",
            "release-assets.githubusercontent.com",
            "objects.githubusercontent.com",
        }:
            raise RuntimeError("bundletool download redirected outside trusted HTTPS hosts")

        digest = hashlib.sha256()
        file_obj = os.fdopen(fd, "wb")
        fd = None
        with file_obj as f:
            for chunk in response.iter_content(8192):
                if chunk:
                    digest.update(chunk)
                    f.write(chunk)
        actual_digest = digest.hexdigest()
        if actual_digest != _BUNDLETOOL_SHA256:
            raise RuntimeError(
                f"bundletool SHA-256 mismatch: expected {_BUNDLETOOL_SHA256}, got {actual_digest}"
            )
        os.replace(tmp, dest)
    except requests.RequestException as e:
        raise RuntimeError(
            f"bundletool download failed: {e}. "
            f"Manually place bundletool-all-{_BUNDLETOOL_VERSION}.jar at {dest}, "
            "or install a 'bundletool' binary in PATH."
        )
    finally:
        if response is not None:
            response.close()
        if fd is not None:
            os.close(fd)
        if os.path.lexists(tmp):
            os.unlink(tmp)
    return [java, "-jar", dest]


def _verify_bundletool(path):
    if os.path.islink(path) or not os.path.isfile(path):
        raise RuntimeError("cached bundletool is not a regular file")
    digest = hashlib.sha256()
    with open(path, "rb") as jar:
        for chunk in iter(lambda: jar.read(1024 * 1024), b""):
            digest.update(chunk)
    actual_digest = digest.hexdigest()
    if actual_digest != _BUNDLETOOL_SHA256:
        raise RuntimeError(
            f"bundletool SHA-256 mismatch: expected {_BUNDLETOOL_SHA256}, got {actual_digest}"
        )


def build_bundle(config):
    from builder import resources

    bundletool_cmd = _find_bundletool(config) or _download_bundletool(config)

    log.info("Building App Bundle (AAB)")
    bundle_dir = os.path.join(config.build_dir, "bundle")
    ensure_output_path(config.build_dir, bundle_dir, "AAB bundle directory")
    bundle_dir = ensure_dir(bundle_dir)
    base_dir = os.path.join(bundle_dir, "base")
    ensure_output_path(config.build_dir, base_dir, "AAB base module directory")
    base_zip = os.path.join(bundle_dir, "base.zip")
    ensure_output_path(config.build_dir, base_zip, "AAB module archive")
    base_dir = ensure_dir(base_dir)

    proto_res = os.path.join(config.bin_dir, "gen.apk.proto.res")
    resources.link_resources(config, proto_format=True)
    linked = os.path.join(config.bin_dir, "gen.apk.res")
    if os.path.isfile(linked):
        os.replace(linked, proto_res)
    if not os.path.isfile(proto_res):
        raise RuntimeError("aapt2 link --proto-format produced no output — resource linking failed")

    _prepare_base_module(config, base_dir, proto_res)

    _zip_directory(base_dir, base_zip)

    aab_path = _bundle_output_path(config)
    fd, staging_path = tempfile.mkstemp(
        prefix=".bundle-", suffix=".aab", dir=os.path.dirname(aab_path)
    )
    os.close(fd)
    try:
        run(bundletool_cmd + [
            "build-bundle",
            "--modules", base_zip,
            "--output", staging_path,
            "--overwrite",
        ])

        _sign_aab(config, staging_path)
        _verify_aab(staging_path, bundletool_cmd)
        os.replace(staging_path, aab_path)
        staging_path = None
    finally:
        if staging_path and os.path.lexists(staging_path):
            os.unlink(staging_path)

    size_bytes = os.path.getsize(aab_path)
    if size_bytes < 1024:
        size = f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        size = f"{size_bytes / 1024:.1f} KiB"
    else:
        size = f"{size_bytes / (1024 * 1024):.1f} MiB"
    log.info("AAB: %s (%s)", aab_path, size)
    return aab_path


def _bundle_output_path(config):
    output_name = f"{variant_name(config)}-{config.build_type}.aab"
    if (
        not output_name
        or "\x00" in output_name
        or "/" in output_name
        or "\\" in output_name
    ):
        raise ValueError("AAB output name must not contain path separators")

    output_path = os.path.join(config.build_dir, output_name)
    return ensure_output_path(config.build_dir, output_path, "AAB output path")


def _sign_aab(config, aab_path):
    """AAB is a JAR-format archive, signed with jarsigner (not apksigner —
    apksigner targets the APK v2/v3 signature scheme, which does not apply
    to .aab; Play Console re-signs on upload, but a local jarsigner
    signature is required for bundletool's own validate/build-apks flows
    that check signatures)."""
    if not os.path.isfile(config.keystore_path):
        raise FileNotFoundError(f"Keystore not found: {config.keystore_path}")
    jarsigner = find_bin("jarsigner")
    if not jarsigner:
        raise RuntimeError("jarsigner not found — install: pkg install openjdk-17")

    env = os.environ.copy()
    env["_TB_KS_PASS"] = config.keystore_store_pass
    env["_TB_KEY_PASS"] = config.keystore_key_pass

    log.info("Signing AAB with jarsigner")
    run([
        jarsigner,
        "-keystore", config.keystore_path,
        "-storepass:env", "_TB_KS_PASS",
        "-keypass:env", "_TB_KEY_PASS",
        "-sigalg", "SHA256withRSA",
        "-digestalg", "SHA-256",
        aab_path,
        config.keystore_alias,
    ], env=env)


def _verify_aab(aab_path, bundletool_cmd=None):
    required_entries = {
        "BundleConfig.pb",
        "base/manifest/AndroidManifest.xml",
        "base/resources.pb",
    }
    try:
        with zipfile.ZipFile(aab_path) as bundle:
            present_entries = set(bundle.namelist())
    except (OSError, zipfile.BadZipFile) as e:
        raise RuntimeError(f"AAB is not a readable ZIP archive: {e}")

    missing = sorted(required_entries - present_entries)
    if missing:
        raise RuntimeError(f"AAB is missing required entries: {', '.join(missing)}")

    if bundletool_cmd:
        run(bundletool_cmd + ["validate", "--bundle", aab_path], capture=True)

    jarsigner = find_bin("jarsigner")
    if not jarsigner:
        raise RuntimeError("jarsigner not found — install: pkg install openjdk-17")
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    result = run([jarsigner, "-verify", aab_path], capture=True, env=env)
    if "jar verified" not in (result.stdout or "").lower():
        raise RuntimeError("AAB signature verification failed: jarsigner did not verify the bundle")
    log.info("AAB structure and signature verified; certificate trust was not checked")


def _prepare_base_module(config, base_dir, proto_apk_path):
    """Build the bundletool base module zip layout from a real
    aapt2 link --proto-format output (a valid proto-format APK zip
    containing AndroidManifest.xml, resources.pb, res/)."""
    import shutil

    if os.path.islink(base_dir):
        raise ValueError("AAB base module directory must not be a symlink")
    if getattr(config, "build_dir", None):
        build_real = os.path.realpath(config.build_dir)
        base_real = os.path.realpath(base_dir)
        try:
            contained = os.path.commonpath((build_real, base_real)) == build_real
        except ValueError:
            contained = False
        if not contained or build_real == base_real:
            raise ValueError("AAB base module path is outside the configured build directory")
    if os.path.isdir(base_dir):
        shutil.rmtree(base_dir)
    elif os.path.lexists(base_dir):
        os.remove(base_dir)
    os.makedirs(base_dir)

    manifest_dir = ensure_dir(os.path.join(base_dir, "manifest"))
    dex_dir = ensure_dir(os.path.join(base_dir, "dex"))

    base_real = os.path.realpath(base_dir)
    with zipfile.ZipFile(proto_apk_path) as z:
        for member in z.infolist():
            member_path = os.path.realpath(os.path.join(base_real, member.filename))
            if os.path.commonpath((base_real, member_path)) != base_real:
                raise ValueError(f"Unsafe archive member path: {member.filename}")
            if stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError(f"Unsafe archive member symlink: {member.filename}")
            z.extract(member, base_real)

    # proto apk has AndroidManifest.xml at root — bundletool wants it under manifest/
    root_manifest = os.path.join(base_dir, "AndroidManifest.xml")
    if os.path.isfile(root_manifest):
        shutil.move(root_manifest, os.path.join(manifest_dir, "AndroidManifest.xml"))

    if not os.path.isfile(os.path.join(base_dir, "resources.pb")):
        raise RuntimeError("resources.pb missing from proto-format link output — AAB requires aapt2 with proto support")

    app_dex_files = find_files(config.dex_dir, ".dex")
    app_dex_files.sort(key=dex_sort_key)
    library_dex_files = []
    library_dex_dir = getattr(config, "library_dex_dir", None)
    if library_dex_dir and os.path.islink(library_dex_dir):
        raise RuntimeError(f"Library DEX cache must not be a symlink: {library_dex_dir}")
    if library_dex_dir and not os.path.isdir(library_dex_dir):
        raise RuntimeError("Library DEX cache disappeared before AAB packaging; rerun the build")
    if library_dex_dir:
        library_dex_files = find_files(library_dex_dir, ".dex")
        library_dex_files.sort(key=dex_sort_key)

    used_dex_names = set()
    next_dex_index = 2
    for dex in app_dex_files + library_dex_files:
        name = os.path.basename(dex)
        if name in used_dex_names:
            name = f"classes{next_dex_index}.dex"
            while name in used_dex_names:
                next_dex_index += 1
                name = f"classes{next_dex_index}.dex"
            next_dex_index += 1
        shutil.copy2(dex, os.path.join(dex_dir, name))
        used_dex_names.add(name)

    native_libs = config.find_native_libs() if hasattr(config, "find_native_libs") else []
    if native_libs:
        lib_dir = ensure_dir(os.path.join(base_dir, "lib"))
        for abi, so_path in native_libs:
            abi_dir = ensure_dir(os.path.join(lib_dir, abi))
            shutil.copy2(so_path, os.path.join(abi_dir, os.path.basename(so_path)))


def _zip_directory(source_dir, output_zip):
    output_dir = os.path.dirname(os.path.abspath(output_zip))
    fd, tmp = tempfile.mkstemp(prefix=".bundle-", suffix=".zip", dir=output_dir)
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(source_dir):
                for directory in dirs:
                    full = os.path.join(root, directory)
                    if os.path.islink(full):
                        raise ValueError(f"Bundle module contains a symlink: {full}")
                dirs.sort()
                for name in sorted(files):
                    full = os.path.join(root, name)
                    if os.path.abspath(full) in {os.path.abspath(tmp), os.path.abspath(output_zip)}:
                        continue
                    if os.path.islink(full):
                        raise ValueError(f"Bundle module contains a symlink: {full}")
                    arc = os.path.relpath(full, source_dir).replace(os.sep, "/")
                    info = zipfile.ZipInfo(arc, (1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.create_system = 3
                    info.external_attr = 0o100644 << 16
                    with open(full, "rb") as source:
                        zf.writestr(info, source.read())
        os.replace(tmp, output_zip)
    finally:
        if os.path.lexists(tmp):
            os.unlink(tmp)
