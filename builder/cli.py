import argparse
import logging
import os
import shutil
import sys
import time

from builder import __version__
from builder.utils import color, log


def main():
    parser = argparse.ArgumentParser(
        prog="termux-builder",
        description="Android Studio no Termux — build APK/AAB sem root, sem PC",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--version", action="version", version=f"termux-builder {__version__}")

    sub = parser.add_subparsers(dest="command")

    build_p = sub.add_parser("build", help="Build APK from project")
    build_p.add_argument("project", help="Project directory")
    build_p.add_argument("--clean", action="store_true", help="Clean build")
    build_p.add_argument("--install", action="store_true", help="Install after build")
    build_p.add_argument("--device", help="Target device serial for install")
    build_p.add_argument("--aab", action="store_true", help="Build AAB instead of APK")
    build_p.add_argument("--no-cache", action="store_true", help="Disable incremental cache")

    init_p = sub.add_parser("init", help="Create new project")
    init_p.add_argument("name", help="Project name")
    init_p.add_argument("--package", default="com.example.app", help="Package name")

    clean_p = sub.add_parser("clean", help="Remove build artifacts")
    clean_p.add_argument("project", help="Project directory")

    deps_p = sub.add_parser("deps", help="Download dependencies")
    deps_p.add_argument("project", help="Project directory")

    test_p = sub.add_parser("test", help="Run unit tests")
    test_p.add_argument("project", help="Project directory")

    lint_p = sub.add_parser("lint", help="Run lint checks")
    lint_p.add_argument("project", help="Project directory")

    sub.add_parser("doctor", help="Check build environment")

    setup_p = sub.add_parser("setup", help="Install SDK and tools")
    setup_p.add_argument("--api", type=int, default=34, help="Android API level")

    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        format="%(message)s",
        level=level,
        stream=sys.stdout,
    )

    commands = {
        "build": _build,
        "init": _init,
        "clean": _clean,
        "deps": _deps,
        "test": _test,
        "lint": _lint,
        "doctor": _doctor,
        "setup": _setup,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


def _build(args):
    from builder.config import Config
    from builder.cache import BuildCache
    from builder import deps, buildconfig, resources, compiler, dexer, packager, signer, binding, manifest, aidl

    start = time.time()
    log.info(color("termux-builder v%s", "bold"), __version__)
    log.info("")

    config = Config(args.project)

    if args.clean:
        _do_clean(config)

    os.makedirs(config.build_dir, exist_ok=True)
    os.makedirs(config.bin_dir, exist_ok=True)

    cache = None
    if not args.no_cache:
        cache = BuildCache(config.cache_dir)

    deps.resolve(config)
    buildconfig.generate(config)
    manifest.merge(config)
    aidl.compile(config)
    resources.compile_resources(config)
    resources.link_resources(config)

    if config.view_binding:
        binding.generate(config)

    compiler.compile_java(config)
    compiler.compile_kotlin(config)
    dexer.dex(config)

    if args.aab:
        from builder import aab
        output = aab.build_bundle(config)
        if not output:
            packager.package(config)
            output = signer.sign(config)
    else:
        packager.package(config)
        output = signer.sign(config)

    if cache:
        cache.mark_directory(config.sources_dir, ".java")
        cache.mark_directory(config.sources_dir, ".kt")
        cache.mark_directory(config.res_dir, ".xml")
        cache.save()

    elapsed = time.time() - start
    log.info("")
    log.info(color("BUILD SUCCESSFUL in %.1fs", "green"), elapsed)
    log.info("Output: %s", output)

    if args.install and not args.aab:
        from builder import installer
        installer.install(output, args.device)


def _init(args):
    from builder.signer import generate_debug_keystore

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
    os.makedirs(os.path.join(project_dir, "src", "test", pkg_path), exist_ok=True)

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
        android:allowBackup="true"
        android:theme="@style/AppTheme">

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

    with open(os.path.join(project_dir, ".gitignore"), "w") as f:
        f.write(".build/\n.cache/\n.libs/\n*.apk\n*.aab\ndebug.keystore\n")

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
    for d in (config.build_dir, config.cache_dir):
        if os.path.isdir(d):
            shutil.rmtree(d)
            log.info("Removed %s", d)


def _deps(args):
    from builder.config import Config
    from builder import deps
    config = Config(args.project)
    deps.resolve(config)


def _test(args):
    from builder.config import Config
    from builder import testing
    config = Config(args.project)
    success = testing.run_tests(config)
    sys.exit(0 if success else 1)


def _lint(args):
    from builder.config import Config
    from builder import lint
    config = Config(args.project)
    issues = lint.check(config)
    sys.exit(0 if issues == 0 else 1)


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
    try:
        r = requests.get(url, timeout=120, stream=True)
        r.raise_for_status()
        with open(jar_path, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
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
