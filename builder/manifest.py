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

    existing_features = set()
    for feat in main_root.findall("uses-feature"):
        name = feat.attrib.get(f"{{{ns}}}name", "")
        if name:
            existing_features.add(name)

    main_app = main_root.find("application")

    existing_components = set()
    if main_app is not None:
        for tag in ("activity", "service", "receiver", "provider"):
            for comp in main_app.findall(tag):
                name = comp.attrib.get(f"{{{ns}}}name", "")
                if name:
                    existing_components.add(name)

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

            for feat in lib_root.findall("uses-feature"):
                name = feat.attrib.get(f"{{{ns}}}name", "")
                if name and name not in existing_features:
                    main_root.append(feat)
                    existing_features.add(name)
                    log.debug("Merged feature: %s", name)

            lib_app = lib_root.find("application")
            if lib_app is not None and main_app is not None:
                for tag in ("activity", "service", "receiver", "provider", "meta-data"):
                    for comp in lib_app.findall(tag):
                        name = comp.attrib.get(f"{{{ns}}}name", "")
                        if name and name not in existing_components:
                            main_app.append(comp)
                            existing_components.add(name)
                            log.debug("Merged %s: %s", tag, name)

        except ET.ParseError:
            log.warning("Failed to parse: %s", manifest_path)

    merged_path = os.path.join(config.build_dir, "AndroidManifest.xml")
    main_tree.write(merged_path, xml_declaration=True, encoding="utf-8")
    config.manifest_path = merged_path
