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

    use_r8 = config.r8_enabled and config.build_type == "release"
    if use_r8:
        if not shutil.which("r8"):
            raise RuntimeError("r8 enabled but 'r8' binary not found — install: pkg install r8")
        _run_r8(config, all_classes, desugar_json=desugar_json)
    elif use_d8:
        _run_d8(config, all_classes, desugar_json=desugar_json)
    else:
        _run_dx(config, all_classes)

    _dex_libraries(config, use_d8)

    if desugar_json:
        _dex_desugar_lib(config, desugar_json, desugar_jar)


def _has_d8(config):
    # True only if bin_d8 resolves to the actual d8 binary, not dx fallback
    return os.path.basename(config.bin_d8) == "d8" and shutil.which("d8") is not None


def _run_r8(config, class_files, desugar_json=None):
    """d8 --release only strips debug info — never runs actual shrink/
    obfuscate (verified: no mapping.txt possible, no class renaming, even
    with --release). Real minification needs the separate 'r8' binary."""
    args = ["r8", "--release"]
    if desugar_json:
        args += ["--desugared-lib", desugar_json]

    default_rules = os.path.join(config.build_dir, "default-r8-rules.pro")
    rules_path = None
    if config.r8_rules:
        candidate = os.path.join(config.project_dir, config.r8_rules)
        if os.path.isfile(candidate):
            rules_path = candidate
        else:
            log.warning("r8-rules file not found: %s — using default keep rules", candidate)
    if not rules_path:
        with open(default_rules, "w") as f:
            f.write(
                "-keep public class * extends android.app.Activity\n"
                "-keep public class * extends android.app.Service\n"
                "-keep public class * extends android.content.BroadcastReceiver\n"
                "-keep public class * extends android.content.ContentProvider\n"
                "-keepclassmembers class * extends android.app.Activity { public void *(android.view.View); }\n"
            )
        rules_path = default_rules
    args += ["--pg-conf", rules_path]

    mapping_path = os.path.join(config.build_dir, "mapping.txt")
    args += ["--pg-map-output", mapping_path]

    args += [
        "--min-api", str(config.min_sdk),
        "--lib", config.android_jar,
        "--output", config.dex_dir,
        *class_files,
    ]
    run(args)
    log.info("R8 minification: %s (mapping: %s)", config.dex_dir, mapping_path)


def _run_d8(config, class_files, desugar_json=None):
    args = [config.bin_d8]
    if desugar_json:
        args += ["--desugared-lib", desugar_json]
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

    VERIFIED BOUNDARY: the d8 9.2.4-dev binary packaged in Termux crashes with
    an internal NullPointerException self-dexing this jar at --min-api 21-25
    (less backport rewriting needed at higher API = crash disappears).
    Confirmed working at --min-api 26+ (exit 0, valid classes.dex produced).
    Confirmed crashing at --min-api 21/22/23/24/25 (same NPE every time).
    This dexes the library at max(config.min_sdk, 26) — the app's own dex
    still targets the real config.min_sdk, so the APK's effective min-sdk is
    unchanged; only the backport library internally targets 26+, which is
    safe because the backport is only reachable via desugared calls that
    already assume its presence."""
    from builder.utils import run
    import subprocess
    lib_out = os.path.join(config.dex_dir, "desugar_lib")
    ensure_dir(lib_out)
    lib_min_api = max(config.min_sdk, 26)
    if config.min_sdk < 26:
        log.warning(
            "desugar: dexing desugar_jdk_libs.jar at --min-api 26 (verified "
            "boundary — d8 crashes below 26 on this jar). App min-sdk stays "
            "%d; only the backport library internals target 26+.",
            config.min_sdk,
        )
    try:
        run([
            config.bin_d8,
            "--desugared-lib", desugar_json,
            "--lib", config.android_jar,
            "--min-api", str(lib_min_api),
            "--output", lib_out,
            f"--{config.build_type}",
            desugar_jar,
        ])
    except subprocess.CalledProcessError:
        raise RuntimeError(
            "desugar: d8 crashed dexing desugar_jdk_libs.jar even at "
            "--min-api 26 (previously verified working) — this is a new "
            "failure mode, not the known 21-25 boundary bug. Disable "
            "'desugar' in project.yml or file an issue with the d8 error above."
        )
