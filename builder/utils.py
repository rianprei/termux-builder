import fcntl
import hashlib
import logging
import os
import shutil
import stat
import subprocess
from contextlib import contextmanager

log = logging.getLogger("termux-builder")


@contextmanager
def _library_dex_cache_lock(cache_root):
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise RuntimeError("DEX cache locking requires O_NOFOLLOW support")
    lock_path = os.path.join(cache_root, ".library-dex.lock")
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | nofollow, 0o600)
    except OSError as exc:
        raise RuntimeError(f"Cannot open DEX cache lock safely: {lock_path}") from exc
    try:
        if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
            raise RuntimeError(f"DEX cache lock must be a regular file: {lock_path}")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(lock_fd)


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


def path_is_within(root, path):
    root = os.path.realpath(root)
    path = os.path.realpath(path)
    try:
        return os.path.commonpath((root, path)) == root
    except ValueError:
        return False


def is_reserved_maven_cache_path(libs_dir, path):
    cache_root = os.path.join(libs_dir, ".termux-builder", "maven")
    return path_is_within(cache_root, path)


def ensure_output_path(build_dir, path, label="Build output"):
    path = os.path.abspath(path)
    if os.path.islink(path):
        raise ValueError(f"{label} must not be a symlink: {path}")
    build_root = os.path.realpath(build_dir)
    output_parent = os.path.realpath(os.path.dirname(path))
    if not path_is_within(build_root, output_parent):
        raise ValueError(f"{label} must stay inside the build directory: {path}")
    return path


def variant_name(config):
    flavor = getattr(config, "flavor", None)
    return f"{config.name}-{flavor}" if flavor else config.name


def dex_sort_key(path):
    name = os.path.basename(path)
    if name == "classes.dex":
        return (0, 1, path)
    if name.startswith("classes") and name.endswith(".dex"):
        number = name[7:-4]
        if number.isdigit():
            return (0, int(number), path)
    return (1, 0, path)


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path
