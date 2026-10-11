import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from builder import kapt


def jar_bytes(entry):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        archive.writestr(entry, b'class')
    return out.getvalue()


def distribution(extra=None):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        archive.writestr('kotlinc/lib/kotlin-compiler.jar', jar_bytes('org/jetbrains/kotlin/cli/jvm/K2JVMCompiler.class'))
        archive.writestr('kotlinc/lib/kotlin-stdlib.jar', jar_bytes('kotlin/Unit.class'))
        if extra:
            archive.writestr(*extra)
    return out.getvalue()


class KotlinDistributionTests(unittest.TestCase):
    def response(self, data):
        response = Mock()
        response.iter_content.return_value = [data]
        return response

    def test_empty_existing_lib_directory_is_not_a_valid_compiler(self):
        with tempfile.TemporaryDirectory() as temp:
            lib = Path(temp) / 'kapt' / ('kotlinc-' + kapt._K1_VERSION) / 'kotlinc/lib'
            lib.mkdir(parents=True)
            with self.assertRaises(RuntimeError):
                kapt.setup_k1_compiler(SimpleNamespace(cache_dir=temp))

    def test_valid_distribution_publishes_and_reuses_offline(self):
        with tempfile.TemporaryDirectory() as temp:
            config = SimpleNamespace(cache_dir=temp)
            with patch('builder.kapt.requests.get', return_value=self.response(distribution())) as get:
                first = kapt.setup_k1_compiler(config)
                second = kapt.setup_k1_compiler(config)
                self.assertEqual(first, second)
                self.assertEqual(len(first), 2)
                get.assert_called_once()

    def test_traversal_distribution_is_rejected_without_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch('builder.kapt.requests.get', return_value=self.response(distribution(('../escape', b'bad')))):
                with self.assertRaises(RuntimeError):
                    kapt.setup_k1_compiler(SimpleNamespace(cache_dir=temp))
            self.assertFalse((Path(temp) / 'kapt' / ('kotlinc-' + kapt._K1_VERSION)).exists())

    def test_failed_download_leaves_no_partial_distribution(self):
        import requests
        with tempfile.TemporaryDirectory() as temp:
            response = self.response(b'partial')
            def chunks(*args):
                yield b'partial'
                raise requests.ConnectionError('interrupted')
            response.iter_content.side_effect = chunks
            with patch('builder.kapt.requests.get', return_value=response):
                with self.assertRaises(RuntimeError):
                    kapt.setup_k1_compiler(SimpleNamespace(cache_dir=temp))
            self.assertEqual(list((Path(temp) / 'kapt').iterdir()), [])

    def test_corrupt_cached_jar_fails_offline(self):
        with tempfile.TemporaryDirectory() as temp:
            config = SimpleNamespace(cache_dir=temp)
            with patch('builder.kapt.requests.get', return_value=self.response(distribution())):
                paths = kapt.setup_k1_compiler(config)
            Path(paths[0]).write_bytes(b'corrupt')
            with patch('builder.kapt.requests.get') as get:
                with self.assertRaises(RuntimeError):
                    kapt.setup_k1_compiler(config)
                get.assert_not_called()

    def test_symlink_distribution_entry_is_rejected(self):
        import stat
        data = io.BytesIO(distribution())
        with zipfile.ZipFile(data, 'a') as archive:
            link = zipfile.ZipInfo('kotlinc/lib/link.jar')
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(link, '/outside')
        with tempfile.TemporaryDirectory() as temp:
            with patch('builder.kapt.requests.get', return_value=self.response(data.getvalue())):
                with self.assertRaises(RuntimeError):
                    kapt.setup_k1_compiler(SimpleNamespace(cache_dir=temp))
            self.assertEqual(list((Path(temp) / 'kapt').iterdir()), [])

    def test_symlink_cache_preserves_external_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cache = root / 'cache'
            cache.mkdir()
            outside = root / 'outside'
            outside.mkdir()
            sentinel = outside / 'keep'
            sentinel.write_text('keep')
            (cache / 'kapt').symlink_to(outside, target_is_directory=True)
            with self.assertRaises(RuntimeError):
                kapt.setup_k1_compiler(SimpleNamespace(cache_dir=str(cache)))
            self.assertEqual(sentinel.read_text(), 'keep')

    def test_zip_directory_limit_is_checked_before_zipfile_parsing(self):
        import struct
        data = bytearray(distribution())
        end = data.rfind(b'PK\x05\x06')
        struct.pack_into('<HH', data, end + 8, 10001, 10001)
        with tempfile.TemporaryDirectory() as temp:
            with patch('builder.kapt.requests.get', return_value=self.response(bytes(data))), patch('builder.kapt.zipfile.ZipFile') as parser:
                with self.assertRaisesRegex(RuntimeError, 'directory limits'):
                    kapt.setup_k1_compiler(SimpleNamespace(cache_dir=temp))
                parser.assert_not_called()

    def test_publication_race_reuses_valid_winner(self):
        import os
        with tempfile.TemporaryDirectory() as temp:
            config = SimpleNamespace(cache_dir=temp)
            original = os.rename
            def competing_publish(source, destination):
                original(source, destination)
                raise FileExistsError('another publisher won')
            with patch('builder.kapt.requests.get', return_value=self.response(distribution())), patch('builder.kapt.os.rename', side_effect=competing_publish):
                self.assertEqual(len(kapt.setup_k1_compiler(config)), 2)

    def test_forged_entry_count_is_rejected_before_zipfile_parsing(self):
        import struct
        data = bytearray(distribution())
        end = data.rfind(b'PK\x05\x06')
        struct.pack_into('<HH', data, end + 8, 1, 1)
        with tempfile.TemporaryDirectory() as temp:
            with patch('builder.kapt.requests.get', return_value=self.response(bytes(data))), patch('builder.kapt.zipfile.ZipFile') as parser:
                with self.assertRaisesRegex(RuntimeError, 'count mismatch'):
                    kapt.setup_k1_compiler(SimpleNamespace(cache_dir=temp))
                parser.assert_not_called()
