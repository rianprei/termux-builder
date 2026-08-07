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

    desugar_json = None
    desugar_jar = None
    if getattr(config, "desugar_enabled", False):
        if not use_d8:
            raise RuntimeError("desugar requires d8 (dx does not support --desugared-lib) — install d8: pkg install d8")
        from builder.desugar import setup_desugar_lib
        desugar_json, desugar_jar = setup_desugar_lib(config)
        if not desugar_json:
            raise RuntimeError("desugar: failed to download desugar_jdk_libs — check network, or disable 'desugar' in project.yml")

    if use_d8:
        _run_d8(config, all_classes, desugar_json=desugar_json)
    else:
        _run_dx(config, all_classes)

    _dex_libraries(config, use_d8)

    if desugar_json:
        _dex_desugar_lib(config, desugar_json, desugar_jar)


def _has_d8(config):
    # True only if bin_d8 resolves to the actual d8 binary, not dx fallback
    return os.path.basename(config.bin_d8) == "d8" and shutil.which("d8") is not None


def _run_d8(config, class_files, desugar_json=None):
    args = [config.bin_d8]
    if desugar_json:
        args += ["--desugared-lib", desugar_json]
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

    # build --classpath args for d8 (other libs as classpath context)
    classpath_args = []
    for j in lib_jars:
        classpath_args += ["--classpath", j]

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
                *classpath_args,
                jar,
            ])
        else:
            run([
                "dx", "--dex",
                f"--output={os.path.join(lib_dir, 'classes.dex')}",
                f"--min-sdk-version={config.min_sdk}",
                jar,
            ])


def _dex_desugar_lib(config, desugar_json, desugar_jar):
    """Dex the desugar_jdk_libs runtime backport jar so java.time/streams APIs
    used by the app actually resolve at runtime on old API levels.

    KNOWN LIMITATION: the d8 9.2.4-dev binary packaged in Termux crashes with
    an internal NullPointerException when self-dexing this specific jar
    (verified: same command with --release and --debug both fail with
    'Cannot invoke com.android.tools.r8.graph.a3.g0() because local2 is null').
    App-side desugaring (rewriting java.time calls in your own code) still
    works — only the runtime backport bundling fails. Until a newer d8 is
    packaged in Termux, this raises with a precise, actionable message
    instead of silently shipping a broken APK."""
    from builder.utils import run
    import subprocess
    lib_out = os.path.join(config.dex_dir, "desugar_lib")
    ensure_dir(lib_out)
    try:
        run([
            config.bin_d8,
            "--desugared-lib", desugar_json,
            "--lib", config.android_jar,
            "--min-api", str(config.min_sdk),
            "--output", lib_out,
            f"--{config.build_type}",
            desugar_jar,
        ])
    except subprocess.CalledProcessError:
        raise RuntimeError(
            "desugar: d8 crashed dexing desugar_jdk_libs.jar (known bug in "
            "Termux's d8 9.2.4-dev with this jar). App code was desugared "
            "correctly, but the runtime backport library could not be "
            "bundled — java.time/stream APIs will crash at runtime below "
            "API 26. Set min-sdk: 26 to avoid needing the backport, or "
            "disable 'desugar' in project.yml."
        )
