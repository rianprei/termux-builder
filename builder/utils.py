import subprocess
import logging
import shutil
import hashlib
import os

log = logging.getLogger("termux-builder")

COLORS = {
    "green": "\033[0;32m",
    "red": "\033[0;31m",
    "yellow": "\033[1;33m",
    "blue": "\033[0;34m",
    "bold": "\033[1m",
    "reset": "\033[0m",
}


def color(text, name):
    return f"{COLORS.get(name, '')}{text}{COLORS['reset']}"


def run(args, capture=False, check=True, cwd=None, env=None):
    cmd = [str(a) for a in args]
    log.debug("$ %s", " ".join(cmd))
    return subprocess.run(cmd, capture_output=capture, text=True, check=check, cwd=cwd, env=env)


def find_bin(name):
    return shutil.which(name)


def require_bin(name):
    path = find_bin(name)
    if not path:
        raise FileNotFoundError(f"{name} not found in PATH. Run: termux-builder doctor")
    return path


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def find_files(base_dir, suffix):
    result = []
    if not os.path.isdir(base_dir):
        return result
    for root, _, files in os.walk(base_dir):
        for f in files:
            if f.endswith(suffix):
                result.append(os.path.join(root, f))
    return result


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path
