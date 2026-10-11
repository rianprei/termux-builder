import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from builder import kapt


def jar_bytes(entry, content=b"class"):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        archive.writestr(entry, content)
    return out.getvalue()


def distribution(extra=None):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        archive.writestr('kotlinc/lib/kotlin-compiler.jar', jar_bytes('org/jetbrains/kotlin/cli/jvm/K2JVMCompiler.class'))
        archive.writestr('kotlinc/lib/kotlin-stdlib.jar', jar_bytes('kotlin/Unit.class'))
        if extra:
            archive.writestr(*extra)
    return out.getvalue()


class KaptRuntimeTests(unittest.TestCase):
    def test_available_java_is_used_for_fallback(self):
        config = SimpleNamespace(bin_kotlinc='kotlinc')
        with patch('builder.kapt._detect_kotlinc_version', return_value='2.0.0'), patch(
            'builder.kapt.find_bin', return_value='/jdk/bin/java'
        ), patch('builder.kapt.setup_k1_compiler', return_value=['compiler.jar']), patch(
            'builder.kapt.setup_kapt_plugin', return_value='plugin.jar'
        ):
            prefix, plugin = kapt.resolve_kapt_toolchain(config)
        self.assertEqual(prefix, ['/jdk/bin/java', '-cp', 'compiler.jar', 'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler'])
        self.assertEqual(plugin, 'plugin.jar')

    def test_missing_java_fails_before_fallback_downloads(self):
        config = SimpleNamespace(bin_kotlinc='kotlinc')
        with patch('builder.kapt._detect_kotlinc_version', return_value='2.0.0'), patch(
            'builder.kapt.find_bin', return_value=None
        ), patch('builder.kapt.setup_k1_compiler', return_value=['compiler.jar']) as compiler, patch(
            'builder.kapt.setup_kapt_plugin', return_value='plugin.jar'
        ) as plugin:
            with self.assertRaisesRegex(RuntimeError, 'java not found'):
                kapt.resolve_kapt_toolchain(config)
            compiler.assert_not_called()
            plugin.assert_not_called()


class KotlinDistributionTests(unittest.TestCase):
    def response(self, data):
        response = Mock(status_code=200)
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


class KaptPluginTests(unittest.TestCase):
    def test_corrupt_cached_plugin_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / 'kapt'
            directory.mkdir()
            (directory / 'kapt-1.9.24.jar').write_bytes(b'corrupt')
            with self.assertRaises(RuntimeError):
                kapt.setup_kapt_plugin(SimpleNamespace(cache_dir=temp), '1.9.24')

    def test_version_traversal_is_rejected_before_download(self):
        with tempfile.TemporaryDirectory() as temp, patch('builder.kapt.requests.get') as get:
            with self.assertRaises(ValueError):
                kapt.setup_kapt_plugin(SimpleNamespace(cache_dir=temp), '../../escape')
            get.assert_not_called()

    def test_valid_plugin_reuses_cache_without_network(self):
        response = Mock(status_code=200)
        response.iter_content.return_value = [jar_bytes('org/jetbrains/kotlin/kapt3/Kapt3ComponentRegistrar.class', b'\xca\xfe\xba\xbe\x00\x00\x00\x34\x00\x02')]
        with tempfile.TemporaryDirectory() as temp:
            config = SimpleNamespace(cache_dir=temp)
            with patch('builder.kapt.requests.get', return_value=response) as get:
                path = kapt.setup_kapt_plugin(config, '1.9.24')
                self.assertEqual(kapt.setup_kapt_plugin(config, '1.9.24'), path)
                get.assert_called_once()
            response.close.assert_called_once()

    def test_invalid_download_is_not_published(self):
        response = Mock(status_code=200)
        response.iter_content.return_value = [b'not a jar']
        with tempfile.TemporaryDirectory() as temp:
            with patch('builder.kapt.requests.get', return_value=response):
                with self.assertRaises(RuntimeError):
                    kapt.setup_kapt_plugin(SimpleNamespace(cache_dir=temp), '1.9.24')
            self.assertEqual(list((Path(temp) / 'kapt').iterdir()), [])

    def test_symlinked_plugin_preserves_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / 'kapt'
            directory.mkdir()
            target = root / 'keep'
            target.write_bytes(b'keep')
            (directory / 'kapt-1.9.24.jar').symlink_to(target)
            with self.assertRaises(RuntimeError):
                kapt.setup_kapt_plugin(SimpleNamespace(cache_dir=temp), '1.9.24')
            self.assertEqual(target.read_bytes(), b'keep')

    def test_interrupted_plugin_download_cleans_staging(self):
        import requests
        response = Mock(status_code=200)
        def chunks(*args):
            yield b'partial'
            raise requests.ConnectionError('interrupted')
        response.iter_content.side_effect = chunks
        with tempfile.TemporaryDirectory() as temp:
            with patch('builder.kapt.requests.get', return_value=response):
                with self.assertRaisesRegex(RuntimeError, 'download failed'):
                    kapt.setup_kapt_plugin(SimpleNamespace(cache_dir=temp), '1.9.24')
            self.assertEqual(list((Path(temp) / 'kapt').iterdir()), [])
        response.close.assert_called_once()


    def test_invalid_registrar_class_header_is_rejected(self):
        response = Mock(status_code=200)
        response.iter_content.return_value = [jar_bytes('org/jetbrains/kotlin/kapt3/Kapt3ComponentRegistrar.class')]
        with tempfile.TemporaryDirectory() as temp:
            with patch('builder.kapt.requests.get', return_value=response):
                with self.assertRaisesRegex(RuntimeError, 'class header'):
                    kapt.setup_kapt_plugin(SimpleNamespace(cache_dir=temp), '1.9.24')
            self.assertEqual(list((Path(temp) / 'kapt').iterdir()), [])

    def test_plugin_redirect_is_refused_before_streaming(self):
        response = Mock(status_code=302)
        with tempfile.TemporaryDirectory() as temp:
            with patch('builder.kapt.requests.get', return_value=response) as get:
                with self.assertRaisesRegex(RuntimeError, 'redirects'):
                    kapt.setup_kapt_plugin(SimpleNamespace(cache_dir=temp), '1.9.24')
                self.assertFalse(get.call_args.kwargs['allow_redirects'])
                response.iter_content.assert_not_called()


class KotlinRedirectTests(unittest.TestCase):
    def test_http_redirect_is_rejected_before_second_request(self):
        response = Mock(status_code=302, headers={'Location': 'http://release-assets.githubusercontent.com/compiler.zip'})
        with patch('builder.kapt.requests.get', return_value=response) as get:
            with self.assertRaises(RuntimeError):
                kapt._k1_download_response()
            get.assert_called_once()
        response.close.assert_called_once()

    def test_official_https_redirect_is_followed_without_automatic_redirects(self):
        redirect = Mock(status_code=302, headers={'Location': 'https://release-assets.githubusercontent.com/compiler.zip?signature=private'})
        final = Mock(status_code=200)
        with patch('builder.kapt.requests.get', side_effect=[redirect, final]) as get:
            self.assertIs(kapt._k1_download_response(), final)
            self.assertTrue(all(call.kwargs['allow_redirects'] is False for call in get.call_args_list))
        redirect.close.assert_called_once()
        final.close.assert_not_called()

    def test_untrusted_redirect_is_rejected_before_second_request(self):
        response = Mock(status_code=302, headers={'Location': 'https://untrusted.invalid/compiler.zip'})
        with patch('builder.kapt.requests.get', return_value=response) as get:
            with self.assertRaises(RuntimeError):
                kapt._k1_download_response()
            get.assert_called_once()

    def test_redirect_loop_is_bounded_and_responses_closed(self):
        responses = [Mock(status_code=302, headers={'Location': 'https://github.com/loop'}) for _ in range(6)]
        with patch('builder.kapt.requests.get', side_effect=responses) as get:
            with self.assertRaisesRegex(RuntimeError, 'five redirects'):
                kapt._k1_download_response()
            self.assertEqual(get.call_count, 6)
        for response in responses:
            response.close.assert_called_once()

    def test_redirect_credentials_are_rejected_without_exposing_secret(self):
        response = Mock(status_code=302, headers={'Location': 'https://token-secret@github.com/compiler.zip'})
        with patch('builder.kapt.requests.get', return_value=response) as get:
            with self.assertRaises(RuntimeError) as error:
                kapt._k1_download_response()
            self.assertNotIn('token-secret', str(error.exception))
            get.assert_called_once()

    def test_malformed_port_is_rejected_before_second_request(self):
        response = Mock(status_code=302, headers={'Location': 'https://github.com:invalid/compiler.zip'})
        with patch('builder.kapt.requests.get', return_value=response) as get:
            with self.assertRaisesRegex(RuntimeError, 'Invalid'):
                kapt._k1_download_response()
            get.assert_called_once()
