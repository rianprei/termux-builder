import xml.etree.ElementTree as ET
import filecmp
import os
import re
import zipfile
import yaml
from builder.utils import find_bin, is_reserved_maven_cache_path, log

_SYSTEM_ANDROID_JAR = "/data/data/com.termux/files/usr/share/java/android.jar"


def _validate_path_segment(value, label):
    if (
        not isinstance(value, str)
        or not value
        or value in (".", "..")
        or any(character in value for character in ("/", "\\", "\x00"))
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError(f"Invalid {label}: expected a single safe path segment")
    return value


def _resolve_password(value, setting):
    value = str(value)
    if not value.startswith("env:"):
        return value

    variable = value[4:]
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", variable):
        raise ValueError(f"Invalid environment variable reference for {setting}")
    password = os.environ.get(variable)
    if password is None:
        raise ValueError(f"{setting} references unset environment variable {variable}")
    return password


def _archive_member_matches_file(archive, member, path):
    try:
        with archive.open(member) as source, open(path, "rb") as target:
            while True:
                source_chunk = source.read(8192)
                target_chunk = target.read(8192)
                if source_chunk != target_chunk:
                    return False
                if not source_chunk:
                    return True
    except (OSError, RuntimeError, zipfile.BadZipFile):
        return False


def _is_legacy_maven_cache_directory(config, directory):
    libs_dir = os.path.abspath(config.libs_dir)
    directory = os.path.abspath(directory)
    if os.path.dirname(directory) != libs_dir or os.path.islink(directory):
        return False
    cache_dir = getattr(config, "cache_dir", None)
    if not cache_dir:
        return False

    name = os.path.basename(directory)
    dependency_cache = os.path.join(cache_dir, "deps")
    jar_path = os.path.join(directory, f"{name}.jar")
    cached_jar = os.path.join(dependency_cache, f"{name}.jar")
    if (
        not os.path.islink(jar_path)
        and os.path.isfile(jar_path)
        and not os.path.islink(cached_jar)
        and os.path.isfile(cached_jar)
        and filecmp.cmp(jar_path, cached_jar, shallow=False)
    ):
        return True

    cached_aar = os.path.join(dependency_cache, f"{name}.aar")
    if os.path.islink(cached_aar) or not os.path.isfile(cached_aar):
        return False
    expected = {}
    try:
        with zipfile.ZipFile(cached_aar) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                relative = member.filename
                if relative == "classes.jar":
                    relative = f"{name}.jar"
                parts = relative.replace("\\", "/").split("/")
                if relative.startswith("/") or any(part in ("", ".", "..") for part in parts):
                    return False
                if relative in expected:
                    return False
                path = os.path.join(directory, *parts)
                if os.path.islink(path) or not os.path.isfile(path):
                    return False
                expected[relative] = (member, path, archive)
    except (OSError, zipfile.BadZipFile):
        return False

    actual = set()
    for current, directories, files in os.walk(directory, followlinks=False):
        if any(os.path.islink(os.path.join(current, name)) for name in directories):
            return False
        for filename in files:
            path = os.path.join(current, filename)
            if os.path.islink(path) or not os.path.isfile(path):
                return False
            relative = os.path.relpath(path, directory).replace(os.sep, "/")
            if relative == ".transitive":
                continue
            actual.add(relative)
    if actual != set(expected):
        return False

    try:
        with zipfile.ZipFile(cached_aar) as archive:
            return all(
                _archive_member_matches_file(archive, archive_member, path)
                for archive_member, path, _ in expected.values()
            )
    except (OSError, zipfile.BadZipFile):
        return False


def _resolve_sdk_bin(sdk_dir, name, bins_config):
    if name in bins_config:
        return bins_config[name]
    path = find_bin(name)
    if path:
        return path

    build_tools_dir = os.path.join(sdk_dir, "build-tools") if sdk_dir else None
    if build_tools_dir and os.path.isdir(build_tools_dir):
        versions = [
            version for version in os.listdir(build_tools_dir)
            if all(part.isdigit() for part in version.split("."))
        ]
        for version in sorted(
            versions,
            key=lambda value: tuple(int(part) for part in value.split(".")),
            reverse=True,
        ):
            candidate = os.path.join(build_tools_dir, version, name)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
    return None


class Config:
    def __init__(self, project_dir, flavor=None):
        self.project_dir = os.path.abspath(project_dir)
        yml_path = os.path.join(self.project_dir, "project.yml")

        if not os.path.exists(yml_path):
            raise FileNotFoundError("project.yml not found in " + self.project_dir)

        with open(yml_path) as f:
            try:
                raw = yaml.safe_load(f)
            except yaml.YAMLError as error:
                mark = getattr(error, "problem_mark", None)
                location = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
                raise ValueError(f"Invalid YAML in project.yml{location}; check syntax locally") from None
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ValueError("project.yml must be a mapping")

        if "android" not in raw:
            raise ValueError("Missing 'android' section in project.yml")
        if not isinstance(raw["android"], dict):
            raise ValueError("android must be a mapping")

        self.name = _validate_path_segment(
            raw.get("name", os.path.basename(self.project_dir)), "project name"
        )
        android = raw["android"]

        self.flavor = flavor
        self.flavors = raw.get("flavors", {})
        if not isinstance(self.flavors, dict):
            raise ValueError("flavors must be a mapping")
        for flavor_name, flavor_config in self.flavors.items():
            _validate_path_segment(flavor_name, "flavor name")
            if not isinstance(flavor_config, dict):
                raise ValueError(f"Flavor configuration must be a mapping: {flavor_name}")
        if flavor is not None and flavor not in self.flavors:
            raise ValueError(f"Unknown flavor: {flavor} (declared: {list(self.flavors)})")
        if flavor is not None:
            _validate_path_segment(flavor, "flavor name")
        flavor_cfg = self.flavors.get(flavor, {}) if flavor else {}

        self.min_sdk = android.get("min-sdk", 21)
        self.target_sdk = android.get("target-sdk", 34)
        self.version_code = flavor_cfg.get("version-code", android.get("version-code", 1))
        self.version_name = str(flavor_cfg.get("version-name", android.get("version-name", "1.0.0")))
        self.build_type = android.get("build-type", "debug")
        self.java_version = android.get("java-version", 17)
        for name, value in (("min-sdk", self.min_sdk), ("target-sdk", self.target_sdk), ("version-code", self.version_code)):
            if type(value) is not int or value <= 0:
                raise ValueError(f"android.{name} must be a positive integer")

        if self.build_type not in ("debug", "release"):
            raise ValueError(f"Invalid build-type: {self.build_type}")

        self.view_binding = android.get("view-binding", False)
        self.compose = android.get("compose", False)
        self.r8_enabled = android.get("r8", False)
        self.r8_rules = android.get("r8-rules", None)
        self.abi_splits = android.get("abi-splits", False)
        self.density_splits = android.get("density-splits", False)
        self.desugar_enabled = android.get("desugar", False)
        self.aab_enabled = android.get("aab", False)
        self.application_id_suffix = flavor_cfg.get("application-id-suffix", "")
        self.annotation_processors = raw.get("annotation-processors", [])
        self.kapt_enabled = android.get("kapt", False)
        self.ksp_enabled = android.get("ksp", False)
        for name in ("kapt", "ksp", "aab", "desugar", "r8", "view-binding", "compose", "abi-splits", "density-splits"):
            if not isinstance(android.get(name, False), bool):
                raise ValueError(f"android.{name} must be a boolean; use true or false without quotes")
        if not isinstance(self.annotation_processors, list) or any(
            not isinstance(path, str) or not path.strip() or '\x00' in path
            for path in self.annotation_processors
        ):
            raise ValueError("annotation-processors must be a list of nonempty file paths")

        self.manifest_path = os.path.join(
            self.project_dir, android.get("manifest-path", "AndroidManifest.xml")
        )
        if not os.path.exists(self.manifest_path):
            raise FileNotFoundError("AndroidManifest.xml not found: " + self.manifest_path)

        self.package_name = ET.parse(self.manifest_path).getroot().attrib.get("package")
        if not self.package_name:
            raise ValueError("AndroidManifest.xml missing 'package' attribute")
        if self.application_id_suffix:
            self.package_name += self.application_id_suffix

        manifest_placeholders = android.get("manifest-placeholders", {})
        flavor_placeholders = flavor_cfg.get("manifest-placeholders", {})
        if not isinstance(manifest_placeholders, dict) or not isinstance(flavor_placeholders, dict):
            raise ValueError("manifest-placeholders must be a mapping")
        self.manifest_placeholders = {}
        for key, value in {**manifest_placeholders, **flavor_placeholders}.items():
            if not isinstance(key, str) or not key or not isinstance(value, (str, int, float, bool)):
                raise ValueError("manifest-placeholders must have non-empty string keys and scalar values")
            self.manifest_placeholders[key] = str(value).lower() if isinstance(value, bool) else str(value)
        self.manifest_placeholders["applicationId"] = self.package_name

        self.sources_dir = os.path.join(self.project_dir, android.get("sources-path", "src/java"))
        self.res_dir = os.path.join(self.project_dir, android.get("res-path", "src/res"))
        self.assets_dir = os.path.join(self.project_dir, android.get("assets-path", "src/assets"))
        self.jni_dir = os.path.join(self.project_dir, android.get("jni-path", "src/jniLibs"))

        # flavor source-set overlay: src/<flavor>/{java,res,assets} merged over main src/
        self.flavor_sources_dir = None
        self.flavor_res_dir = None
        self.flavor_assets_dir = None
        if flavor:
            fsrc = os.path.join(self.project_dir, "src", flavor, "java")
            fres = os.path.join(self.project_dir, "src", flavor, "res")
            fassets = os.path.join(self.project_dir, "src", flavor, "assets")
            self.flavor_sources_dir = fsrc if os.path.isdir(fsrc) else None
            self.flavor_res_dir = fres if os.path.isdir(fres) else None
            self.flavor_assets_dir = fassets if os.path.isdir(fassets) else None

        self.keystore_path = os.path.join(self.project_dir, android.get("keystore-path", "debug.keystore"))
        self.keystore_alias = android.get("keystore-alias", "androiddebugkey")
        self.keystore_store_pass = _resolve_password(android.get("keystore-store-pass", "android"), "keystore-store-pass")
        self.keystore_key_pass = _resolve_password(android.get("keystore-key-pass", "android"), "keystore-key-pass")

        signing = android.get("signing", {})
        if not isinstance(signing, dict):
            raise ValueError("android.signing must be a mapping")
        for scheme in ("v1", "v2", "v3", "v4"):
            if scheme in signing and not isinstance(signing[scheme], bool):
                raise ValueError(f"android.signing.{scheme} must be a boolean; use true or false without quotes")
        # v4 needs incremental-fs support (API 30+) to have any effect — off
        # by default below that so apksigner doesn't warn for nothing
        self.sign_v1 = signing.get("v1", True)
        self.sign_v2 = signing.get("v2", True)
        self.sign_v3 = signing.get("v3", True)
        self.sign_v4 = signing.get("v4", self.min_sdk >= 30)

        self.libs_dir = os.path.join(self.project_dir, raw.get("libs-path", ".libs"))
        self.cache_dir = os.path.join(self.project_dir, raw.get("cache-path", ".cache"))
        self.build_dir = os.path.join(self.project_dir, raw.get("build-path", ".build"))
        self.gen_dir = os.path.join(self.build_dir, "gen")
        self.bin_dir = os.path.join(self.build_dir, "bin")
        self.java_classes_dir = os.path.join(self.bin_dir, "classes", "java")
        self.kotlin_classes_dir = os.path.join(self.bin_dir, "classes", "kotlin")
        self.compiled_res_dir = os.path.join(self.bin_dir, "res")
        self.dex_dir = os.path.join(self.bin_dir, "dex")
        self.binding_dir = os.path.join(self.build_dir, "view_binding")

        self.dependencies = raw.get("dependencies", [])

        self.sdk_dir = self._resolve_sdk(android.get("sdk-path"))
        self.android_jar = self._resolve_android_jar()

        bins = raw.get("bins", {})
        if not isinstance(bins, dict):
            raise ValueError("bins must be a mapping of tool names to executable paths")
        if any(not isinstance(name, str) or not name.strip() or not isinstance(path, str)
               or not path.strip() or '\x00' in path for name, path in bins.items()):
            raise ValueError("bins must contain nonempty tool names and executable paths without NUL")
        self.bin_aapt2 = self._resolve_bin("aapt2", bins)
        self.bin_javac = self._resolve_bin("javac", bins)
        self.bin_kotlinc = self._resolve_bin("kotlinc", bins)
        # prefer d8, fallback to dx (Termux native)
        self.bin_d8 = self._resolve_bin("d8", bins)
        if self.bin_d8 == "d8" and "d8" not in bins:
            self.bin_d8 = self._resolve_bin("dx", bins)
        self.bin_apksigner = self._resolve_bin("apksigner", bins)

    def _resolve_sdk(self, configured):
        if configured:
            return configured
        for var in ("ANDROID_SDK", "ANDROID_HOME", "ANDROID_SDK_ROOT"):
            val = os.getenv(var)
            if val and os.path.isdir(val):
                log.info("Using SDK from $%s: %s", var, val)
                return val
        default = os.path.join(os.getenv("HOME", ""), ".termux-builder", "sdk")
        if os.path.isdir(default):
            return default
        # Return a path even if it doesn't exist — android.jar fallback handles it
        return default

    def _resolve_android_jar(self):
        jar = os.path.join(self.sdk_dir, "platforms", f"android-{self.target_sdk}", "android.jar")
        if os.path.isfile(jar):
            return jar
        # Termux native fallback — no setup needed
        if os.path.isfile(_SYSTEM_ANDROID_JAR):
            log.info("SDK not found — using system android.jar (Termux native)")
            return _SYSTEM_ANDROID_JAR
        return jar  # will fail with clear error later

    def _resolve_bin(self, name, bins_config):
        path = _resolve_sdk_bin(self.sdk_dir, name, bins_config)
        return path if path is not None else name

    def find_java_files(self, base_dir=None):
        from builder.utils import find_files
        if base_dir:
            return find_files(base_dir, ".java")
        files = find_files(self.sources_dir, ".java")
        if self.flavor_sources_dir:
            files += find_files(self.flavor_sources_dir, ".java")
        return files

    def find_kotlin_files(self, base_dir=None):
        from builder.utils import find_files
        if base_dir:
            return find_files(base_dir, ".kt")
        files = find_files(self.sources_dir, ".kt")
        if self.flavor_sources_dir:
            files += find_files(self.flavor_sources_dir, ".kt")
        return files

    def find_res_dirs(self):
        dirs = [self.res_dir]
        if self.flavor_res_dir:
            dirs.append(self.flavor_res_dir)
        return dirs

    def find_lib_jars(self):
        from builder.utils import find_files
        # lint.jar causes d8/javac errors — filter it out
        jars = [j for j in find_files(self.libs_dir, ".jar")
                if os.path.basename(j) != "lint.jar"]
        jars = [
            jar for jar in jars
            if not _is_legacy_maven_cache_directory(self, os.path.dirname(jar))
        ]
        resolved_dirs = getattr(self, "resolved_dependency_dirs", None)
        if resolved_dirs is None:
            return sorted(
                jar for jar in jars
                if not is_reserved_maven_cache_path(self.libs_dir, os.path.dirname(jar))
            )

        resolved_dirs = {os.path.realpath(path) for path in resolved_dirs}
        selected = []
        libs_root = os.path.realpath(self.libs_dir)
        for jar in jars:
            reserved_cache_entry = is_reserved_maven_cache_path(
                self.libs_dir, os.path.dirname(jar)
            )
            current = os.path.realpath(os.path.dirname(jar))
            dependency_dir = None
            while current != libs_root:
                try:
                    if os.path.commonpath((libs_root, current)) != libs_root:
                        break
                except ValueError:
                    break
                if (
                    os.path.isfile(os.path.join(current, ".termux-builder-coordinate"))
                    or os.path.isfile(os.path.join(current, ".transitive"))
                ):
                    dependency_dir = current
                    break
                current = os.path.dirname(current)
            if reserved_cache_entry and dependency_dir is None:
                continue
            if dependency_dir is None or dependency_dir in resolved_dirs:
                selected.append(jar)
        return sorted(selected)

    def _is_legacy_maven_cache_directory(self, directory):
        return _is_legacy_maven_cache_directory(self, directory)

    def _library_dirs(self):
        library_dirs = {os.path.dirname(jar) for jar in self.find_lib_jars()}
        resolved_dirs = getattr(self, "resolved_dependency_dirs", None)
        if resolved_dirs is not None:
            library_dirs.update(resolved_dirs)
        return library_dirs

    def find_lib_resource_dirs(self):
        library_dirs = self._library_dirs()
        resource_dirs = []
        for directory in library_dirs:
            resource_dir = os.path.join(directory, "res")
            if os.path.islink(resource_dir):
                raise RuntimeError(f"Dependency resource directory must not be a symlink: {resource_dir}")
            if os.path.isdir(resource_dir):
                resource_dirs.append(resource_dir)
        return sorted(resource_dirs)

    def find_lib_asset_dirs(self):
        library_dirs = self._library_dirs()
        asset_dirs = []
        for directory in library_dirs:
            asset_dir = os.path.join(directory, "assets")
            if os.path.islink(asset_dir):
                raise RuntimeError(f"Dependency asset directory must not be a symlink: {asset_dir}")
            if os.path.isdir(asset_dir):
                asset_dirs.append(asset_dir)
        return sorted(asset_dirs)

    def find_native_libs(self):
        native_dirs = [self.jni_dir]
        native_dirs.extend(
            os.path.join(directory, "jni") for directory in sorted(self._library_dirs())
        )
        selected = {}
        libs = []
        for native_dir in native_dirs:
            if os.path.islink(native_dir):
                raise RuntimeError(f"Native library directory must not be a symlink: {native_dir}")
            if not os.path.isdir(native_dir):
                continue
            for abi in sorted(os.listdir(native_dir)):
                abi_dir = os.path.join(native_dir, abi)
                if os.path.islink(abi_dir):
                    raise RuntimeError(f"Native ABI directory must not be a symlink: {abi_dir}")
                if not os.path.isdir(abi_dir):
                    continue
                for name in sorted(os.listdir(abi_dir)):
                    if not name.endswith(".so"):
                        continue
                    so_path = os.path.join(abi_dir, name)
                    if os.path.islink(so_path):
                        raise RuntimeError(f"Native library must not be a symlink: {so_path}")
                    if not os.path.isfile(so_path):
                        continue
                    key = (abi, name)
                    previous = selected.get(key)
                    if previous:
                        if filecmp.cmp(previous, so_path, shallow=False):
                            continue
                        raise RuntimeError(
                            f"Conflicting native library {abi}/{name}: {previous} and {so_path}"
                        )
                    selected[key] = so_path
                    libs.append((abi, so_path))
        return libs
