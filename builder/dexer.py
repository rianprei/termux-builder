import os
from builder.utils import run, ensure_dir, find_files, log


def dex(config):
    log.info("Converting to DEX (d8)")
    ensure_dir(config.dex_dir)

    java_classes = find_files(config.java_classes_dir, ".class")
    kotlin_classes = find_files(config.kotlin_classes_dir, ".class")
    all_classes = java_classes + kotlin_classes

    if not all_classes:
        raise RuntimeError("No .class files found — compilation may have failed")

    args = [config.bin_d8]

    if config.r8_enabled and config.build_type == "release":
        args = _build_r8_args(config, all_classes)
    else:
        args += [
            f"--{config.build_type}",
            "--min-api", str(config.min_sdk),
            "--lib", config.android_jar,
            "--output", config.dex_dir,
            *all_classes,
        ]

    run(args)
    _dex_libraries(config)


def _build_r8_args(config, class_files):
    log.info("R8 minification enabled")
    args = [
        config.bin_d8,
        "--release",
        "--min-api", str(config.min_sdk),
        "--lib", config.android_jar,
        "--output", config.dex_dir,
    ]

    if config.r8_rules:
        rules_path = os.path.join(config.project_dir, config.r8_rules)
        if os.path.isfile(rules_path):
            args += ["--pg-conf", rules_path]

    args += class_files
    return args


def _dex_libraries(config):
    lib_jars = config.find_lib_jars()
    classpath_args = []
    for jar in lib_jars:
        classpath_args += ["--classpath", jar]

    for jar in lib_jars:
        lib_dir = os.path.dirname(jar)
        existing_dex = find_files(lib_dir, ".dex")
        if existing_dex:
            continue

        log.info("Dexing library: %s", os.path.basename(jar))
        run([
            config.bin_d8,
            f"--{config.build_type}",
            "--min-api", str(config.min_sdk),
            "--lib", config.android_jar,
            "--output", lib_dir,
            jar,
            *classpath_args,
        ])
