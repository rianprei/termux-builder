import os
import shutil
import xml.etree.ElementTree as ET
from builder.utils import run, ensure_dir, find_files, log

# System android.jar (Termux native package)
_SYSTEM_ANDROID_JAR = "/data/data/com.termux/files/usr/share/java/android.jar"


def _resolve_android_jar(config):
    # config.py already resolves config.android_jar to the system jar when
    # no SDK is configured, so that path is checked once here (no dead branch).
    if os.path.isfile(config.android_jar):
        if config.android_jar == _SYSTEM_ANDROID_JAR:
            log.warning(
                "Using system android.jar — aapt2 link will fail with themes. "
                "Run: termux-builder setup"
            )
        return config.android_jar
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

    res_dirs = config.find_res_dirs() if hasattr(config, "find_res_dirs") else [config.res_dir]
    for i, res_dir in enumerate(res_dirs):
        out = os.path.join(config.compiled_res_dir, "res.zip" if i == 0 else f"res-flavor{i}.zip")
        run([config.bin_aapt2, "compile", "--dir", res_dir, "-o", out])

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


_DENSITY_BUCKETS = {
    "ldpi": "ldpi", "mdpi": "mdpi", "hdpi": "hdpi",
    "xhdpi": "xhdpi", "xxhdpi": "xxhdpi", "xxxhdpi": "xxxhdpi",
}


def link_resources(config, proto_format=False):
    android_jar = _resolve_android_jar(config)

    if _has_aapt2(config):
        return _link_aapt2(config, android_jar, proto_format=proto_format)
    else:
        _link_aapt1(config, android_jar)
        return None


def _link_aapt2(config, android_jar, proto_format=False):
    log.info("Linking resources (aapt2)")
    # clean gen_dir so stale R.java from old package names is removed
    import shutil
    if os.path.isdir(config.gen_dir):
        shutil.rmtree(config.gen_dir)
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

    if proto_format:
        args.append("--proto-format")

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

    split_paths = []
    if getattr(config, "density_splits", False) and not proto_format:
        split_dir = ensure_dir(os.path.join(config.bin_dir, "splits"))
        for density in _DENSITY_BUCKETS:
            split_path = os.path.join(split_dir, f"split-{density}.apk")
            args += ["--split", f"{split_path}:density={_DENSITY_BUCKETS[density]}"]
            split_paths.append((density, split_path))

    run(args)
    return split_paths


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
