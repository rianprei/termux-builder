import hashlib
import json
import os
import shutil
import tempfile
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


def _remove_stale_library_dex_staging(cache_root):
    try:
        entries = list(os.scandir(cache_root))
    except FileNotFoundError:
        return
    for entry in entries:
        prefix = ".library-dex-"
        if not entry.name.startswith(prefix) or entry.is_symlink():
            continue
        pid_text, separator, _ = entry.name[len(prefix):].partition("-")
        if not separator or not pid_text.isdigit() or int(pid_text) == os.getpid():
            continue
        try:
            os.kill(int(pid_text), 0)
        except ProcessLookupError:
            if entry.is_dir(follow_symlinks=False):
                shutil.rmtree(entry.path)
            else:
                os.unlink(entry.path)
        except PermissionError:
            continue


def _dex_libraries(config, use_d8):
    lib_jars = sorted(config.find_lib_jars())
    if not lib_jars:
        config.library_dex_dir = None
        return

    cache_root = os.path.join(config.cache_dir, "library-dex")
    if os.path.islink(config.cache_dir) or os.path.islink(cache_root):
        raise RuntimeError(f"Library DEX cache directory must not be a symlink: {cache_root}")
    ensure_dir(cache_root)
    _remove_stale_library_dex_staging(cache_root)

    fingerprint = _library_dex_fingerprint(config, lib_jars, use_d8)
    cache_dir = os.path.join(cache_root, fingerprint)
    if os.path.islink(cache_dir):
        raise RuntimeError(f"Library DEX cache entry must not be a symlink: {cache_dir}")
    if _valid_library_dex_cache(cache_dir, fingerprint):
        config.library_dex_dir = cache_dir
        return

    # build --classpath args for d8 (other libs as classpath context)
    classpath_args = []
    for j in lib_jars:
        classpath_args += ["--classpath", j]

    staging_dir = tempfile.mkdtemp(prefix=f".library-dex-{os.getpid()}-", dir=cache_root)
    try:
        for index, jar in enumerate(lib_jars):
            output_dir = os.path.join(staging_dir, f"lib-{index:04d}")
            ensure_dir(output_dir)
            log.info("Dexing library: %s", os.path.basename(jar))
            if use_d8:
                run([
                    config.bin_d8,
                    f"--{config.build_type}",
                    "--min-api", str(config.min_sdk),
                    "--lib", config.android_jar,
                    "--output", output_dir,
                    *classpath_args,
                    jar,
                ])
            else:
                run([
                    "dx", "--dex",
                    f"--output={os.path.join(output_dir, 'classes.dex')}",
                    f"--min-sdk-version={config.min_sdk}",
                    jar,
                ])

        dex_outputs = sorted(find_files(staging_dir, ".dex"))
        manifest = {
            "schema_version": 1,
            "fingerprint": fingerprint,
            "outputs": [
                {
                    "path": os.path.relpath(path, staging_dir).replace(os.sep, "/"),
                    "sha256": _sha256_file(path),
                }
                for path in dex_outputs
            ],
        }
        manifest_path = os.path.join(staging_dir, ".termux-builder-dex.json")
        with open(manifest_path, "w") as output:
            json.dump(manifest, output, sort_keys=True, separators=(",", ":"))

        if _valid_library_dex_cache(cache_dir, fingerprint):
            config.library_dex_dir = cache_dir
            return
        if os.path.lexists(cache_dir):
            if os.path.islink(cache_dir):
                raise RuntimeError(f"Library DEX cache entry must not be a symlink: {cache_dir}")
            if os.path.isdir(cache_dir):
                shutil.rmtree(cache_dir)
            else:
                os.remove(cache_dir)
        os.replace(staging_dir, cache_dir)
        staging_dir = None
    finally:
        if staging_dir is not None:
            shutil.rmtree(staging_dir, ignore_errors=True)

    config.library_dex_dir = cache_dir


def _library_dex_fingerprint(config, lib_jars, use_d8):
    tool = config.bin_d8 if use_d8 else "dx"
    resolved_tool = shutil.which(tool) or tool
    tool_files = [resolved_tool]
    tool_name = os.path.basename(resolved_tool)
    sidecar = "d8.jar" if tool_name == "d8" else "dx.jar" if tool_name == "dx" else None
    if sidecar:
        tool_files.append(os.path.join(os.path.dirname(resolved_tool), "lib", sidecar))
    tool_identity = {"path": os.path.realpath(resolved_tool), "files": []}
    for path in tool_files:
        if os.path.isfile(path):
            tool_identity["files"].append({
                "path": os.path.realpath(path),
                "sha256": _sha256_file(path),
            })

    inputs = []
    for jar in lib_jars:
        try:
            relative_path = os.path.relpath(jar, config.libs_dir)
        except ValueError:
            relative_path = os.path.abspath(jar)
        inputs.append({"path": relative_path.replace(os.sep, "/"), "sha256": _sha256_file(jar)})

    fingerprint_data = {
        "schema_version": 1,
        "tool": tool_identity,
        "use_d8": use_d8,
        "build_type": config.build_type,
        "min_sdk": config.min_sdk,
        "android_jar_sha256": _sha256_file(config.android_jar),
        "libraries": inputs,
    }
    encoded = json.dumps(fingerprint_data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_library_dex_cache(cache_dir, fingerprint):
    if os.path.islink(cache_dir) or not os.path.isdir(cache_dir):
        return False

    actual = set()
    for current, directories, files in os.walk(cache_dir, followlinks=False):
        if any(os.path.islink(os.path.join(current, name)) for name in directories):
            return False
        for name in files:
            path = os.path.join(current, name)
            if os.path.islink(path):
                return False
            if name.endswith(".dex"):
                if not os.path.isfile(path):
                    return False
                actual.add(os.path.relpath(path, cache_dir).replace(os.sep, "/"))

    manifest_path = os.path.join(cache_dir, ".termux-builder-dex.json")
    if os.path.islink(manifest_path) or not os.path.isfile(manifest_path):
        return False
    try:
        with open(manifest_path) as source:
            manifest = json.load(source)
    except (OSError, json.JSONDecodeError):
        return False
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 1
        or manifest.get("fingerprint") != fingerprint
        or not isinstance(manifest.get("outputs"), list)
    ):
        return False

    expected = {}
    for item in manifest["outputs"]:
        if not isinstance(item, dict):
            return False
        relative = item.get("path")
        digest = item.get("sha256")
        if (
            not isinstance(relative, str)
            or not relative.endswith(".dex")
            or os.path.isabs(relative)
            or "\\" in relative
            or any(part in ("", ".", "..") for part in relative.split("/"))
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
            or relative in expected
        ):
            return False
        output_path = os.path.join(cache_dir, *relative.split("/"))
        if os.path.islink(output_path) or not os.path.isfile(output_path):
            return False
        try:
            if _sha256_file(output_path) != digest:
                return False
        except OSError:
            return False
        expected[relative] = None
    return actual == set(expected)




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
