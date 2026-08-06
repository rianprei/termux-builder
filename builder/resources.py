import os
import shutil
import xml.etree.ElementTree as ET
from builder.utils import run, ensure_dir, find_files, log


def compile_resources(config):
    log.info("Compiling resources (aapt2)")
    ensure_dir(config.compiled_res_dir)

    run([
        config.bin_aapt2, "compile",
        "--dir", config.res_dir,
        "-o", os.path.join(config.compiled_res_dir, "res.zip"),
    ])

    for jar in config.find_lib_jars():
        lib_dir = os.path.dirname(jar)
        lib_name = os.path.basename(lib_dir)
        res = os.path.join(lib_dir, "res")
        if not os.path.isdir(res):
            continue
        out = os.path.join(config.compiled_res_dir, f"{lib_name}.zip")
        if os.path.exists(out):
            continue
        run([config.bin_aapt2, "compile", "--dir", res, "-o", out])


def link_resources(config):
    log.info("Linking resources (aapt2)")
    ensure_dir(config.gen_dir)

    args = [
        config.bin_aapt2, "link",
        "--allow-reserved-package-id",
        "--no-version-vectors",
        "--no-version-transitions",
        "--auto-add-overlay",
        "--min-sdk-version", str(config.min_sdk),
        "--target-sdk-version", str(config.target_sdk),
        "--version-code", str(config.version_code),
        "--version-name", config.version_name,
        "-I", config.android_jar,
    ]

    if os.path.isdir(config.assets_dir):
        args += ["-A", config.assets_dir]

    for f in os.listdir(config.compiled_res_dir):
        if f.endswith(".zip"):
            args += ["-R", os.path.join(config.compiled_res_dir, f)]

    extra_packages = _get_lib_packages(config)
    if extra_packages:
        args += ["--extra-packages", extra_packages]

    output_res = os.path.join(config.bin_dir, "gen.apk.res")
    args += [
        "--java", config.gen_dir,
        "--manifest", config.manifest_path,
        "-o", output_res,
    ]

    run(args)


def _get_lib_packages(config):
    packages = set()
    if not os.path.isdir(config.libs_dir):
        return ""
    for root, _, files in os.walk(config.libs_dir):
        for f in files:
            if f != "AndroidManifest.xml":
                continue
            path = os.path.join(root, f)
            pkg = ET.parse(path).getroot().attrib.get("package")
            if pkg:
                packages.add(pkg)
    return ":".join(sorted(packages))
