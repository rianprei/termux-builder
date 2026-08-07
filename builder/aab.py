import os
import zipfile
from builder.utils import run, find_bin, find_files, ensure_dir, log


def build_bundle(config):
    raise NotImplementedError(
        "AAB output disabled — res.zip (aapt2 compile) is not resources.pb "
        "(aapt2 link --proto-format), bundle would be invalid. "
        "Use termux-builder build for APK output."
    )
    bundletool = find_bin("bundletool") or find_bin("bundletool.jar")
    java = find_bin("java")

    if not bundletool:
        log.warning("bundletool not found — install via: pip install bundletool or download bundletool.jar")
        log.info("Falling back to APK output")
        return None

    if not java:
        log.error("java not found — needed for bundletool")
        return None

    log.info("Building App Bundle (AAB)")
    bundle_dir = ensure_dir(os.path.join(config.build_dir, "bundle"))

    base_dir = ensure_dir(os.path.join(bundle_dir, "base"))
    _prepare_base_module(config, base_dir)

    base_zip = os.path.join(bundle_dir, "base.zip")
    _zip_directory(base_dir, base_zip)

    output_name = f"{config.name}-{config.build_type}.aab"
    aab_path = os.path.join(config.build_dir, output_name)

    if bundletool.endswith(".jar"):
        cmd = [java, "-jar", bundletool]
    else:
        cmd = [bundletool]

    cmd += [
        "build-bundle",
        "--modules", base_zip,
        "--output", aab_path,
    ]

    run(cmd)

    size_mb = os.path.getsize(aab_path) / (1024 * 1024)
    log.info("AAB: %s (%.1f MB)", aab_path, size_mb)
    return aab_path


def _prepare_base_module(config, base_dir):
    manifest_dir = ensure_dir(os.path.join(base_dir, "manifest"))
    dex_dir = ensure_dir(os.path.join(base_dir, "dex"))
    res_dir = ensure_dir(os.path.join(base_dir, "res"))

    import shutil
    manifest_src = os.path.join(config.build_dir, "AndroidManifest.xml")
    if not os.path.isfile(manifest_src):
        manifest_src = config.manifest_path
    shutil.copy2(manifest_src, os.path.join(manifest_dir, "AndroidManifest.xml"))

    for dex in find_files(config.dex_dir, ".dex"):
        shutil.copy2(dex, os.path.join(dex_dir, os.path.basename(dex)))

    # NOTE: bundletool requires resources.pb (aapt2 link --proto-format output).
    # res.zip here is aapt2 *compile* output — not the same format.
    # Full AAB support requires a separate aapt2 link --proto-format step.
    compiled_res = os.path.join(config.compiled_res_dir, "res.zip")
    if os.path.isfile(compiled_res):
        log.warning("AAB: res.zip is compile output, not resources.pb — bundle may be invalid")
        with zipfile.ZipFile(compiled_res) as z:
            z.extractall(res_dir)

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
