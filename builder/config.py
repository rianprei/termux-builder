import xml.etree.ElementTree as ET
import os
import yaml
from builder.utils import find_bin, log

_SYSTEM_ANDROID_JAR = "/data/data/com.termux/files/usr/share/java/android.jar"


class Config:
    def __init__(self, project_dir, flavor=None):
        self.project_dir = os.path.abspath(project_dir)
        yml_path = os.path.join(self.project_dir, "project.yml")

        if not os.path.exists(yml_path):
            raise FileNotFoundError("project.yml not found in " + self.project_dir)

        with open(yml_path) as f:
            raw = yaml.safe_load(f) or {}

        if "android" not in raw:
            raise ValueError("Missing 'android' section in project.yml")

        self.name = raw.get("name", os.path.basename(self.project_dir))
        android = raw["android"]

        self.flavor = flavor
        self.flavors = raw.get("flavors", {})
        if flavor is not None and flavor not in self.flavors:
            raise ValueError(f"Unknown flavor: {flavor} (declared: {list(self.flavors)})")
        flavor_cfg = self.flavors.get(flavor, {}) if flavor else {}

        self.min_sdk = android.get("min-sdk", 21)
        self.target_sdk = android.get("target-sdk", 34)
        self.version_code = flavor_cfg.get("version-code", android.get("version-code", 1))
        self.version_name = str(flavor_cfg.get("version-name", android.get("version-name", "1.0.0")))
        self.build_type = android.get("build-type", "debug")
        self.java_version = android.get("java-version", 17)

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

        self.sources_dir = os.path.join(self.project_dir, android.get("sources-path", "src/java"))
        self.res_dir = os.path.join(self.project_dir, android.get("res-path", "src/res"))
        self.assets_dir = os.path.join(self.project_dir, android.get("assets-path", "src/assets"))
        self.jni_dir = os.path.join(self.project_dir, android.get("jni-path", "src/jniLibs"))

        # flavor source-set overlay: src/<flavor>/{java,res,assets} merged over main src/
        self.flavor_sources_dir = None
        self.flavor_res_dir = None
        if flavor:
            fsrc = os.path.join(self.project_dir, "src", flavor, "java")
            fres = os.path.join(self.project_dir, "src", flavor, "res")
            self.flavor_sources_dir = fsrc if os.path.isdir(fsrc) else None
            self.flavor_res_dir = fres if os.path.isdir(fres) else None

        self.keystore_path = os.path.join(self.project_dir, android.get("keystore-path", "debug.keystore"))
        self.keystore_alias = android.get("keystore-alias", "androiddebugkey")
        self.keystore_store_pass = str(android.get("keystore-store-pass", "android"))
        self.keystore_key_pass = str(android.get("keystore-key-pass", "android"))

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
        self.bin_aapt2 = self._resolve_bin("aapt2", bins)
        self.bin_javac = self._resolve_bin("javac", bins)
        self.bin_kotlinc = self._resolve_bin("kotlinc", bins)
        # prefer d8, fallback to dx (Termux native)
        self.bin_d8 = self._resolve_bin("d8", bins) if find_bin("d8") else self._resolve_bin("dx", bins)
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
        if name in bins_config:
            return bins_config[name]
        path = find_bin(name)
        return path if path else name

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
        return [j for j in find_files(self.libs_dir, ".jar")
                if os.path.basename(j) != "lint.jar"]

    def find_native_libs(self):
        libs = []
        if not os.path.isdir(self.jni_dir):
            return libs
        for abi in os.listdir(self.jni_dir):
            abi_dir = os.path.join(self.jni_dir, abi)
            if not os.path.isdir(abi_dir):
                continue
            for f in os.listdir(abi_dir):
                if f.endswith(".so"):
                    libs.append((abi, os.path.join(abi_dir, f)))
        return libs
