import subprocess
from builder.utils import log, find_bin


def tail(package=None, device=None):
    """Wrap adb logcat, filtered to a package's PID when given — CLI
    replacement for Android Studio's integrated Logcat viewer."""
    adb = find_bin("adb") or find_bin("termux-adb")
    if not adb:
        raise FileNotFoundError("adb not found — install termux-adb or add adb to PATH")

    args = [adb]
    if device:
        args += ["-s", device]

    if package:
        pid_result = subprocess.run(
            args + ["shell", "pidof", "-s", package],
            capture_output=True, text=True, check=False,
        )
        pid = pid_result.stdout.strip()
        if not pid:
            raise RuntimeError(f"{package} is not running — launch the app first")
        log.info("Streaming logcat for %s (pid %s) — Ctrl+C to stop", package, pid)
        args += ["logcat", "--pid", pid]
    else:
        log.info("Streaming full logcat — Ctrl+C to stop")
        args += ["logcat"]

    try:
        subprocess.run(args, check=False)
    except KeyboardInterrupt:
        pass
