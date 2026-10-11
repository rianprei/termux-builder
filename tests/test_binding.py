import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from builder import binding


class BindingGenerationTests(unittest.TestCase):
    def config(self, root):
        return SimpleNamespace(build_dir=str(root / 'build'), binding_dir=str(root / 'build/binding'),
                               res_dir=str(root / 'res'), package_name='org.example', view_binding=True)

    def test_deleted_layout_removes_generated_binding(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            layout = root / 'res/layout/screen.xml'
            layout.parent.mkdir(parents=True)
            layout.write_text('<LinearLayout/>')
            config = self.config(root)
            binding.generate(config)
            output = Path(config.binding_dir) / 'org/example/databinding/ScreenBinding.java'
            self.assertTrue(output.exists())
            layout.unlink()
            binding.generate(config)
            self.assertFalse(output.exists())

    def test_invalid_layout_fails_explicitly(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            layout = root / 'res/layout/broken.xml'
            layout.parent.mkdir(parents=True)
            layout.write_text('<LinearLayout>')
            with self.assertRaisesRegex(ValueError, 'broken.xml'):
                binding.generate(self.config(root))

    def test_symlinked_output_preserves_external_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = self.config(root)
            Path(config.build_dir).mkdir()
            outside = root / 'outside'
            outside.mkdir()
            sentinel = outside / 'Keep.java'
            sentinel.write_text('keep')
            Path(config.binding_dir).symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                binding.generate(config)
            self.assertEqual(sentinel.read_text(), 'keep')
