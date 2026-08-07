import os
import shutil
from builder.utils import color
from builder import __version__

_SYSTEM_ANDROID_JAR = "/data/data/com.termux/files/usr/share/java/android.jar"
_ECJ_JAR = "/data/data/com.termux/files/usr/share/dex/ecj.jar"


def check():
    issues = 0
    print()
    print(color(f"termux-builder doctor v{__version__}", "bold"))
    print("=" * 40)
    print()

    print("Java compiler (one required):")
    javac = shutil.which("javac")
    dalvik = shutil.which("dalvikvm")
    ecj_ok = dalvik and os.path.isfile(_ECJ_JAR)

    if javac:
        print(f"  {color('OK', 'green')}  javac: {javac}")
    else:
        print(f"  {color('--', 'yellow')}  javac not found — pkg install openjdk-17")

    if ecj_ok:
        print(f"  {color('OK', 'green')}  ecj+dalvikvm (native): {dalvik}")
    else:
        print(f"  {color('--', 'yellow')}  ecj/dalvikvm not found — pkg install ecj")

    if not javac and not ecj_ok:
        print(f"  {color('XX', 'red')}  No Java compiler! Install openjdk-17 or ecj")
        issues += 1
    print()

    print("Dexer (one required):")
    d8 = shutil.which("d8")
    dx = shutil.which("dx")
    if d8:
        print(f"  {color('OK', 'green')}  d8: {d8}")
    elif dx:
        print(f"  {color('OK', 'green')}  dx (fallback): {dx}")
    else:
        print(f"  {color('XX', 'red')}  No dexer — pkg install dx")
        issues += 1
    print()

    print("Resource tools (one required):")
    aapt2 = shutil.which("aapt2")
    aapt1 = shutil.which("aapt")
    if aapt2:
        print(f"  {color('OK', 'green')}  aapt2: {aapt2}")
    elif aapt1:
        print(f"  {color('OK', 'green')}  aapt v1 (fallback): {aapt1}")
    else:
        print(f"  {color('XX', 'red')}  No aapt — pkg install aapt2")
        issues += 1
    print()

    print("Signer:")
    for tool, pkg in [("apksigner", "apksigner"), ("keytool", "openjdk-17")]:
        path = shutil.which(tool)
        if path:
            print(f"  {color('OK', 'green')}  {tool}: {path}")
        else:
            print(f"  {color('XX', 'red')}  {tool} not found — pkg install {pkg}")
            issues += 1
    print()

    print("Android SDK / android.jar:")
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

    if sdk_path:
        platforms = os.path.join(sdk_path, "platforms")
        apis = sorted(os.listdir(platforms)) if os.path.isdir(platforms) else []
        if apis:
            print(f"  {color('OK', 'green')}  APIs: {', '.join(apis)}")
        else:
            print(f"  {color('--', 'yellow')}  No SDK platforms — run: termux-builder setup")

    if os.path.isfile(_SYSTEM_ANDROID_JAR):
        print(f"  {color('OK', 'green')}  system android.jar: {_SYSTEM_ANDROID_JAR} (no setup needed)")
    elif not sdk_path:
        print(f"  {color('XX', 'red')}  No android.jar — run: termux-builder setup")
        issues += 1
    print()

    print("Optional tools:")
    optional = {"adb": "android-tools", "kotlinc": "kotlin", "git": "git", "aidl": "aidl", "d8": "d8", "apktool": "apktool"}
    for tool, pkg in optional.items():
        path = shutil.which(tool)
        if path:
            print(f"  {color('OK', 'green')}  {tool}: {path}")
        else:
            print(f"  {color('--', 'yellow')}  {tool} — pkg install {pkg}")
    print()

    print("Python packages:")
    for pkg, pip_name in [("yaml", "pyyaml"), ("requests", "requests")]:
        try:
            __import__(pkg)
            print(f"  {color('OK', 'green')}  {pkg}")
        except ImportError:
            print(f"  {color('XX', 'red')}  {pkg} — pip install {pip_name}")
            issues += 1
    print()

    print("=" * 40)
    if issues == 0:
        print(color("All checks passed!", "green"))
    else:
        print(color(f"{issues} issue(s) found.", "red"))
    print()
    return issues
