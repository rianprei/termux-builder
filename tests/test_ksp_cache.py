import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from builder import ksp
from tests.test_kapt_cache import forged_payload


class KspCacheTests(unittest.TestCase):
    def test_forged_cached_compiler_payload_is_rejected_offline(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / 'ksp'
            directory.mkdir()
            path = directory / ('kotlin-compiler-embeddable-' + ksp._K1_KOTLIN_VERSION + '.jar')
            original = forged_payload('org/jetbrains/kotlin/cli/jvm/K2JVMCompiler.class')
            path.write_bytes(original)
            with patch('builder.ksp.requests.get') as get, patch('builder.ksp.find_bin', return_value='java'):
                with self.assertRaisesRegex(RuntimeError, 'actual ZIP payload'):
                    ksp.setup_ksp_toolchain(SimpleNamespace(cache_dir=temp))
                get.assert_not_called()
            self.assertEqual(path.read_bytes(), original)

    def test_forged_downloaded_plugin_is_not_published(self):
        response = Mock(status_code=200)
        response.iter_content.return_value = [forged_payload(ksp._PLUGIN_CLASS)]
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'plugin.jar'
            with patch('builder.ksp.requests.get', return_value=response):
                with self.assertRaisesRegex(RuntimeError, 'actual ZIP payload'):
                    ksp._download(ksp._MAVEN_BASE + '/plugin.jar', str(target))
            self.assertEqual(list(Path(temp).iterdir()), [])
        response.close.assert_called_once()

    def test_corrupt_cached_compiler_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / 'ksp'
            directory.mkdir()
            (directory / ('kotlin-compiler-embeddable-' + ksp._K1_KOTLIN_VERSION + '.jar')).write_bytes(b'corrupt')
            with patch('builder.ksp._download'), patch('builder.kapt.setup_k1_compiler', return_value=['runtime.jar']), patch('builder.ksp.find_bin', return_value='java'):
                with self.assertRaises(RuntimeError):
                    ksp.setup_ksp_toolchain(SimpleNamespace(cache_dir=temp))

    def test_invalid_download_is_not_published(self):
        response = Mock(status_code=200)
        response.iter_content.return_value = [b'not a jar']
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'plugin.jar'
            with patch('builder.ksp.requests.get', return_value=response):
                with self.assertRaises(RuntimeError):
                    ksp._download(ksp._MAVEN_BASE + '/plugin.jar', str(target))
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_missing_java_fails_before_downloads(self):
        with tempfile.TemporaryDirectory() as temp, patch('builder.ksp.find_bin', return_value=None), patch('builder.ksp.requests.get') as get:
            with self.assertRaisesRegex(RuntimeError, 'java not found'):
                ksp.setup_ksp_toolchain(SimpleNamespace(cache_dir=temp))
            get.assert_not_called()

    def test_interrupted_download_leaves_no_partial_artifact(self):
        import requests
        response = Mock(status_code=200)
        def chunks(*args):
            yield b'partial'
            raise requests.ConnectionError('interrupted')
        response.iter_content.side_effect = chunks
        with tempfile.TemporaryDirectory() as temp:
            with patch('builder.ksp.requests.get', return_value=response):
                with self.assertRaisesRegex(RuntimeError, 'download failed'):
                    ksp._download(ksp._MAVEN_BASE + '/plugin.jar', str(Path(temp) / 'plugin.jar'))
            self.assertEqual(list(Path(temp).iterdir()), [])
        response.close.assert_called_once()

    def test_symlink_destination_preserves_external_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / 'keep'
            target.write_bytes(b'keep')
            destination = root / 'plugin.jar'
            destination.symlink_to(target)
            with patch('builder.ksp.requests.get') as get:
                with self.assertRaises(RuntimeError):
                    ksp._download(ksp._MAVEN_BASE + '/plugin.jar', str(destination))
                get.assert_not_called()
            self.assertEqual(target.read_bytes(), b'keep')

    def test_unsafe_origin_is_rejected_before_network(self):
        with tempfile.TemporaryDirectory() as temp, patch('builder.ksp.requests.get') as get:
            with self.assertRaises(ValueError):
                ksp._download('http://untrusted.invalid/plugin.jar', str(Path(temp) / 'plugin.jar'))
            get.assert_not_called()

    def test_redirect_is_refused_before_streaming(self):
        response = Mock(status_code=302)
        with tempfile.TemporaryDirectory() as temp:
            with patch('builder.ksp.requests.get', return_value=response) as get:
                with self.assertRaisesRegex(RuntimeError, 'redirects'):
                    ksp._download(ksp._MAVEN_BASE + '/plugin.jar', str(Path(temp) / 'plugin.jar'))
                self.assertFalse(get.call_args.kwargs['allow_redirects'])
                response.iter_content.assert_not_called()
            self.assertEqual(list(Path(temp).iterdir()), [])
