import hashlib
import os
import shutil
import xml.etree.ElementTree as ET
import zipfile
import zlib
from builder.utils import ensure_output_path, run, ensure_dir, find_files, log
from builder.archives import check_zip_directory, verify_zip_payloads

# System android.jar (Termux native package)
_SYSTEM_ANDROID_JAR = "/data/data/com.termux/files/usr/share/java/android.jar"


def _resolve_android_jar(config):
    # config.py already resolves config.android_jar to the system jar when
    # no SDK is configured, so that path is checked once here (no dead branch).
    if not os.path.isfile(config.android_jar):
        raise FileNotFoundError("android.jar not found. Run: termux-builder setup")
    failure = "android.jar verification failed: "
    repair = "; restore the selected SDK platform's android.jar from its trusted source"
    try:
        with open(config.android_jar, "rb") as sdk:
            if os.fstat(sdk.fileno()).st_size > 128 * 1024**2:
                raise RuntimeError(failure + "archive exceeds 128 MiB")
            check_zip_directory(sdk, 60000, "android.jar verification failed")
            with zipfile.ZipFile(sdk) as archive:
                entries = archive.infolist()
                if sum(entry.file_size for entry in entries) > 1024**3:
                    raise RuntimeError(failure + "archive exceeds expanded-size limits")
                if len({entry.filename for entry in entries}) != len(entries):
                    raise RuntimeError(failure + "duplicate ZIP entries")
                if any("\x00" in entry.orig_filename or entry.filename != entry.orig_filename
                       for entry in entries):
                    raise RuntimeError(failure + "ambiguous ZIP entry names")
                if any(entry.flag_bits & 0x41 or entry.compress_type not in
                       (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) for entry in entries):
                    raise RuntimeError(failure + "encrypted or unsupported ZIP entries")
                if not any(entry.filename == "android/app/Activity.class" and entry.file_size > 0
                           for entry in entries):
                    raise RuntimeError(failure + "missing Android framework class")
                verify_zip_payloads(sdk, archive, 1024**3, "android.jar verification failed")
    except RuntimeError as error:
        detail = str(error)
        if not detail.startswith(failure):
            detail = failure + "unsupported ZIP data"
        raise RuntimeError(detail + repair) from None
    except OSError:
        raise RuntimeError(failure + "cannot read SDK archive; check its path and permissions") from None
    except (zipfile.BadZipFile, zipfile.LargeZipFile, ValueError, EOFError, NotImplementedError, zlib.error):
        raise RuntimeError(failure + "invalid ZIP data or CRC" + repair) from None
    if config.android_jar == _SYSTEM_ANDROID_JAR:
        log.warning(
            "Using system android.jar — aapt2 link will fail with themes. "
            "Run: termux-builder setup"
        )
    return config.android_jar


def _has_aapt2(config):
    return shutil.which("aapt2") is not None or (
        config.bin_aapt2 != "aapt2" and os.path.isfile(config.bin_aapt2)
    )


def compile_resources(config):
    if _has_aapt2(config):
        _compile_aapt2(config)
    else:
        _compile_aapt1(config)


def _dependency_coordinate(config, directory):
    libs_root = os.path.realpath(config.libs_dir)
    current = os.path.realpath(directory)
    while current != libs_root:
        try:
            if os.path.commonpath((libs_root, current)) != libs_root:
                return None
        except ValueError:
            return None
        marker = os.path.join(current, ".termux-builder-coordinate")
        if os.path.islink(marker):
            raise ValueError(f"Dependency coordinate marker must not be a symlink: {marker}")
        if os.path.isfile(marker):
            with open(marker) as file:
                return file.read().strip()
        current = os.path.dirname(current)
    return None


def _partition_library_dirs(config, library_dirs):
    remaining = set(library_dirs)
    direct_dirs = []
    for coordinate in getattr(config, "dependencies", []) or []:
        if not isinstance(coordinate, str):
            continue
        parts = coordinate.split(":")
        if len(parts) != 3:
            continue
        version = parts[2]
        if version.startswith("[") and version.endswith("]") and "," not in version:
            version = version[1:-1]
        canonical_coordinate = f"{parts[0]}:{parts[1]}:{version}"
        matches = [
            directory for directory in sorted(remaining)
            if _dependency_coordinate(config, directory) == canonical_coordinate
        ]
        direct_dirs.extend(matches)
        remaining.difference_update(matches)
    return sorted(remaining), direct_dirs


def _aapt2_resource_jobs(config):
    res_dirs = config.find_res_dirs() if hasattr(config, "find_res_dirs") else [config.res_dir]
    jobs = []
    library_res_dirs = sorted(set(config.find_lib_resource_dirs()))
    transitive_dirs, direct_dirs = _partition_library_dirs(config, library_res_dirs)
    ordered_library_res_dirs = transitive_dirs + list(reversed(direct_dirs))
    library_outputs = set()
    for res in ordered_library_res_dirs:
        lib_dir = os.path.dirname(res)
        library_path = os.path.relpath(lib_dir, config.libs_dir).replace(os.sep, "/")
        library_id = hashlib.sha256(library_path.encode("utf-8")).hexdigest()
        out = os.path.join(config.compiled_res_dir, f"lib-{library_id}.zip")
        if out not in library_outputs:
            jobs.append((res, out))
            library_outputs.add(out)

    for i, res_dir in enumerate(res_dirs):
        out = os.path.join(config.compiled_res_dir, "res.zip" if i == 0 else f"res-flavor{i}.zip")
        jobs.append((res_dir, out))
    return jobs


def _compile_aapt2(config):
    log.info("Compiling resources (aapt2)")
    ensure_output_path(
        getattr(config, "build_dir", config.compiled_res_dir),
        os.path.join(config.compiled_res_dir, ".output-check"),
        "AAPT2 compiled resource directory",
    )
    ensure_dir(config.compiled_res_dir)
    for res_dir, out in _aapt2_resource_jobs(config):
        ensure_output_path(
            getattr(config, "build_dir", config.compiled_res_dir), out, "AAPT2 resource output"
        )
        run([config.bin_aapt2, "compile", "--dir", res_dir, "-o", out])


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
    if proto_format:
        raise RuntimeError("AAB builds require aapt2 with --proto-format; install aapt2 and add it to PATH")
    _link_aapt1(config, android_jar)
    return None


def _link_aapt2(config, android_jar, proto_format=False):
    log.info("Linking resources (aapt2)")
    # clean gen_dir so stale R.java from old package names is removed
    import shutil
    ensure_output_path(
        getattr(config, "build_dir", config.bin_dir),
        os.path.join(config.gen_dir, ".output-check"),
        "AAPT generated source output",
    )
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

    asset_dirs = []
    flavor_assets_dir = getattr(config, "flavor_assets_dir", None)
    if flavor_assets_dir and os.path.isdir(flavor_assets_dir):
        asset_dirs.append(flavor_assets_dir)
    if os.path.isdir(config.assets_dir):
        asset_dirs.append(config.assets_dir)
    library_asset_dirs = config.find_lib_asset_dirs() if hasattr(config, "find_lib_asset_dirs") else []
    transitive_assets, direct_assets = _partition_library_dirs(config, library_asset_dirs)
    asset_dirs.extend(direct_assets)
    asset_dirs.extend(transitive_assets)
    for asset_dir in asset_dirs:
        args += ["-A", asset_dir]

    for _, resource_archive in _aapt2_resource_jobs(config):
        args += ["-R", resource_archive]

    extra_packages = _get_lib_packages(config)
    if extra_packages:
        args += ["--extra-packages", extra_packages]

    output_res = os.path.join(config.bin_dir, "gen.apk.res")
    ensure_output_path(
        getattr(config, "build_dir", config.bin_dir), output_res, "AAPT2 resource output"
    )
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
            ensure_output_path(
                getattr(config, "build_dir", config.bin_dir), split_path, "AAPT2 split output"
            )
            args += ["--split", f"{split_path}:{_DENSITY_BUCKETS[density]}"]
            split_paths.append((density, split_path))

    run(args)
    return split_paths


def _link_aapt1(config, android_jar):
    """aapt v1 package — compile + link in one shot."""
    log.info("Linking resources (aapt v1)")
    ensure_output_path(
        getattr(config, "build_dir", config.bin_dir),
        os.path.join(config.gen_dir, ".output-check"),
        "AAPT generated source output",
    )
    ensure_dir(config.gen_dir)
    output_res = os.path.join(config.bin_dir, "gen.apk.res")
    ensure_output_path(
        getattr(config, "build_dir", config.bin_dir), output_res, "AAPT resource output"
    )

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
        "-I", android_jar,
        "-F", output_res,
    ]

    app_res_dirs = config.find_res_dirs() if hasattr(config, "find_res_dirs") else [config.res_dir]
    app_res_dirs = [path for path in app_res_dirs if os.path.isdir(path)]
    # AAPT1 uses the first resource directory that matches; flavor and app
    # resources therefore precede library resources.
    resource_dirs = list(reversed(app_res_dirs))
    library_res_dirs = config.find_lib_resource_dirs() if hasattr(config, "find_lib_resource_dirs") else []
    transitive_res_dirs, direct_res_dirs = _partition_library_dirs(config, library_res_dirs)
    resource_dirs.extend(direct_res_dirs)
    resource_dirs.extend(transitive_res_dirs)
    if not resource_dirs:
        resource_dirs.append(config.res_dir)
    if len(resource_dirs) > 1:
        args.append("--auto-add-overlay")
    for resource_dir in resource_dirs:
        args += ["-S", resource_dir]

    asset_dirs = []
    flavor_assets_dir = getattr(config, "flavor_assets_dir", None)
    if flavor_assets_dir and os.path.isdir(flavor_assets_dir):
        asset_dirs.append(flavor_assets_dir)
    if os.path.isdir(config.assets_dir):
        asset_dirs.append(config.assets_dir)
    library_asset_dirs = config.find_lib_asset_dirs() if hasattr(config, "find_lib_asset_dirs") else []
    transitive_asset_dirs, direct_asset_dirs = _partition_library_dirs(config, library_asset_dirs)
    asset_dirs.extend(direct_asset_dirs)
    asset_dirs.extend(transitive_asset_dirs)
    for asset_dir in asset_dirs:
        args += ["-A", asset_dir]

    extra_packages = _get_lib_packages(config)
    if extra_packages:
        args += ["--extra-packages", extra_packages]

    run(args)


def _get_lib_packages(config):
    packages = set()
    if not os.path.isdir(config.libs_dir):
        return ""
    if hasattr(config, "_library_dirs"):
        library_dirs = sorted(config._library_dirs())
    else:
        library_dirs = []
        for root, _, files in os.walk(config.libs_dir):
            if "AndroidManifest.xml" in files:
                library_dirs.append(root)
    for library_dir in library_dirs:
        manifest_path = os.path.join(library_dir, "AndroidManifest.xml")
        if os.path.islink(manifest_path):
            raise ValueError(f"Library manifest must not be a symlink: {manifest_path}")
        if not os.path.isfile(manifest_path):
            continue
        pkg = ET.parse(manifest_path).getroot().attrib.get("package")
        if pkg:
            packages.add(pkg)
    return ":".join(sorted(packages))
