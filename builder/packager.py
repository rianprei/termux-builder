import os
import shutil
import zipfile
from builder.utils import find_files, log


def package(config, abi=None):
    log.info("Packaging APK%s", f" ({abi})" if abi else "")

    unsigned = os.path.join(config.bin_dir, f"unsigned-{abi}.apk" if abi else "unsigned.apk")
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

        # collect all dex names already added to avoid conflicts
        used_names = {os.path.basename(d) for d in dex_files}
        dex_index = len(dex_files) + 1
        for jar in config.find_lib_jars():
            lib_dir = os.path.dirname(jar)
            lib_dexes = find_files(lib_dir, ".dex")
            for ld in lib_dexes:
                name = f"classes{dex_index}.dex"
                while name in used_names:
                    dex_index += 1
                    name = f"classes{dex_index}.dex"
                apk.write(ld, name)
                used_names.add(name)
                dex_index += 1

        for lib_abi, so_path in config.find_native_libs():
            if abi and lib_abi != abi:
                continue
            arc = f"lib/{lib_abi}/{os.path.basename(so_path)}"
            apk.write(so_path, arc)

    log.info("APK packaged: %s", unsigned)
    return unsigned


def available_abis(config):
    return sorted({a for a, _ in config.find_native_libs()})
