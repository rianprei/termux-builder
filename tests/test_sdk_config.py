import tempfile
import unittest
from pathlib import Path

import yaml

from builder.config import Config


class SdkConfigTests(unittest.TestCase):
    def project(self, root, sdk_path=None):
        project = root / 'project'
        project.mkdir()
        (project / 'AndroidManifest.xml').write_text('<manifest package="fixture.sdk"/>')
        raw = {'name': 'sdk-fixture', 'android': {'target-sdk': 36}}
        if sdk_path is not None:
            raw['android']['sdk-path'] = sdk_path
        (project / 'project.yml').write_text(yaml.safe_dump(raw))
        return project, raw

    def test_relative_sdk_is_resolved_against_project(self):
        with tempfile.TemporaryDirectory() as temp:
            project, _ = self.project(Path(temp), 'sdk')
            jar = project / 'sdk/platforms/android-36/android.jar'
            jar.parent.mkdir(parents=True)
            jar.write_bytes(b'platform fixture')
            config = Config(project)
            self.assertEqual(config.sdk_dir, str(project / 'sdk'))
            self.assertEqual(config.android_jar, str(jar))

    def test_absolute_sdk_path_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sdk = root / 'external-sdk'
            project, _ = self.project(root, str(sdk))
            self.assertEqual(Config(project).sdk_dir, str(sdk))

    def test_top_level_sdk_path_is_rejected_with_migration_action(self):
        for nested in (False, True):
            with self.subTest(nested=nested), tempfile.TemporaryDirectory() as temp:
                project, raw = self.project(Path(temp), 'sdk' if nested else None)
                raw['sdk-path'] = 'misplaced-sdk'
                (project / 'project.yml').write_text(yaml.safe_dump(raw))
                with self.assertRaisesRegex(ValueError, 'android.sdk-path'):
                    Config(project)

    def test_invalid_sdk_path_is_rejected_without_echoing_values(self):
        for value in ('', '   ', 'private-token\x00', 42, True, [], {}):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temp:
                project, _ = self.project(Path(temp), value)
                with self.assertRaisesRegex(ValueError, 'android.sdk-path') as caught:
                    Config(project)
                self.assertNotIn('private-token', str(caught.exception))
