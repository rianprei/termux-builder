import os
import tempfile
import unittest
from types import SimpleNamespace
from xml.etree import ElementTree as ET

from builder.manifest import merge


ANDROID = "http://schemas.android.com/apk/res/android"


class ManifestMergeTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.libs_dir = os.path.join(self.tempdir.name, ".libs")
        self.build_dir = os.path.join(self.tempdir.name, ".build")
        os.makedirs(self.build_dir)
        os.makedirs(os.path.join(self.libs_dir, "z-library"))
        self.main_path = os.path.join(self.tempdir.name, "AndroidManifest.xml")
        self.config = SimpleNamespace(
            libs_dir=self.libs_dir,
            build_dir=self.build_dir,
            manifest_path=self.main_path,
            manifest_placeholders={},
            package_name="com.example.app",
        )

    def write_manifest(self, path, xml):
        with open(path, "w", encoding="utf-8") as manifest:
            manifest.write(xml)

    def test_same_activity_merges_nonconflicting_attributes(self):
        self.write_manifest(
            self.main_path,
            f'<manifest xmlns:android="{ANDROID}" package="com.example.app">'
            '<application><activity android:name=".MainActivity" android:exported="true" />'
            '</application></manifest>',
        )
        self.write_manifest(
            os.path.join(self.libs_dir, "z-library", "AndroidManifest.xml"),
            f'<manifest xmlns:android="{ANDROID}" package="com.example.app">'
            '<application><activity android:name=".MainActivity" android:label="Library label" />'
            '</application></manifest>',
        )

        merge(self.config)

        root = ET.parse(self.config.manifest_path).getroot()
        activity = root.find("application/activity")
        self.assertEqual(activity.attrib[f"{{{ANDROID}}}exported"], "true")
        self.assertEqual(activity.attrib[f"{{{ANDROID}}}label"], "Library label")

    def test_conflicting_attributes_report_both_sources_and_remediation(self):
        library_manifest = os.path.join(self.libs_dir, "z-library", "AndroidManifest.xml")
        self.write_manifest(
            self.main_path,
            f'<manifest xmlns:android="{ANDROID}" package="com.example.app">'
            '<application><activity android:name=".MainActivity" android:exported="true" />'
            '</application></manifest>',
        )
        self.write_manifest(
            library_manifest,
            f'<manifest xmlns:android="{ANDROID}" package="com.example.app">'
            '<application><activity android:name=".MainActivity" android:exported="false" />'
            '</application></manifest>',
        )

        with self.assertRaisesRegex(ValueError, "android:exported") as raised:
            merge(self.config)

        self.assertIn(self.main_path, str(raised.exception))
        self.assertIn(library_manifest, str(raised.exception))
        self.assertIn("tools:replace", str(raised.exception))
        self.assertEqual(self.config.manifest_path, self.main_path)

    def test_tools_replace_resolves_conflict_and_is_removed_from_output(self):
        library_manifest = os.path.join(self.libs_dir, "z-library", "AndroidManifest.xml")
        self.write_manifest(
            self.main_path,
            f'<manifest xmlns:android="{ANDROID}" xmlns:tools="http://schemas.android.com/tools" '
            'package="com.example.app"><application><activity android:name=".MainActivity" '
            'android:exported="true" tools:replace="android:exported" /></application></manifest>',
        )
        self.write_manifest(
            library_manifest,
            f'<manifest xmlns:android="{ANDROID}" package="com.example.app">'
            '<application><activity android:name=".MainActivity" android:exported="false" />'
            '</application></manifest>',
        )

        merge(self.config)

        root = ET.parse(self.config.manifest_path).getroot()
        activity = root.find("application/activity")
        self.assertEqual(activity.attrib[f"{{{ANDROID}}}exported"], "true")
        self.assertNotIn("{http://schemas.android.com/tools}replace", activity.attrib)

    def test_tools_node_remove_drops_matching_library_element(self):
        self.write_manifest(
            self.main_path,
            f'<manifest xmlns:android="{ANDROID}" xmlns:tools="http://schemas.android.com/tools" '
            'package="com.example.app"><application><activity android:name=".LegacyActivity" '
            'tools:node="remove" /></application></manifest>',
        )
        self.write_manifest(
            os.path.join(self.libs_dir, "z-library", "AndroidManifest.xml"),
            f'<manifest xmlns:android="{ANDROID}" package="com.example.app">'
            '<application><activity android:name=".LegacyActivity" android:exported="false" />'
            '</application></manifest>',
        )

        merge(self.config)
        merge(self.config)

        root = ET.parse(self.config.manifest_path).getroot()
        self.assertIsNone(root.find("application/activity"))

    def test_tools_remove_suppresses_selected_lower_priority_attribute(self):
        self.write_manifest(
            self.main_path,
            f'<manifest xmlns:android="{ANDROID}" xmlns:tools="http://schemas.android.com/tools" '
            'package="com.example.app"><application><activity android:name=".MainActivity" '
            'tools:remove="android:exported" /></application></manifest>',
        )
        self.write_manifest(
            os.path.join(self.libs_dir, "z-library", "AndroidManifest.xml"),
            f'<manifest xmlns:android="{ANDROID}" package="com.example.app">'
            '<application><activity android:name=".MainActivity" android:exported="false" />'
            '</application></manifest>',
        )

        merge(self.config)

        activity = ET.parse(self.config.manifest_path).getroot().find("application/activity")
        self.assertNotIn(f"{{{ANDROID}}}exported", activity.attrib)

    def test_tools_strict_rejects_an_unset_high_priority_attribute(self):
        self.write_manifest(
            self.main_path,
            f'<manifest xmlns:android="{ANDROID}" xmlns:tools="http://schemas.android.com/tools" '
            'package="com.example.app"><application><activity android:name=".MainActivity" '
            'tools:strict="android:label" /></application></manifest>',
        )
        self.write_manifest(
            os.path.join(self.libs_dir, "z-library", "AndroidManifest.xml"),
            f'<manifest xmlns:android="{ANDROID}" package="com.example.app">'
            '<application><activity android:name=".MainActivity" android:label="Library label" />'
            '</application></manifest>',
        )

        with self.assertRaisesRegex(ValueError, "android:label"):
            merge(self.config)

    def test_tools_node_remove_all_keeps_higher_priority_application_entries(self):
        self.write_manifest(
            self.main_path,
            f'<manifest xmlns:android="{ANDROID}" xmlns:tools="http://schemas.android.com/tools" '
            'package="com.example.app"><application>'
            '<meta-data android:name="appOwned" android:value="keep" />'
            '<meta-data tools:node="removeAll" />'
            '</application></manifest>',
        )
        self.write_manifest(
            os.path.join(self.libs_dir, "z-library", "AndroidManifest.xml"),
            f'<manifest xmlns:android="{ANDROID}" package="com.example.lib">'
            '<application><meta-data android:name="libraryOwned" android:value="remove" />'
            '</application></manifest>',
        )

        merge(self.config)

        root = ET.parse(self.config.manifest_path).getroot()
        metadata = root.findall("application/meta-data")
        self.assertEqual(len(metadata), 1)
        self.assertEqual(metadata[0].attrib[f"{{{ANDROID}}}name"], "appOwned")

    def test_library_min_sdk_above_app_min_sdk_fails_with_override_guidance(self):
        self.config.min_sdk = 21
        self.write_manifest(
            self.main_path,
            f'<manifest xmlns:android="{ANDROID}" package="com.example.app">'
            '<uses-sdk android:minSdkVersion="21" /><application /></manifest>',
        )
        self.write_manifest(
            os.path.join(self.libs_dir, "z-library", "AndroidManifest.xml"),
            f'<manifest xmlns:android="{ANDROID}" package="com.example.lib">'
            '<uses-sdk android:minSdkVersion="26" /><application /></manifest>',
        )

        with self.assertRaisesRegex(ValueError, "minSdkVersion.*26.*overrideLibrary"):
            merge(self.config)

    def test_tools_override_library_allows_explicit_min_sdk_override(self):
        self.config.min_sdk = 21
        self.write_manifest(
            self.main_path,
            f'<manifest xmlns:android="{ANDROID}" xmlns:tools="http://schemas.android.com/tools" '
            'package="com.example.app"><uses-sdk android:minSdkVersion="21" '
            'tools:overrideLibrary="com.example.lib" /><application /></manifest>',
        )
        self.write_manifest(
            os.path.join(self.libs_dir, "z-library", "AndroidManifest.xml"),
            f'<manifest xmlns:android="{ANDROID}" package="com.example.lib">'
            '<uses-sdk android:minSdkVersion="26" /><application /></manifest>',
        )

        merge(self.config)

        root = ET.parse(self.config.manifest_path).getroot()
        uses_sdk = root.find("uses-sdk")
        self.assertEqual(uses_sdk.attrib[f"{{{ANDROID}}}minSdkVersion"], "21")
        self.assertNotIn("{http://schemas.android.com/tools}overrideLibrary", uses_sdk.attrib)

    def test_tools_selector_scopes_attribute_replacement_to_library_package(self):
        self.write_manifest(
            self.main_path,
            f'<manifest xmlns:android="{ANDROID}" xmlns:tools="http://schemas.android.com/tools" '
            'package="com.example.app"><application><activity android:name="com.example.lib.MainActivity" '
            'android:exported="true" tools:replace="android:exported" '
            'tools:selector="com.example.lib" /></application></manifest>',
        )
        self.write_manifest(
            os.path.join(self.libs_dir, "z-library", "AndroidManifest.xml"),
            f'<manifest xmlns:android="{ANDROID}" package="com.example.lib">'
            '<application><activity android:name=".MainActivity" android:exported="false" />'
            '</application></manifest>',
        )

        merge(self.config)

        activity = ET.parse(self.config.manifest_path).getroot().find("application/activity")
        self.assertEqual(activity.attrib[f"{{{ANDROID}}}exported"], "true")

    def test_tools_node_replace_keeps_only_higher_priority_element(self):
        self.write_manifest(
            self.main_path,
            f'<manifest xmlns:android="{ANDROID}" xmlns:tools="http://schemas.android.com/tools" '
            'package="com.example.app"><application><activity android:name=".MainActivity" '
            'tools:node="replace"><meta-data android:name="appOwned" android:value="keep" />'
            '</activity></application></manifest>',
        )
        self.write_manifest(
            os.path.join(self.libs_dir, "z-library", "AndroidManifest.xml"),
            f'<manifest xmlns:android="{ANDROID}" package="com.example.app">'
            '<application><activity android:name=".MainActivity" android:label="discard">'
            '<meta-data android:name="libraryOwned" android:value="discard" />'
            '</activity></application></manifest>',
        )

        merge(self.config)

        activity = ET.parse(self.config.manifest_path).getroot().find("application/activity")
        self.assertEqual(
            [node.attrib[f"{{{ANDROID}}}name"] for node in activity.findall("meta-data")],
            ["appOwned"],
        )
        self.assertNotIn(f"{{{ANDROID}}}label", activity.attrib)

    def test_tools_node_strict_accepts_matching_element(self):
        self.write_manifest(
            self.main_path,
            f'<manifest xmlns:android="{ANDROID}" xmlns:tools="http://schemas.android.com/tools" '
            'package="com.example.app"><application><activity android:name=".MainActivity" '
            'android:exported="true" tools:node="strict" /></application></manifest>',
        )
        self.write_manifest(
            os.path.join(self.libs_dir, "z-library", "AndroidManifest.xml"),
            f'<manifest xmlns:android="{ANDROID}" package="com.example.app">'
            '<application><activity android:name=".MainActivity" android:exported="true" />'
            '</application></manifest>',
        )

        merge(self.config)

        activity = ET.parse(self.config.manifest_path).getroot().find("application/activity")
        self.assertEqual(activity.attrib[f"{{{ANDROID}}}exported"], "true")

    def test_tools_node_strict_rejects_different_attributes(self):
        self.write_manifest(
            self.main_path,
            f'<manifest xmlns:android="{ANDROID}" xmlns:tools="http://schemas.android.com/tools" '
            'package="com.example.app"><application><activity android:name=".MainActivity" '
            'android:exported="true" tools:node="strict" /></application></manifest>',
        )
        self.write_manifest(
            os.path.join(self.libs_dir, "z-library", "AndroidManifest.xml"),
            f'<manifest xmlns:android="{ANDROID}" package="com.example.app">'
            '<application><activity android:name=".MainActivity" android:exported="false" />'
            '</application></manifest>',
        )

        with self.assertRaisesRegex(ValueError, "tools:node=\"strict\" mismatch"):
            merge(self.config)

    def test_tools_node_merge_only_attributes_skips_library_children(self):
        self.write_manifest(
            self.main_path,
            f'<manifest xmlns:android="{ANDROID}" xmlns:tools="http://schemas.android.com/tools" '
            'package="com.example.app"><application><activity android:name=".MainActivity" '
            'tools:node="mergeOnlyAttributes"><meta-data android:name="appOwned" '
            'android:value="keep" /></activity></application></manifest>',
        )
        self.write_manifest(
            os.path.join(self.libs_dir, "z-library", "AndroidManifest.xml"),
            f'<manifest xmlns:android="{ANDROID}" package="com.example.app">'
            '<application><activity android:name=".MainActivity" android:exported="false">'
            '<meta-data android:name="libraryOwned" android:value="discard" />'
            '</activity></application></manifest>',
        )

        merge(self.config)

        activity = ET.parse(self.config.manifest_path).getroot().find("application/activity")
        self.assertEqual(activity.attrib[f"{{{ANDROID}}}exported"], "false")
        self.assertEqual(
            [node.attrib[f"{{{ANDROID}}}name"] for node in activity.findall("meta-data")],
            ["appOwned"],
        )

    def test_build_sdk_configuration_overrides_manifests(self):
        self.config.min_sdk = 23
        self.config.target_sdk = 35
        self.write_manifest(
            self.main_path,
            f'<manifest xmlns:android="{ANDROID}" package="com.example.app"><application /></manifest>',
        )
        self.write_manifest(
            os.path.join(self.libs_dir, "z-library", "AndroidManifest.xml"),
            f'<manifest xmlns:android="{ANDROID}" package="com.example.lib">'
            '<uses-sdk android:minSdkVersion="21" android:targetSdkVersion="28" />'
            '<application /></manifest>',
        )

        merge(self.config)

        uses_sdk = ET.parse(self.config.manifest_path).getroot().find("uses-sdk")
        self.assertEqual(uses_sdk.attrib[f"{{{ANDROID}}}minSdkVersion"], "23")
        self.assertEqual(uses_sdk.attrib[f"{{{ANDROID}}}targetSdkVersion"], "35")

    def test_uses_feature_required_uses_or_merge(self):
        self.write_manifest(
            self.main_path,
            f'<manifest xmlns:android="{ANDROID}" package="com.example.app">'
            '<uses-feature android:name="android.hardware.camera" android:required="false" />'
            '<application /></manifest>',
        )
        self.write_manifest(
            os.path.join(self.libs_dir, "z-library", "AndroidManifest.xml"),
            f'<manifest xmlns:android="{ANDROID}" package="com.example.lib">'
            '<uses-feature android:name="android.hardware.camera" android:required="true" />'
            '<application /></manifest>',
        )

        merge(self.config)

        feature = ET.parse(self.config.manifest_path).getroot().find("uses-feature")
        self.assertEqual(feature.attrib[f"{{{ANDROID}}}required"], "true")

    def test_direct_manifest_priority_follows_project_dependency_order(self):
        self.config.dependencies = ["com.z:z-library:1.0", "com.a:a-library:1.0"]
        self.write_manifest(
            self.main_path,
            f'<manifest xmlns:android="{ANDROID}" package="com.example.app">'
            '<application><activity android:name=".MainActivity" /></application></manifest>',
        )
        z_dir = os.path.join(
            self.libs_dir, ".termux-builder", "maven", "com", "z", "z-library-1.0"
        )
        a_dir = os.path.join(
            self.libs_dir, ".termux-builder", "maven", "com", "a", "a-library-1.0"
        )
        z_manifest = os.path.join(z_dir, "AndroidManifest.xml")
        a_manifest = os.path.join(a_dir, "AndroidManifest.xml")
        os.makedirs(os.path.dirname(z_manifest))
        os.makedirs(os.path.dirname(a_manifest))
        self.config.resolved_dependency_dirs = {z_dir, a_dir}
        with open(os.path.join(z_dir, ".termux-builder-coordinate"), "w") as marker:
            marker.write("com.z:z-library:1.0")
        with open(os.path.join(a_dir, ".termux-builder-coordinate"), "w") as marker:
            marker.write("com.a:a-library:1.0")
        self.write_manifest(
            z_manifest,
            f'<manifest xmlns:android="{ANDROID}" package="com.z">'
            '<application><activity android:name="com.example.app.MainActivity" android:label="z" />'
            '</application></manifest>',
        )
        self.write_manifest(
            a_manifest,
            f'<manifest xmlns:android="{ANDROID}" package="com.a">'
            '<application><activity android:name="com.example.app.MainActivity" android:label="a" />'
            '</application></manifest>',
        )

        with self.assertRaisesRegex(ValueError, "attribute android:label") as raised:
            merge(self.config)

        message = str(raised.exception)
        self.assertLess(message.index(z_manifest), message.index(a_manifest))

    def test_stale_maven_manifest_is_excluded_when_no_dependencies_are_resolved(self):
        self.config.dependencies = []
        self.config.resolved_dependency_dirs = set()
        self.write_manifest(
            self.main_path,
            f'<manifest xmlns:android="{ANDROID}" package="com.example.app"><application/></manifest>',
        )
        stale_dir = os.path.join(
            self.libs_dir, ".termux-builder", "maven", "com", "example", "stale-1.0-aar"
        )
        os.makedirs(stale_dir)
        with open(os.path.join(stale_dir, ".termux-builder-coordinate"), "w") as marker:
            marker.write("com.example:stale:1.0")
        stale_manifest = os.path.join(stale_dir, "AndroidManifest.xml")
        self.write_manifest(
            stale_manifest,
            f'<manifest xmlns:android="{ANDROID}" package="com.example.stale">'
            '<uses-permission android:name="android.permission.CAMERA" /></manifest>',
        )

        merge(self.config)

        root = ET.parse(self.config.manifest_path).getroot()
        self.assertIsNone(root.find("uses-permission"))

    def test_unmarked_interrupted_maven_extraction_is_not_merged(self):
        self.config.dependencies = []
        self.config.resolved_dependency_dirs = set()
        self.write_manifest(
            self.main_path,
            f'<manifest xmlns:android="{ANDROID}" package="com.example.app"><application/></manifest>',
        )
        staging_dir = os.path.join(
            self.libs_dir, ".termux-builder", "maven", "com", "example", ".partial.stage"
        )
        os.makedirs(staging_dir)
        self.write_manifest(
            os.path.join(staging_dir, "AndroidManifest.xml"),
            f'<manifest xmlns:android="{ANDROID}" package="com.example.partial">'
            '<uses-permission android:name="android.permission.CAMERA" /></manifest>',
        )

        merge(self.config)

        root = ET.parse(self.config.manifest_path).getroot()
        self.assertIsNone(root.find("uses-permission"))

    def test_merge_keeps_resolved_maven_and_local_manifests_only(self):
        self.config.dependencies = ["com.example:active:1.0"]
        active_dir = os.path.join(
            self.libs_dir, ".termux-builder", "maven", "com", "example", "active-1.0-aar"
        )
        stale_dir = os.path.join(
            self.libs_dir, ".termux-builder", "maven", "com", "example", "stale-1.0-aar"
        )
        local_dir = os.path.join(self.libs_dir, "local")
        for directory in (active_dir, stale_dir, local_dir):
            os.makedirs(directory)
        for directory, coordinate in (
            (active_dir, "com.example:active:1.0"),
            (stale_dir, "com.example:stale:1.0"),
        ):
            with open(os.path.join(directory, ".termux-builder-coordinate"), "w") as marker:
                marker.write(coordinate)
        self.config.resolved_dependency_dirs = {active_dir}
        self.write_manifest(
            self.main_path,
            f'<manifest xmlns:android="{ANDROID}" package="com.example.app"><application/></manifest>',
        )
        for directory, permission in (
            (active_dir, "android.permission.CAMERA"),
            (stale_dir, "android.permission.ACCESS_FINE_LOCATION"),
            (local_dir, "android.permission.INTERNET"),
        ):
            self.write_manifest(
                os.path.join(directory, "AndroidManifest.xml"),
                f'<manifest xmlns:android="{ANDROID}" package="com.example.library">'
                f'<uses-permission android:name="{permission}" /></manifest>',
            )

        merge(self.config)

        permissions = {
            element.attrib[f"{{{ANDROID}}}name"]
            for element in ET.parse(self.config.manifest_path).getroot().findall("uses-permission")
        }
        self.assertEqual(permissions, {
            "android.permission.CAMERA", "android.permission.INTERNET"
        })

    def test_relative_component_names_use_each_manifest_package_for_matching(self):
        self.write_manifest(
            self.main_path,
            f'<manifest xmlns:android="{ANDROID}" package="com.example.app">'
            '<application><activity android:name=".MainActivity" /></application></manifest>',
        )
        self.write_manifest(
            os.path.join(self.libs_dir, "z-library", "AndroidManifest.xml"),
            f'<manifest xmlns:android="{ANDROID}" package="com.example.lib">'
            '<application><activity android:name=".MainActivity" android:label="Library" />'
            '</application></manifest>',
        )

        merge(self.config)

        activities = ET.parse(self.config.manifest_path).getroot().findall("application/activity")
        self.assertEqual(len(activities), 2)
        self.assertNotIn(f"{{{ANDROID}}}label", activities[0].attrib)
        self.assertEqual(activities[1].attrib[f"{{{ANDROID}}}label"], "Library")
        self.assertEqual(activities[1].attrib[f"{{{ANDROID}}}name"], "com.example.lib.MainActivity")

    def test_application_class_name_merges_as_package_relative_name(self):
        self.write_manifest(
            self.main_path,
            f'<manifest xmlns:android="{ANDROID}" package="com.example.app">'
            '<application android:name=".App" /></manifest>',
        )
        self.write_manifest(
            os.path.join(self.libs_dir, "z-library", "AndroidManifest.xml"),
            f'<manifest xmlns:android="{ANDROID}" package="com.example.lib">'
            '<application android:name="com.example.app.App" /></manifest>',
        )

        merge(self.config)

        application = ET.parse(self.config.manifest_path).getroot().find("application")
        self.assertEqual(application.attrib[f"{{{ANDROID}}}name"], "com.example.app.App")

    def test_placeholders_expand_before_manifest_matching(self):
        self.config.manifest_placeholders = {"channel": "stable"}
        self.write_manifest(
            self.main_path,
            f'<manifest xmlns:android="{ANDROID}" package="com.example.app">'
            '<application><activity android:name="${applicationId}.MainActivity" />'
            '</application></manifest>',
        )
        self.write_manifest(
            os.path.join(self.libs_dir, "z-library", "AndroidManifest.xml"),
            f'<manifest xmlns:android="{ANDROID}" package="com.example.lib">'
            '<application><activity android:name="com.example.app.MainActivity" '
            'android:label="${channel}" /></application></manifest>',
        )

        merge(self.config)

        root = ET.parse(self.config.manifest_path).getroot()
        activity = root.find("application/activity")
        self.assertEqual(
            activity.attrib[f"{{{ANDROID}}}name"],
            "com.example.app.MainActivity",
        )
        self.assertEqual(activity.attrib[f"{{{ANDROID}}}label"], "stable")

    def test_unknown_placeholder_fails_with_source_path(self):
        self.write_manifest(
            self.main_path,
            f'<manifest xmlns:android="{ANDROID}" package="com.example.app">'
            '<application android:label="${missingValue}" /></manifest>',
        )

        with self.assertRaisesRegex(ValueError, "missingValue") as raised:
            merge(self.config)

        self.assertIn(self.main_path, str(raised.exception))
        self.assertEqual(self.config.manifest_path, self.main_path)

    def test_placeholders_are_expanded_when_library_directory_is_missing(self):
        os.rmdir(os.path.join(self.libs_dir, "z-library"))
        os.rmdir(self.libs_dir)
        self.write_manifest(
            self.main_path,
            f'<manifest xmlns:android="{ANDROID}" package="com.example.app">'
            '<application android:label="${applicationId}" /></manifest>',
        )

        merge(self.config)

        root = ET.parse(self.config.manifest_path).getroot()
        self.assertEqual(
            root.find("application").attrib[f"{{{ANDROID}}}label"],
            "com.example.app",
        )

    def test_library_manifest_symlink_is_rejected(self):
        outside_manifest = os.path.join(self.tempdir.name, "outside.xml")
        self.write_manifest(
            outside_manifest,
            f'<manifest xmlns:android="{ANDROID}" package="com.example.lib" />',
        )
        library_manifest = os.path.join(self.libs_dir, "z-library", "AndroidManifest.xml")
        os.symlink(outside_manifest, library_manifest)
        self.write_manifest(self.main_path, '<manifest package="com.example.app" />')

        with self.assertRaisesRegex(ValueError, "must not be a symlink"):
            merge(self.config)

    def test_non_manifest_xml_root_is_rejected(self):
        self.write_manifest(self.main_path, "<not-a-manifest />")

        with self.assertRaisesRegex(ValueError, "root element must be <manifest>"):
            merge(self.config)

    def test_unsupported_tools_attribute_fails_instead_of_being_ignored(self):
        self.write_manifest(
            self.main_path,
            '<manifest xmlns:tools="http://schemas.android.com/tools" '
            'package="com.example.app"><application tools:merge="combine" /></manifest>',
        )

        with self.assertRaisesRegex(ValueError, "Unsupported tools attribute tools:merge"):
            merge(self.config)

    def test_build_output_never_overwrites_source_manifest(self):
        self.config.build_dir = self.tempdir.name
        original = '<manifest package="com.example.app"><application /></manifest>\n'
        self.write_manifest(self.main_path, original)

        merge(self.config)

        with open(self.main_path, encoding="utf-8") as manifest:
            self.assertEqual(manifest.read(), original)
        self.assertNotEqual(os.path.realpath(self.config.manifest_path), os.path.realpath(self.main_path))


if __name__ == "__main__":
    unittest.main()
