import os
import shutil
import zipfile
from builder.utils import find_files, log


def package(config):
    log.info("Packaging APK")

    unsigned = os.path.join(config.bin_dir, "unsigned.apk")
    base_apk = os.path.join(config.bin_dir, "gen.apk.res")

    if not os.path.isfile(base_apk):
        raise FileNotFoundError("Resource APK not found — aapt2 link may have failed")

    shutil.copy2(base_apk, unsigned)

    with zipfile.ZipFile(unsigned, "a", zipfile.ZIP_DEFLATED) as apk:
        dex_files = sorted(find_files(config.dex_dir, ".dex"))
        if not dex_files:
            raise RuntimeError("No DEX files found")

        for dex in dex_files:
            apk.write(dex, os.path.basename(dex))

        dex_index = len(dex_files) + 1
        for jar in config.find_lib_jars():
            lib_dir = os.path.dirname(jar)
            lib_dexes = find_files(lib_dir, ".dex")
            for ld in lib_dexes:
                apk.write(ld, f"classes{dex_index}.dex")
                dex_index += 1

        for abi, so_path in config.find_native_libs():
            arc = f"lib/{abi}/{os.path.basename(so_path)}"
            apk.write(so_path, arc)

    log.info("APK packaged: %s", unsigned)
    return unsigned
