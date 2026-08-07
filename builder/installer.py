import os
from builder.utils import run, find_bin, log


def install(apk_path, device=None):
    adb = find_bin("adb") or find_bin("termux-adb")
    if not adb:
        raise FileNotFoundError("adb not found — install termux-adb or add adb to PATH")

    if not os.path.isfile(apk_path):
        raise FileNotFoundError(f"APK not found: {apk_path}")

    log.info("Installing APK via adb")

    args = [adb]
    if device:
        args += ["-s", device]
    args += ["install", "-r", apk_path]

    run(args)
    log.info("APK installed successfully")


def install_multiple(apk_paths, device=None):
    """Install a base APK together with density/ABI split APKs — real
    'adb install-multiple' path, required because split APKs are not
    independently installable (they carry only a subset of resources
    and must share package name + signing cert with the base)."""
    adb = find_bin("adb") or find_bin("termux-adb")
    if not adb:
        raise FileNotFoundError("adb not found — install termux-adb or add adb to PATH")

    for p in apk_paths:
        if not os.path.isfile(p):
            raise FileNotFoundError(f"APK not found: {p}")

    log.info("Installing %d APKs via adb install-multiple", len(apk_paths))

    args = [adb]
    if device:
        args += ["-s", device]
    args += ["install-multiple", "-r", *apk_paths]

    run(args)
    log.info("Split APKs installed successfully")
