import os
import subprocess
from builder.utils import log, find_bin


def list_avds(sdk_dir):
    avdmanager = _tool(sdk_dir, "avdmanager")
    result = subprocess.run([avdmanager, "list", "avd"], capture_output=True, text=True, check=False)
    log.info(result.stdout)
    return result.stdout


def start(sdk_dir, avd_name, headless=True):
    """Start an AVD headless via the SDK's own emulator binary — CLI
    replacement for Android Studio's AVD Manager launch button (no window,
    no GUI device frame; the emulator process itself is the same binary)."""
    emulator_bin = _tool(sdk_dir, "emulator", subdir="emulator")
    if not os.path.isfile(emulator_bin):
        raise FileNotFoundError(
            f"emulator binary not found at {emulator_bin} — install it via sdkmanager 'emulator' package"
        )

    args = [emulator_bin, "-avd", avd_name]
    if headless:
        args += ["-no-window", "-no-audio", "-gpu", "swiftshader_indirect"]

    log.info("Starting AVD %s (%s)", avd_name, "headless" if headless else "windowed")
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log.info("Emulator launching in background — check 'adb devices' in a few seconds")


def _tool(sdk_dir, name, subdir="cmdline-tools/latest/bin"):
    candidate = os.path.join(sdk_dir, subdir, name)
    if os.path.isfile(candidate):
        return candidate
    found = find_bin(name)
    if found:
        return found
    if subdir != "emulator":
        return candidate
    return os.path.join(sdk_dir, "emulator", name)
