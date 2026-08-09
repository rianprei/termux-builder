import os
import subprocess
import tempfile
from builder.utils import log, run, find_bin


def pull(package, db_name, device=None, output=None):
    """Pull an app's SQLite database off-device and dump its schema — CLI
    replacement for Android Studio's Database Inspector (no live inspection,
    since that needs a persistent debug bridge; this is inspect-after-pull)."""
    adb = find_bin("adb") or find_bin("termux-adb")
    if not adb:
        raise FileNotFoundError("adb not found — install termux-adb or add adb to PATH")
    sqlite3 = find_bin("sqlite3")
    if not sqlite3:
        raise FileNotFoundError("sqlite3 not found. Run: pkg install sqlite")

    remote_path = f"/data/data/{package}/databases/{db_name}"
    dest = output or os.path.join(tempfile.gettempdir(), db_name)

    args = [adb]
    if device:
        args += ["-s", device]
    args += ["exec-out", "run-as", package, "cat", remote_path]

    log.info("Pulling %s from %s", db_name, package)
    # binary content — utils.run forces text=True, which corrupts bytes on
    # decode/encode round-trip, so this shells out raw instead
    result = subprocess.run(args, capture_output=True, check=False)
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError(f"Could not pull {remote_path} — check package/db name and that app is debuggable")
    with open(dest, "wb") as f:
        f.write(result.stdout)

    log.info("Saved: %s", dest)
    log.info("")
    log.info("Schema:")
    schema = run([sqlite3, dest, ".schema"], capture=True, check=False)
    log.info(schema.stdout)

    log.info("Tables:")
    tables = run([sqlite3, dest, ".tables"], capture=True, check=False)
    log.info(tables.stdout)

    return dest
