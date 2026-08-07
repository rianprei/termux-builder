import xml.etree.ElementTree as ET
import os
import yaml
from builder.utils import find_bin, log


class Config:
    def __init__(self, project_dir):
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

        self.min_sdk = android.get("min-sdk", 21)
        self.target_sdk = android.get("target-sdk", 34)
        self.version_code = android.get("version-code", 1)
        self.version_name = str(android.get("version-name", "1.0.0"))
        self.build_type = android.get("build-type", "debug")
        self.java_version = android.get("java-version", 17)

        if self.build_type not in ("debug", "release"):
            raise ValueError(f"Invalid build-type: {self.build_type}")

        self.view_binding = android.get("view-binding", False)
        self.compose = android.get("compose", False)
        self.r8_enabled = android.get("r8", False)
        self.r8_rules = android.get("r8-rules", None)

        self.manifest_path = os.path.join(
            self.project_dir, android.get("manifest-path", "AndroidManifest.xml")
        )
        if not os.path.exists(self.manifest_path):
            raise FileNotFoundError("AndroidManifest.xml not found: " + self.manifest_path)

        self.package_name = ET.parse(self.manifest_path).getroot().attrib.get("package")
        if not self.package_name:
            raise ValueError("AndroidManifest.xml missing 'package' attribute")

        self.sources_dir = os.path.join(
            self.project_dir, android.get("sources-path", "src/java")
        )
        self.res_dir = os.path.join(
            self.project_dir, android.get("res-path", "src/res")
        )
        self.assets_dir = os.path.join(
            self.project_dir, android.get("assets-path", "src/assets")
        )
        self.jni_dir = os.path.join(
            self.project_dir, android.get("jni-path", "src/jniLibs")
        )

        self.keystore_path = os.path.join(
            self.project_dir, android.get("keystore-path", "debug.keystore")
        )
        self.keystore_alias = android.get("keystore-alias", "androiddebugkey")
        self.keystore_store_pass = str(android.get("keystore-store-pass", "android"))
        self.keystore_key_pass = str(android.get("keystore-key-pass", "android"))

        self.libs_dir = os.path.join(
            self.project_dir, raw.get("libs-path", ".libs")
        )
        self.cache_dir = os.path.join(
            self.project_dir, raw.get("cache-path", ".cache")
        )

        self.build_dir = os.path.join(
            self.project_dir, raw.get("build-path", ".build")
        )
        self.gen_dir = os.path.join(self.build_dir, "gen")
        self.bin_dir = os.path.join(self.build_dir, "bin")
        self.java_classes_dir = os.path.join(self.bin_dir, "classes", "java")
        self.kotlin_classes_dir = os.path.join(self.bin_dir, "classes", "kotlin")
        self.compiled_res_dir = os.path.join(self.bin_dir, "res")
        self.dex_dir = os.path.join(self.bin_dir, "dex")
        self.binding_dir = os.path.join(self.build_dir, "view_binding")

        self.dependencies = raw.get("dependencies", [])

        self.sdk_dir = self._resolve_sdk(android.get("sdk-path"))
        self.android_jar = os.path.join(
            self.sdk_dir, "platforms", f"android-{self.target_sdk}", "android.jar"
        )

        bins = raw.get("bins", {})
        self.bin_aapt2 = self._resolve_bin("aapt2", bins)
        self.bin_javac = self._resolve_bin("javac", bins)
        self.bin_kotlinc = self._resolve_bin("kotlinc", bins)
        self.bin_d8 = self._resolve_bin("d8", bins) if self._find_bin_direct("d8") else self._resolve_bin("dx", bins)
        self.bin_apksigner = self._resolve_bin("apksigner", bins)

    def _resolve_sdk(self, configured):
        if configured:
            return configured
        for var in ("ANDROID_SDK", "ANDROID_HOME", "ANDROID_SDK_ROOT"):
            val = os.getenv(var)
            if val and os.path.isdir(val):
                log.info("Using SDK from $%s: %s", var, val)
                return val
        home = os.getenv("HOME", "")
        default = os.path.join(home, ".termux-builder", "sdk")
        if os.path.isdir(default):
            return default
        raise EnvironmentError(
            "Android SDK not found. Set ANDROID_SDK or run: termux-builder setup"
        )

    def _find_bin_direct(self, name):
        return find_bin(name) is not None

    def _resolve_bin(self, name, bins_config):
        if name in bins_config:
            return bins_config[name]
        path = find_bin(name)
        if path:
            return path
        return name

    def find_java_files(self, base_dir=None):
        from builder.utils import find_files
        base = base_dir or self.sources_dir
        return find_files(base, ".java")

    def find_kotlin_files(self, base_dir=None):
        from builder.utils import find_files
        base = base_dir or self.sources_dir
        return find_files(base, ".kt")

    def find_lib_jars(self):
        from builder.utils import find_files
        return find_files(self.libs_dir, ".jar")

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
