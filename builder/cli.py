import argparse
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import yaml
import requests

from builder import __version__
from builder.utils import color, log


def main():
    parser = argparse.ArgumentParser(
        prog="termux-builder",
        description="Android Studio no Termux — build APK sem root, sem PC",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--version", action="version", version=f"termux-builder {__version__}")

    sub = parser.add_subparsers(dest="command")

    build_p = sub.add_parser("build", help="Build APK from project")
    build_p.add_argument("project", help="Project directory")
    build_p.add_argument("--clean", action="store_true", help="Clean build")
    build_p.add_argument("--install", action="store_true", help="Install after build")
    build_p.add_argument("--flavor", help="Build flavor (declared under 'flavors:' in project.yml)")
    build_p.add_argument("--device", help="Target device serial for install")

    init_p = sub.add_parser("init", help="Create new project")
    init_p.add_argument("name", help="Project name")
    init_p.add_argument("--package", default="com.example.app", help="Package name")

    clean_p = sub.add_parser("clean", help="Remove build artifacts")
    clean_p.add_argument("project", help="Project directory")

    deps_p = sub.add_parser("deps", help="Download dependencies")
    deps_p.add_argument("project", help="Project directory")

    sub.add_parser("doctor", help="Check build environment")

    setup_p = sub.add_parser("setup", help="Install SDK and tools")
    setup_p.add_argument("--api", type=int, default=34, help="Android API level")

    test_p = sub.add_parser("test", help="Run JUnit tests")
    test_p.add_argument("project", help="Project directory")

    lint_p = sub.add_parser("lint", help="Run lint checks")
    lint_p.add_argument("project", help="Project directory")

    dec_p = sub.add_parser("decompile", help="Decompile APK with apktool")
    dec_p.add_argument("apk", help="APK file to decompile")
    dec_p.add_argument("-o", "--output", help="Output directory")
    dec_p.add_argument("-f", "--force", action="store_true", help="Overwrite existing output")

    rec_p = sub.add_parser("recompile", help="Recompile decompiled APK with apktool")
    rec_p.add_argument("dir", help="Decompiled project directory")
    rec_p.add_argument("-o", "--output", help="Output APK path")

    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        format="%(message)s",
        level=level,
        stream=sys.stdout,
    )

    try:
        if args.command == "build":
            _build(args)
        elif args.command == "init":
            _init(args)
        elif args.command == "clean":
            _clean(args)
        elif args.command == "deps":
            _deps(args)
        elif args.command == "doctor":
            _doctor()
        elif args.command == "setup":
            _setup(args)
        elif args.command == "test":
            _test(args)
        elif args.command == "lint":
            _lint(args)
        elif args.command == "decompile":
            from builder.decompile import decompile
            decompile(args.apk, args.output, args.force)
        elif args.command == "recompile":
            from builder.decompile import recompile
            recompile(args.dir, args.output)
        else:
            parser.print_help()
    except (FileNotFoundError, ValueError, RuntimeError, subprocess.CalledProcessError, yaml.YAMLError, ET.ParseError, requests.RequestException) as e:
        log.error(color("BUILD FAILED: %s", "red"), e)
        sys.exit(1)
    except KeyboardInterrupt:
        log.error(color("Interrupted", "red"))
        sys.exit(130)


def _build(args):
    from builder.config import Config
    from builder import deps, buildconfig, resources, compiler, dexer, packager, signer, binding, manifest, aidl

    start = time.time()
    log.info(color("termux-builder v%s", "bold"), __version__)
    log.info("")

    config = Config(args.project, flavor=getattr(args, "flavor", None))

    if args.clean:
        _do_clean(config)

    os.makedirs(config.build_dir, exist_ok=True)
    os.makedirs(config.bin_dir, exist_ok=True)

    deps.resolve(config)
    manifest.merge(config)
    resources.compile_resources(config)
    density_splits = resources.link_resources(config) or []
    buildconfig.generate(config)

    aidl.compile(config)

    if config.view_binding:
        binding.generate(config)

    compiler.compile_java(config)
    compiler.compile_kotlin(config)
    dexer.dex(config)

    abis = packager.available_abis(config) if config.abi_splits else []
    install_set = None

    if abis:
        apk_paths = []
        for abi in abis:
            packager.package(config, abi=abi)
            apk_paths.append(signer.sign(config, abi=abi))
        apk_path = apk_paths[0]
        log.info("")
        log.info(color("BUILD SUCCESSFUL in %.1fs", "green"), time.time() - start)
        for p in apk_paths:
            log.info("APK: %s", p)
    else:
        packager.package(config)
        apk_path = signer.sign(config)

        if density_splits:
            signed_splits = []
            for density, split_apk in density_splits:
                signed_out = os.path.join(config.build_dir, f"{config.name}-{density}-{config.build_type}.apk")
                signer.sign_apk(config, split_apk, signed_out)
                signed_splits.append(signed_out)
            install_set = [apk_path] + signed_splits
            log.info("")
            log.info(color("BUILD SUCCESSFUL in %.1fs", "green"), time.time() - start)
            log.info("Base APK: %s", apk_path)
            for p in signed_splits:
                log.info("Density split: %s", p)
            log.info("Install with: adb install-multiple %s",
                     " ".join([os.path.basename(apk_path)] + [os.path.basename(p) for p in signed_splits]))
        else:
            elapsed = time.time() - start
            log.info("")
            log.info(color("BUILD SUCCESSFUL in %.1fs", "green"), elapsed)
            log.info("APK: %s", apk_path)

    if args.install:
        from builder import installer
        if install_set:
            installer.install_multiple(install_set, args.device)
        else:
            installer.install(apk_path, args.device)


def _test(args):
    from builder.config import Config
    from builder import testing
    config = Config(args.project)
    if not testing.run_tests(config):
        sys.exit(1)


def _lint(args):
    from builder.config import Config
    from builder import lint
    config = Config(args.project)
    issues = lint.check(config)
    if issues:
        log.warning(color("%d lint issue(s) found", "yellow"), issues)
        sys.exit(1)
    else:
        log.info(color("Lint passed", "green"))


def _init(args):
    from builder.signer import generate_debug_keystore

    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*", args.package):
        log.error("Invalid package name: %s (must be Java-style, e.g. com.example.app)", args.package)
        sys.exit(1)

    project_dir = os.path.abspath(args.name)
    if os.path.exists(project_dir):
        log.error("Directory already exists: %s", project_dir)
        sys.exit(1)

    pkg_path = args.package.replace(".", os.sep)
    os.makedirs(os.path.join(project_dir, "src", "java", pkg_path))
    os.makedirs(os.path.join(project_dir, "src", "res", "layout"))
    os.makedirs(os.path.join(project_dir, "src", "res", "values"))
    os.makedirs(os.path.join(project_dir, "src", "res", "drawable"))
    os.makedirs(os.path.join(project_dir, "src", "assets"), exist_ok=True)

    app_name = args.name.replace("-", " ").replace("_", " ").title()

    with open(os.path.join(project_dir, "project.yml"), "w") as f:
        f.write(f"""name: {args.name}
build-path: .build
libs-path: .libs
cache-path: .cache

dependencies: []

android:
  target-sdk: 34
  min-sdk: 21
  version-code: 1
  version-name: "1.0.0"

  manifest-path: AndroidManifest.xml
  sources-path: src/java
  res-path: src/res
  assets-path: src/assets
  jni-path: src/jniLibs

  build-type: debug
  java-version: 17
  view-binding: false
  compose: false
  r8: false

  keystore-path: debug.keystore
  keystore-alias: androiddebugkey
  keystore-store-pass: android
  keystore-key-pass: android
""")

    with open(os.path.join(project_dir, "AndroidManifest.xml"), "w") as f:
        f.write(f"""<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="{args.package}">

    <application
        android:label="{app_name}"
        android:theme="@style/AppTheme"
        android:allowBackup="false">

        <activity
            android:name=".MainActivity"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>

    </application>
</manifest>
""")

    main_java = os.path.join(project_dir, "src", "java", pkg_path, "MainActivity.java")
    with open(main_java, "w") as f:
        f.write(f"""package {args.package};

import android.app.Activity;
import android.os.Bundle;
import android.widget.TextView;

public class MainActivity extends Activity {{
    @Override
    protected void onCreate(Bundle savedInstanceState) {{
        super.onCreate(savedInstanceState);
        TextView tv = new TextView(this);
        tv.setText("Hello from termux-builder!");
        tv.setTextSize(24f);
        tv.setPadding(32, 32, 32, 32);
        setContentView(tv);
    }}
}}
""")

    with open(os.path.join(project_dir, "src", "res", "values", "styles.xml"), "w") as f:
        f.write("""<?xml version="1.0" encoding="utf-8"?>
<resources>
    <style name="AppTheme" parent="android:Theme.Material.Light">
    </style>
</resources>
""")

    with open(os.path.join(project_dir, "src", "res", "values", "strings.xml"), "w") as f:
        f.write(f"""<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">{app_name}</string>
</resources>
""")

    generate_debug_keystore(os.path.join(project_dir, "debug.keystore"))

    log.info(color("Project created: %s", "green"), project_dir)
    log.info("")
    log.info("Next steps:")
    log.info("  cd %s", args.name)
    log.info("  termux-builder build .")


def _clean(args):
    from builder.config import Config
    config = Config(args.project)
    _do_clean(config)
    log.info(color("Clean complete", "green"))


def _do_clean(config):
    if os.path.isdir(config.build_dir):
        shutil.rmtree(config.build_dir)
        log.info("Removed %s", config.build_dir)


def _deps(args):
    from builder.config import Config
    from builder import deps
    config = Config(args.project)
    deps.resolve(config)


def _doctor():
    from builder.doctor import check
    issues = check()
    sys.exit(1 if issues > 0 else 0)


def _setup(args):
    import requests

    home = os.getenv("HOME", "")
    sdk_dir = os.path.join(home, ".termux-builder", "sdk")
    platform_dir = os.path.join(sdk_dir, "platforms", f"android-{args.api}")
    jar_path = os.path.join(platform_dir, "android.jar")

    if os.path.isfile(jar_path):
        log.info("android.jar already exists: %s", jar_path)
        return

    os.makedirs(platform_dir, exist_ok=True)

    url = (
        f"https://github.com/Reginer/aosp-android-jar/raw/main/"
        f"android-{args.api}/android.jar"
    )

    log.info("Downloading android.jar (API %d)...", args.api)
    tmp_path = jar_path + ".tmp"
    try:
        r = requests.get(url, timeout=120, stream=True)
        r.raise_for_status()
        with open(tmp_path, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        os.rename(tmp_path, jar_path)
    except Exception as e:
        log.error("Download failed: %s", e)
        log.info("Alternative: manually place android.jar at %s", jar_path)
        sys.exit(1)

    size_mb = os.path.getsize(jar_path) / (1024 * 1024)
    log.info(color("android.jar downloaded (%.1f MB)", "green"), size_mb)

    env_line = f'export ANDROID_SDK="{sdk_dir}"'
    for rc in (os.path.join(home, ".bashrc"), os.path.join(home, ".zshrc")):
        if not os.path.isfile(rc):
            continue
        with open(rc) as f:
            if "ANDROID_SDK" in f.read():
                continue
        with open(rc, "a") as f:
            f.write(f"\n{env_line}\n")
        log.info("Added ANDROID_SDK to %s", os.path.basename(rc))

    os.environ["ANDROID_SDK"] = sdk_dir
    log.info(color("Setup complete!", "green"))
    log.info("SDK: %s", sdk_dir)
