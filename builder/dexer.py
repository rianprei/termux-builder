import os
import shutil
from builder.utils import run, ensure_dir, find_files, log


def dex(config):
    log.info("Converting to DEX")
    ensure_dir(config.dex_dir)

    java_classes = find_files(config.java_classes_dir, ".class")
    kotlin_classes = find_files(config.kotlin_classes_dir, ".class")
    all_classes = java_classes + kotlin_classes

    if not all_classes:
        raise RuntimeError("No .class files found — compilation may have failed")

    use_d8 = _has_d8(config)

    if use_d8:
        _run_d8(config, all_classes)
    else:
        _run_dx(config, all_classes)

    _dex_libraries(config, use_d8)


def _has_d8(config):
    # True only if bin_d8 resolves to the actual d8 binary, not dx fallback
    return os.path.basename(config.bin_d8) == "d8" and shutil.which("d8") is not None


def _run_d8(config, class_files):
    args = [config.bin_d8]
    if config.r8_enabled and config.build_type == "release":
        log.info("R8 minification enabled")
        args += ["--release"]
        if config.r8_rules:
            rules_path = os.path.join(config.project_dir, config.r8_rules)
            if os.path.isfile(rules_path):
                args += ["--pg-conf", rules_path]
    else:
        args += [f"--{config.build_type}"]

    args += [
        "--min-api", str(config.min_sdk),
        "--lib", config.android_jar,
        "--output", config.dex_dir,
        *class_files,
    ]
    run(args)


def _run_dx(config, class_files):
    log.info("Using dx (legacy dexer)")
    out_dex = os.path.join(config.dex_dir, "classes.dex")

    # dx needs a directory or jar — write classes into a temp jar
    import zipfile, tempfile
    tmp_jar = os.path.join(config.build_dir, "classes_for_dx.jar")
    with zipfile.ZipFile(tmp_jar, "w", zipfile.ZIP_DEFLATED) as zf:
        for cls in class_files:
            # find relative path from java_classes_dir or kotlin_classes_dir
            for base in (config.java_classes_dir, config.kotlin_classes_dir):
                if cls.startswith(base):
                    arc = os.path.relpath(cls, base)
                    zf.write(cls, arc)
                    break

    run([
        "dx", "--dex",
        f"--output={out_dex}",
        f"--min-sdk-version={config.min_sdk}",
        tmp_jar,
    ])


def _dex_libraries(config, use_d8):
    lib_jars = config.find_lib_jars()
    if not lib_jars:
        return

    for jar in lib_jars:
        lib_dir = os.path.dirname(jar)
        if find_files(lib_dir, ".dex"):
            continue

        log.info("Dexing library: %s", os.path.basename(jar))
        if use_d8:
            run([
                config.bin_d8,
                f"--{config.build_type}",
                "--min-api", str(config.min_sdk),
                "--lib", config.android_jar,
                "--output", lib_dir,
                jar,
            ])
        else:
            run([
                "dx", "--dex",
                f"--output={os.path.join(lib_dir, 'classes.dex')}",
                f"--min-sdk-version={config.min_sdk}",
                jar,
            ])
