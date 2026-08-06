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
