import os
import xml.etree.ElementTree as ET
from builder.utils import log


def merge(config):
    lib_manifests = []
    if not os.path.isdir(config.libs_dir):
        return

    for root_dir, _, files in os.walk(config.libs_dir):
        for f in files:
            if f == "AndroidManifest.xml":
                lib_manifests.append(os.path.join(root_dir, f))

    if not lib_manifests:
        return

    log.info("Merging %d library manifests", len(lib_manifests))
    main_tree = ET.parse(config.manifest_path)
    main_root = main_tree.getroot()

    ns = "http://schemas.android.com/apk/res/android"
    ET.register_namespace("android", ns)

    existing_perms = set()
    for perm in main_root.findall("uses-permission"):
        name = perm.attrib.get(f"{{{ns}}}name", "")
        if name:
            existing_perms.add(name)

    for manifest_path in lib_manifests:
        try:
            lib_tree = ET.parse(manifest_path)
            lib_root = lib_tree.getroot()

            for perm in lib_root.findall("uses-permission"):
                name = perm.attrib.get(f"{{{ns}}}name", "")
                if name and name not in existing_perms:
                    main_root.append(perm)
                    existing_perms.add(name)
                    log.debug("Merged permission: %s", name)

        except ET.ParseError:
            log.warning("Failed to parse: %s", manifest_path)

    merged_path = os.path.join(config.build_dir, "AndroidManifest.xml")
    main_tree.write(merged_path, xml_declaration=True, encoding="utf-8")
    config.manifest_path = merged_path
