import json
import os
from builder.utils import log


class BuildCache:
    def __init__(self, cache_path):
        self.cache_file = os.path.join(cache_path, ".build_cache.json")
        self.data = self._load()

    def _load(self):
        if not os.path.isfile(self.cache_file):
            return {}
        try:
            with open(self.cache_file) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def save(self):
        os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
        with open(self.cache_file, "w") as f:
            json.dump(self.data, f, indent=2)

    def is_modified(self, filepath):
        if not os.path.isfile(filepath):
            return True
        mtime = os.path.getmtime(filepath)
        cached = self.data.get(filepath)
        return cached != mtime

    def mark(self, filepath):
        if os.path.isfile(filepath):
            self.data[filepath] = os.path.getmtime(filepath)

    def get_modified_files(self, base_dir, suffix):
        modified = []
        if not os.path.isdir(base_dir):
            return modified
        for root, _, files in os.walk(base_dir):
            for f in files:
                if f.endswith(suffix):
                    full = os.path.join(root, f)
                    if self.is_modified(full):
                        modified.append(full)
        return modified

    def mark_directory(self, base_dir, suffix):
        if not os.path.isdir(base_dir):
            return
        for root, _, files in os.walk(base_dir):
            for f in files:
                if f.endswith(suffix):
                    self.mark(os.path.join(root, f))
