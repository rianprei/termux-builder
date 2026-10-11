import hashlib
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from builder import testing


class JacocoCacheTests(unittest.TestCase):
    def test_cache_root_and_dependency_directory_symlinks_cannot_publish_outside(self):
        for root_alias in (False, True):
            with self.subTest(root_alias=root_alias), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                outside = root / 'outside'
                outside.mkdir()
                cache = root / 'cache'
                if root_alias:
                    cache.symlink_to(outside, target_is_directory=True)
                else:
                    cache.mkdir()
                    (cache / 'deps').symlink_to(outside, target_is_directory=True)
                config = SimpleNamespace(cache_dir=str(cache) + '/')
                with patch.object(testing.requests, 'get') as request:
                    with self.assertRaisesRegex(RuntimeError, 'cache directories must not be symlinks'):
                        testing._find_jacoco(config, 'agent', 'org.jacoco.agent', 'runtime')
                    request.assert_not_called()
                self.assertEqual(list(outside.iterdir()), [])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='termux-builder-jacoco-cache-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = SimpleNamespace(cache_dir=str(self.root))
        self.destination = self.root / 'deps/org.jacoco.agent-0.8.12-runtime.jar'
        self.payload = b'verified fixture bytes'
        pins = patch.object(testing, 'JACOCO_SHA256', {'agent': hashlib.sha256(self.payload).hexdigest()})
        pins.start()
        self.addCleanup(pins.stop)

    def find(self):
        return testing._find_jacoco(self.config, 'agent', 'org.jacoco.agent', 'runtime')

    def test_corrupt_cache_is_rejected_without_network_or_modification(self):
        self.destination.parent.mkdir()
        self.destination.write_bytes(b'corrupted cache')
        with patch.object(testing.requests, 'get') as request:
            with self.assertRaisesRegex(RuntimeError, 'checksum'):
                self.find()
            request.assert_not_called()
        self.assertEqual(self.destination.read_bytes(), b'corrupted cache')

    def test_symlinks_directories_and_fifos_are_rejected_offline(self):
        for kind in ('symlink', 'directory', 'fifo'):
            with self.subTest(kind=kind):
                self.destination.parent.mkdir(exist_ok=True)
                target = self.root / 'target'
                target.write_bytes(self.payload)
                if kind == 'symlink':
                    self.destination.symlink_to(target)
                elif kind == 'directory':
                    self.destination.mkdir()
                else:
                    os.mkfifo(self.destination)
                try:
                    with patch.object(testing.requests, 'get') as request:
                        with self.assertRaises(RuntimeError):
                            self.find()
                        request.assert_not_called()
                    self.assertEqual(target.read_bytes(), self.payload)
                finally:
                    if kind == 'directory':
                        self.destination.rmdir()
                    else:
                        self.destination.unlink()

    def test_download_is_verified_published_and_reused_offline(self):
        response = Mock(status_code=200)
        response.iter_content.return_value = [self.payload[:5], self.payload[5:]]
        with patch.object(testing.requests, 'get', return_value=response) as request:
            self.assertEqual(self.find(), str(self.destination))
            self.assertFalse(request.call_args.kwargs['allow_redirects'])
            self.assertTrue(request.call_args.kwargs['stream'])
        response.close.assert_called_once()
        self.assertEqual(self.destination.read_bytes(), self.payload)
        with patch.object(testing.requests, 'get') as request:
            self.assertEqual(self.find(), str(self.destination))
            request.assert_not_called()
        self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])

    def test_failed_downloads_never_publish_partial_cache(self):
        for failure in ('checksum', 'redirect', 'interrupt', 'oversize'):
            with self.subTest(failure=failure):
                response = Mock(status_code=302 if failure == 'redirect' else 200)
                response.iter_content.return_value = [b'wrong bytes'] if failure == 'checksum' else [self.payload]
                if failure == 'interrupt':
                    def interrupted(_size):
                        yield self.payload[:3]
                        raise OSError('interrupted fixture')
                    response.iter_content.side_effect = interrupted
                with patch.object(testing.requests, 'get', return_value=response), \
                    patch.object(testing, 'JACOCO_MAX_BYTES', 4 if failure == 'oversize' else 1024, create=True):
                    with self.assertRaises(RuntimeError):
                        self.find()
                response.close.assert_called_once()
                self.assertFalse(self.destination.exists())
                self.assertEqual(list(self.destination.parent.iterdir()), [])

    def test_network_errors_are_sanitized_and_cancelled_downloads_clean_staging(self):
        with patch.object(testing.requests, 'get', side_effect=testing.requests.ConnectionError('secret proxy credentials')):
            with self.assertRaisesRegex(RuntimeError, 'network is required') as caught:
                self.find()
            self.assertNotIn('secret proxy', str(caught.exception))
            self.assertTrue(caught.exception.__suppress_context__)
        response = Mock(status_code=200)
        response.iter_content.side_effect = KeyboardInterrupt
        with patch.object(testing.requests, 'get', return_value=response):
            with self.assertRaises(KeyboardInterrupt):
                self.find()
        response.close.assert_called_once()
        self.assertEqual(list(self.destination.parent.iterdir()), [])

    def test_oversize_cache_and_invalid_artifact_selector_are_rejected(self):
        self.destination.parent.mkdir()
        self.destination.write_bytes(self.payload)
        with patch.object(testing, 'JACOCO_MAX_BYTES', 4), patch.object(testing.requests, 'get') as request:
            with self.assertRaisesRegex(RuntimeError, 'size limit'):
                self.find()
            request.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'Unsupported JaCoCo artifact'):
            testing._find_jacoco(self.config, 'agent', '../outside', 'runtime')

    def test_cache_permission_failure_is_explicit_and_does_not_start_network(self):
        with patch.object(testing.tempfile, 'mkstemp', side_effect=PermissionError('private fixture detail')), \
            patch.object(testing.requests, 'get') as request:
            with self.assertRaisesRegex(RuntimeError, 'Cannot prepare JaCoCo cache directory') as caught:
                self.find()
            request.assert_not_called()
            self.assertNotIn('private fixture', str(caught.exception))
            self.assertFalse(self.destination.exists())


if __name__ == '__main__':
    unittest.main()
