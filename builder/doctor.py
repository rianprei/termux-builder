import os
import shutil
from builder.utils import color


def check():
    issues = 0
    print()
    print(color("termux-builder doctor v1.0.0", "bold"))
    print("=" * 35)
    print()

    tools = {
        "javac": "openjdk-17",
        "kotlinc": "kotlin",
        "aapt2": "aapt2",
        "d8": "dx",
        "apksigner": "apksigner",
        "keytool": "openjdk-17",
    }

    print("Build tools:")
    for tool, pkg in tools.items():
        path = shutil.which(tool)
        if path:
            print(f"  {color('OK', 'green')}  {tool}: {path}")
        else:
            print(f"  {color('XX', 'red')}  {tool} not found — pkg install {pkg}")
            issues += 1
    print()

    print("Optional tools:")
    optional = {"adb": "termux-adb", "git": "git", "curl": "curl"}
    for tool, pkg in optional.items():
        path = shutil.which(tool)
        if path:
            print(f"  {color('OK', 'green')}  {tool}: {path}")
        else:
            print(f"  {color('--', 'yellow')}  {tool} not found — pkg install {pkg}")
    print()

    print("Android SDK:")
    sdk_path = None
    for var in ("ANDROID_SDK", "ANDROID_HOME", "ANDROID_SDK_ROOT"):
        val = os.getenv(var)
        if val and os.path.isdir(val):
            sdk_path = val
            print(f"  {color('OK', 'green')}  ${var} = {val}")
            break

    if not sdk_path:
        default = os.path.join(os.getenv("HOME", ""), ".termux-builder", "sdk")
        if os.path.isdir(default):
            sdk_path = default
            print(f"  {color('OK', 'green')}  {default}")
        else:
            print(f"  {color('XX', 'red')}  No SDK found — run: termux-builder setup")
            issues += 1

    if sdk_path:
        platforms = os.path.join(sdk_path, "platforms")
        if os.path.isdir(platforms):
            apis = sorted(os.listdir(platforms))
            if apis:
                print(f"  {color('OK', 'green')}  APIs: {', '.join(apis)}")
            else:
                print(f"  {color('XX', 'red')}  No android.jar found in {platforms}")
                issues += 1
        else:
            print(f"  {color('XX', 'red')}  platforms/ directory missing in SDK")
            issues += 1
    print()

    print("Python packages:")
    for pkg in ("yaml", "requests"):
        try:
            __import__(pkg)
            print(f"  {color('OK', 'green')}  {pkg}")
        except ImportError:
            print(f"  {color('XX', 'red')}  {pkg} — pip install {'pyyaml' if pkg == 'yaml' else pkg}")
            issues += 1
    print()

    print("=" * 35)
    if issues == 0:
        print(color("All checks passed!", "green"))
    else:
        print(color(f"{issues} issue(s) found.", "red"))
    print()
    return issues
