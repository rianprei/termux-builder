import os
import zipfile
from builder.utils import log, run, find_bin


def analyze(apk_path):
    """APK size breakdown by category — CLI replacement for Android Studio's APK analyzer."""
    if not os.path.isfile(apk_path):
        raise FileNotFoundError(f"APK not found: {apk_path}")

    total = os.path.getsize(apk_path)
    buckets = {"dex": 0, "resources": 0, "assets": 0, "native_libs": 0, "manifest": 0, "other": 0}

    with zipfile.ZipFile(apk_path) as z:
        for info in z.infolist():
            name = info.filename
            size = info.file_size
            if name.endswith(".dex"):
                buckets["dex"] += size
            elif name.startswith("res/") or name == "resources.arsc":
                buckets["resources"] += size
            elif name.startswith("assets/"):
                buckets["assets"] += size
            elif name.startswith("lib/"):
                buckets["native_libs"] += size
            elif name == "AndroidManifest.xml":
                buckets["manifest"] += size
            else:
                buckets["other"] += size

    log.info("APK: %s", apk_path)
    log.info("Total size (compressed on disk): %s", _human(total))
    log.info("")
    log.info("Uncompressed content breakdown:")
    for name, size in sorted(buckets.items(), key=lambda kv: -kv[1]):
        if size:
            log.info("  %-14s %s", name, _human(size))

    aapt2 = find_bin("aapt2")
    if aapt2:
        result = run([aapt2, "dump", "badging", apk_path], capture=True, check=False)
        for line in result.stdout.splitlines():
            if line.startswith("package:") or line.startswith("application-label:") or line.startswith("sdkVersion:"):
                log.info(line)

    return buckets


def _human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024
    return f"{n:.1f}TB"
