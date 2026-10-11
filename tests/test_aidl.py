import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from builder import aidl


class AidlInvalidationTests(unittest.TestCase):
    def test_removed_aidl_does_not_leave_generated_java(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            generated = root / 'gen' / 'aidl'
            generated.mkdir(parents=True)
            (generated / 'Deleted.java').write_text('obsolete')
            config = SimpleNamespace(build_dir=tempdir, gen_dir=str(root / 'gen'), sources_dir=str(root / 'src'))
            aidl.compile(config)
            self.assertFalse((generated / 'Deleted.java').exists())

    def test_missing_aidl_tool_fails_instead_of_skipping(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            source = root / 'src'
            source.mkdir()
            (source / 'Service.aidl').write_text('interface Service {}')
            config = SimpleNamespace(build_dir=tempdir, gen_dir=str(root / 'gen'), sources_dir=str(source))
            with patch('builder.aidl.find_bin', return_value=None):
                with self.assertRaisesRegex(RuntimeError, 'aidl'):
                    aidl.compile(config)

    def test_cleanup_preserves_other_generated_sources(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            gen = root / 'gen'
            gen.mkdir()
            resource = gen / 'R.java'
            resource.write_text('resource')
            config = SimpleNamespace(build_dir=tempdir, gen_dir=str(gen), sources_dir=str(root / 'src'))
            aidl.compile(config)
            self.assertEqual(resource.read_text(), 'resource')

    def test_external_generated_directory_is_not_removed(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            build = root / 'build'
            build.mkdir()
            outside = root / 'outside'
            generated = outside / 'aidl'
            generated.mkdir(parents=True)
            sentinel = generated / 'Keep.java'
            sentinel.write_text('keep')
            (build / 'gen').symlink_to(outside, target_is_directory=True)
            config = SimpleNamespace(build_dir=str(build), gen_dir=str(build / 'gen'), sources_dir=str(root / 'src'))
            with self.assertRaises(ValueError):
                aidl.compile(config)
            self.assertEqual(sentinel.read_text(), 'keep')
