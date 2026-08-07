import os
import shutil
import xml.etree.ElementTree as ET
from builder.utils import run, ensure_dir, find_files, log

# System android.jar (Termux native package)
_SYSTEM_ANDROID_JAR = "/data/data/com.termux/files/usr/share/java/android.jar"


def _resolve_android_jar(config):
    if os.path.isfile(config.android_jar):
        return config.android_jar
    if os.path.isfile(_SYSTEM_ANDROID_JAR):
        log.info("Using system android.jar: %s", _SYSTEM_ANDROID_JAR)
        return _SYSTEM_ANDROID_JAR
    raise FileNotFoundError(
        "android.jar not found. Run: termux-builder setup"
    )


def _has_aapt2(config):
    return shutil.which("aapt2") is not None or (
        config.bin_aapt2 != "aapt2" and os.path.isfile(config.bin_aapt2)
    )


def compile_resources(config):
    if _has_aapt2(config):
        _compile_aapt2(config)
    else:
        _compile_aapt1(config)


def _compile_aapt2(config):
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


def _compile_aapt1(config):
    """aapt v1 fallback — simpler, no compile step needed."""
    log.info("Using aapt (v1 fallback)")
    # aapt v1 compiles+links in one step — nothing to do here
    ensure_dir(config.compiled_res_dir)


def link_resources(config):
    android_jar = _resolve_android_jar(config)

    if _has_aapt2(config):
        _link_aapt2(config, android_jar)
    else:
        _link_aapt1(config, android_jar)


def _link_aapt2(config, android_jar):
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
        "-I", android_jar,
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


def _link_aapt1(config, android_jar):
    """aapt v1 package — compile + link in one shot."""
    log.info("Linking resources (aapt v1)")
    ensure_dir(config.gen_dir)
    output_res = os.path.join(config.bin_dir, "gen.apk.res")

    args = [
        "aapt", "package",
        "-f",
        "--generate-dependencies",
        "-J", config.gen_dir,
        "--min-sdk-version", str(config.min_sdk),
        "--target-sdk-version", str(config.target_sdk),
        "--version-code", str(config.version_code),
        "--version-name", config.version_name,
        "-M", config.manifest_path,
        "-S", config.res_dir,
        "-I", android_jar,
        "-F", output_res,
    ]

    if os.path.isdir(config.assets_dir):
        args += ["-A", config.assets_dir]

    run(args)


def _get_lib_packages(config):
    packages = set()
    if not os.path.isdir(config.libs_dir):
        return ""
    for root, _, files in os.walk(config.libs_dir):
        for f in files:
            if f != "AndroidManifest.xml":
                continue
            pkg = ET.parse(os.path.join(root, f)).getroot().attrib.get("package")
            if pkg:
                packages.add(pkg)
    return ":".join(sorted(packages))
