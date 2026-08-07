import os
import zipfile
import requests
from builder.utils import run, find_bin, find_files, ensure_dir, log

_BUNDLETOOL_VERSION = "1.18.3"
_BUNDLETOOL_URL = f"https://github.com/google/bundletool/releases/download/{_BUNDLETOOL_VERSION}/bundletool-all-{_BUNDLETOOL_VERSION}.jar"


def _find_bundletool(config):
    local = find_bin("bundletool")
    if local:
        return [local]

    cached = os.path.join(config.cache_dir, "bundletool", f"bundletool-all-{_BUNDLETOOL_VERSION}.jar")
    if os.path.isfile(cached):
        java = find_bin("java")
        if not java:
            raise RuntimeError("java not found — needed to run bundletool.jar")
        return [java, "-jar", cached]

    return None


def _download_bundletool(config):
    java = find_bin("java")
    if not java:
        raise RuntimeError("java not found — needed to run bundletool.jar. Install: pkg install openjdk-17")

    out_dir = ensure_dir(os.path.join(config.cache_dir, "bundletool"))
    dest = os.path.join(out_dir, f"bundletool-all-{_BUNDLETOOL_VERSION}.jar")
    tmp = dest + ".tmp"

    log.info("Downloading bundletool %s", _BUNDLETOOL_VERSION)
    try:
        r = requests.get(_BUNDLETOOL_URL, timeout=120, stream=True)
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        os.rename(tmp, dest)
    except requests.RequestException as e:
        raise RuntimeError(
            f"bundletool download failed: {e}. "
            f"Manually place bundletool-all-{_BUNDLETOOL_VERSION}.jar at {dest}, "
            "or install a 'bundletool' binary in PATH."
        )
    return [java, "-jar", dest]


def build_bundle(config):
    from builder import resources

    bundletool_cmd = _find_bundletool(config) or _download_bundletool(config)

    log.info("Building App Bundle (AAB)")
    bundle_dir = ensure_dir(os.path.join(config.build_dir, "bundle"))

    proto_res = os.path.join(config.bin_dir, "gen.apk.proto.res")
    resources.link_resources(config, proto_format=True)
    linked = os.path.join(config.bin_dir, "gen.apk.res")
    if os.path.isfile(linked):
        os.replace(linked, proto_res)
    if not os.path.isfile(proto_res):
        raise RuntimeError("aapt2 link --proto-format produced no output — resource linking failed")

    base_dir = ensure_dir(os.path.join(bundle_dir, "base"))
    _prepare_base_module(config, base_dir, proto_res)

    base_zip = os.path.join(bundle_dir, "base.zip")
    _zip_directory(base_dir, base_zip)

    output_name = f"{config.name}-{config.build_type}.aab"
    aab_path = os.path.join(config.build_dir, output_name)

    run(bundletool_cmd + [
        "build-bundle",
        "--modules", base_zip,
        "--output", aab_path,
        "--overwrite",
    ])

    size_mb = os.path.getsize(aab_path) / (1024 * 1024)
    log.info("AAB: %s (%.1f MB)", aab_path, size_mb)
    return aab_path


def _prepare_base_module(config, base_dir, proto_apk_path):
    """Build the bundletool base module zip layout from a real
    aapt2 link --proto-format output (a valid proto-format APK zip
    containing AndroidManifest.xml, resources.pb, res/)."""
    import shutil

    manifest_dir = ensure_dir(os.path.join(base_dir, "manifest"))
    dex_dir = ensure_dir(os.path.join(base_dir, "dex"))

    with zipfile.ZipFile(proto_apk_path) as z:
        z.extractall(base_dir)

    # proto apk has AndroidManifest.xml at root — bundletool wants it under manifest/
    root_manifest = os.path.join(base_dir, "AndroidManifest.xml")
    if os.path.isfile(root_manifest):
        shutil.move(root_manifest, os.path.join(manifest_dir, "AndroidManifest.xml"))

    if not os.path.isfile(os.path.join(base_dir, "resources.pb")):
        raise RuntimeError("resources.pb missing from proto-format link output — AAB requires aapt2 with proto support")

    for dex in find_files(config.dex_dir, ".dex"):
        shutil.copy2(dex, os.path.join(dex_dir, os.path.basename(dex)))

    if os.path.isdir(config.jni_dir):
        lib_dir = ensure_dir(os.path.join(base_dir, "lib"))
        for abi, so_path in config.find_native_libs():
            abi_dir = ensure_dir(os.path.join(lib_dir, abi))
            shutil.copy2(so_path, os.path.join(abi_dir, os.path.basename(so_path)))

    if os.path.isdir(config.assets_dir):
        assets_dest = ensure_dir(os.path.join(base_dir, "assets"))
        for root, _, files in os.walk(config.assets_dir):
            for f in files:
                src = os.path.join(root, f)
                rel = os.path.relpath(src, config.assets_dir)
                dest = os.path.join(assets_dest, rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(src, dest)


def _zip_directory(source_dir, output_zip):
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(source_dir):
            for f in files:
                full = os.path.join(root, f)
                arc = os.path.relpath(full, source_dir)
                zf.write(full, arc)
