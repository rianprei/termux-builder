import os
import shutil
from builder.utils import run, find_bin, log, color


def decompile(apk_path, output_dir=None, force=False):
    apktool = find_bin("apktool")
    if not apktool:
        raise FileNotFoundError("apktool not found — run: pkg install apktool")

    if not os.path.isfile(apk_path):
        raise FileNotFoundError(f"APK not found: {apk_path}")

    if output_dir is None:
        base = os.path.splitext(os.path.basename(apk_path))[0]
        output_dir = os.path.join(os.path.dirname(os.path.abspath(apk_path)), base + "-decompiled")

    args = [apktool, "d", apk_path, "-o", output_dir]
    if force:
        args.append("-f")

    log.info("Decompiling: %s", apk_path)
    run(args)
    log.info(color("Decompiled to: %s", "green"), output_dir)
    return output_dir


def recompile(project_dir, output_apk=None):
    apktool = find_bin("apktool")
    if not apktool:
        raise FileNotFoundError("apktool not found — run: pkg install apktool")

    if not os.path.isdir(project_dir):
        raise FileNotFoundError(f"Directory not found: {project_dir}")

    if output_apk is None:
        name = os.path.basename(project_dir.rstrip("/"))
        output_apk = os.path.join(project_dir, f"{name}-recompiled.apk")

    args = [apktool, "b", project_dir, "-o", output_apk]

    log.info("Recompiling: %s", project_dir)
    run(args)
    log.info(color("Recompiled APK: %s", "green"), output_apk)
    return output_apk
