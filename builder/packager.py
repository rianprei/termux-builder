import os
import shutil
import tempfile
import zipfile
from builder.utils import dex_sort_key, ensure_output_path, find_files, log


def _processor_resource_entries(config):
    if not getattr(config, "kapt_enabled", False):
        return []
    root = os.path.join(config.build_dir, "kapt", "classes")
    ensure_output_path(config.build_dir, root, "KAPT resources")
    if not os.path.lexists(root):
        return []
    if not os.path.isdir(root):
        raise ValueError("KAPT resource output must be a directory")
    def scan_error(error):
        raise RuntimeError(f"Cannot read KAPT resources: {error.filename or root}; check permissions and rerun the build") from None
    entries = []
    for directory, directories, files in os.walk(root, onerror=scan_error):
        directories.sort()
        for child in directories:
            ensure_output_path(root, os.path.join(directory, child), "KAPT resource directory")
        for filename in sorted(files):
            path = os.path.join(directory, filename)
            ensure_output_path(root, path, "KAPT resource")
            if not os.path.isfile(path):
                raise ValueError(f"KAPT resource must be a regular file: {path}")
            if filename.endswith('.class'):
                continue
            name = os.path.relpath(path, root).replace(os.sep, '/')
            parts = name.split('/')
            if '\\' in name or any(part in {'', '.', '..'} for part in parts):
                raise ValueError(f"Unsafe KAPT resource path: {name}")
            if parts[0] in {'AndroidManifest.xml', 'resources.arsc', 'resources.pb', 'res', 'assets', 'lib', 'dex', 'manifest', 'root'} or name.endswith('.dex'):
                raise ValueError(f"Reserved KAPT resource path: {name}")
            if name.upper().startswith('META-INF/') and (name.upper() == 'META-INF/MANIFEST.MF' or name.upper().endswith(('.SF', '.RSA', '.DSA', '.EC'))):
                raise ValueError(f"Signature metadata cannot be supplied by KAPT: {name}")
            entries.append((path, name))
    return entries


def _append_file(apk, path, archive_name, used_names):
    if archive_name in used_names:
        raise RuntimeError(f"Duplicate APK entry: {archive_name}")
    info = zipfile.ZipInfo(archive_name, (1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    with open(path, "rb") as source:
        apk.writestr(info, source.read())
    used_names.add(archive_name)


def package(config, abi=None):
    log.info("Packaging APK%s", f" ({abi})" if abi else "")

    unsigned = os.path.join(config.bin_dir, f"unsigned-{abi}.apk" if abi else "unsigned.apk")
    base_apk = os.path.join(config.bin_dir, "gen.apk.res")
    build_dir = getattr(config, "build_dir", config.bin_dir)
    ensure_output_path(build_dir, unsigned, "Unsigned APK output")
    ensure_output_path(build_dir, base_apk, "Resource APK input")

    if not os.path.isfile(base_apk):
        raise FileNotFoundError("Resource APK not found — aapt2 link may have failed")

    # Keep app DEX first; dex_sort_key provides numeric ordering for multidex.
    dex_files = [
        path for path in find_files(config.dex_dir, ".dex")
        if os.path.dirname(path) == config.dex_dir
    ]
    dex_files.sort(key=dex_sort_key)
    if not dex_files:
        raise RuntimeError("No DEX files found")

    dex_entries = [(path, os.path.basename(path)) for path in dex_files]
    used_dex_names = {name for _, name in dex_entries}
    dex_index = len(dex_files) + 1
    library_dex_dir = getattr(config, "library_dex_dir", None)
    if library_dex_dir and os.path.islink(library_dex_dir):
        raise RuntimeError(f"Library DEX cache must not be a symlink: {library_dex_dir}")
    if library_dex_dir and not os.path.isdir(library_dex_dir):
        raise RuntimeError("Library DEX cache disappeared before APK packaging; rerun the build")
    extra_dex_dirs = [library_dex_dir] if library_dex_dir else []
    desugar_lib_dir = os.path.join(config.dex_dir, "desugar_lib")
    if os.path.isdir(desugar_lib_dir):
        extra_dex_dirs.append(desugar_lib_dir)
    for lib_dir in extra_dex_dirs:
        for path in sorted(find_files(lib_dir, ".dex"), key=dex_sort_key):
            name = f"classes{dex_index}.dex"
            while name in used_dex_names:
                dex_index += 1
                name = f"classes{dex_index}.dex"
            dex_entries.append((path, name))
            used_dex_names.add(name)
            dex_index += 1

    native_entries = []
    for lib_abi, so_path in config.find_native_libs():
        if abi and lib_abi != abi:
            continue
        native_entries.append((so_path, f"lib/{lib_abi}/{os.path.basename(so_path)}"))
    native_entries.sort(key=lambda entry: entry[1])
    processor_resources = _processor_resource_entries(config)

    fd, staging_path = tempfile.mkstemp(
        prefix=".unsigned-", suffix=".apk", dir=os.path.dirname(unsigned)
    )
    os.close(fd)
    try:
        shutil.copyfile(base_apk, staging_path)
        with zipfile.ZipFile(staging_path, "a", zipfile.ZIP_DEFLATED) as apk:
            base_names = apk.namelist()
            if len(base_names) != len(set(base_names)):
                raise RuntimeError("Resource APK contains duplicate ZIP entries")
            used_names = set(base_names)
            for path, name in dex_entries:
                _append_file(apk, path, name, used_names)
            for path, name in native_entries:
                _append_file(apk, path, name, used_names)
            for path, name in processor_resources:
                _append_file(apk, path, name, used_names)
        os.replace(staging_path, unsigned)
        staging_path = None
    finally:
        if staging_path and os.path.lexists(staging_path):
            os.unlink(staging_path)

    log.info("APK packaged: %s", unsigned)
    return unsigned


def available_abis(config):
    return sorted({a for a, _ in config.find_native_libs()})
