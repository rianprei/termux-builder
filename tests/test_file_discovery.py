import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from builder.utils import find_files


class FileDiscoveryTests(unittest.TestCase):
    def test_results_have_stable_path_order(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ('z/First.java', 'a/Last.java', 'Main.java', 'Ignored.kt'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('source')
            enumeration = [(temp, ['z', 'a'], ['Main.java', 'Ignored.kt']),
                (str(root / 'z'), [], ['First.java']), (str(root / 'a'), [], ['Last.java'])]
            with patch('builder.utils.os.walk', return_value=enumeration):
                self.assertEqual(find_files(temp, '.java'), [
                    str(root / 'Main.java'), str(root / 'a/Last.java'), str(root / 'z/First.java')])

    def test_unreadable_tree_fails_instead_of_omitting_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            nested = root / 'nested'
            nested.mkdir()
            (nested / 'Required.class').write_bytes(b'class')
            original = os.scandir
            def scan(path):
                if os.fspath(path) == str(nested):
                    raise PermissionError(13, 'Permission denied', str(nested))
                return original(path)
            with patch('os.scandir', side_effect=scan):
                with self.assertRaisesRegex(RuntimeError, 'Cannot read file tree'):
                    find_files(temp, '.class')

    def test_missing_optional_directory_still_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(find_files(str(Path(temp) / 'missing'), '.java'), [])
