import os
import xml.etree.ElementTree as ET
from builder.utils import log

_NS = "http://schemas.android.com/apk/res/android"
_NS_PREFIX = f"{{{_NS}}}"

# Whitelist merger — only these tags are merged from library manifests.
# Tags outside this list (e.g. <queries>, <uses-sdk>) are NOT merged.
# Top-level elements merged by name attribute
_NAMED_TOP = ("uses-permission", "uses-feature", "permission", "permission-group")
# <application> children merged by android:name
_NAMED_APP = ("activity", "service", "receiver", "provider")
# <application> children merged by android:name (no dedup check needed)
_UNNAMED_APP = ("meta-data",)


def merge(config):
    if not os.path.isdir(config.libs_dir):
        return

    lib_manifests = []
    for root_dir, _, files in os.walk(config.libs_dir):
        for f in files:
            if f == "AndroidManifest.xml":
                lib_manifests.append(os.path.join(root_dir, f))

    if not lib_manifests:
        return

    log.info("Merging %d library manifests", len(lib_manifests))
    ET.register_namespace("android", _NS)

    main_tree = ET.parse(config.manifest_path)
    main_root = main_tree.getroot()
    main_app = main_root.find("application")

    # Build dedup sets
    existing_top = {}  # tag -> set of names
    for tag in _NAMED_TOP:
        existing_top[tag] = {
            e.attrib.get(f"{_NS_PREFIX}name", "")
            for e in main_root.findall(tag)
        }

    existing_app = {}  # tag -> set of names
    if main_app is not None:
        for tag in _NAMED_APP:
            existing_app[tag] = {
                e.attrib.get(f"{_NS_PREFIX}name", "")
                for e in main_app.findall(tag)
            }

    for manifest_path in lib_manifests:
        try:
            lib_root = ET.parse(manifest_path).getroot()
            lib_app = lib_root.find("application")

            # Merge top-level named elements
            for tag in _NAMED_TOP:
                for elem in lib_root.findall(tag):
                    name = elem.attrib.get(f"{_NS_PREFIX}name", "")
                    if name not in existing_top[tag]:
                        main_root.append(elem)
                        existing_top[tag].add(name)
                        log.debug("Merged <%s>: %s", tag, name)

            # Merge <application> children
            if lib_app is not None and main_app is not None:
                for tag in _NAMED_APP:
                    for elem in lib_app.findall(tag):
                        name = elem.attrib.get(f"{_NS_PREFIX}name", "")
                        if name not in existing_app.get(tag, set()):
                            main_app.append(elem)
                            existing_app.setdefault(tag, set()).add(name)
                            log.debug("Merged <application/%s>: %s", tag, name)

                for tag in _UNNAMED_APP:
                    for elem in lib_app.findall(tag):
                        if main_app is not None:
                            main_app.append(elem)

        except ET.ParseError:
            log.warning("Failed to parse: %s", manifest_path)

    merged_path = os.path.join(config.build_dir, "AndroidManifest.xml")
    main_tree.write(merged_path, xml_declaration=True, encoding="utf-8")
    config.manifest_path = merged_path
