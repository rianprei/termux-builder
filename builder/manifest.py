import os
import re
import xml.etree.ElementTree as ET

from .utils import log


_ANDROID_NS = "http://schemas.android.com/apk/res/android"
_TOOLS_NS = "http://schemas.android.com/tools"
_ANDROID = f"{{{_ANDROID_NS}}}"
_TOOLS = f"{{{_TOOLS_NS}}}"
_TOOLS_ATTRIBUTES = {"ignore", "node", "overrideLibrary", "remove", "replace", "selector", "strict", "targetApi"}
_NODE_MARKERS = {"merge", "mergeOnlyAttributes", "remove", "removeAll", "replace", "strict"}
_MATCH_BY_NAME = {
    "action",
    "activity",
    "activity-alias",
    "category",
    "instrumentation",
    "meta-data",
    "package",
    "permission",
    "permission-group",
    "permission-tree",
    "provider",
    "receiver",
    "service",
    "supports-gl-texture",
    "uses-library",
    "uses-permission",
    "uses-permission-sdk-23",
    "uses-permission-sdk-m",
}
_COMPONENT_TAGS = {"activity", "activity-alias", "instrumentation", "provider", "receiver", "service"}
_CLASS_NAME_TAGS = _COMPONENT_TAGS | {"application"}
_SINGLETON_TAGS = {
    "application",
    "compatible-screens",
    "queries",
    "supports-screens",
    "uses-configuration",
    "uses-sdk",
}


def _qualified_class_name(tag, value, source_package):
    if tag in _CLASS_NAME_TAGS and value and value.startswith(".") and source_package:
        return source_package + value
    return value


def _match_key(element, source_package=None):
    tag = element.tag
    if tag == "intent-filter":
        return None
    if tag in _SINGLETON_TAGS or tag in {"data", "grant-uri-permission", "path-permission"}:
        return tag, None
    if tag == "uses-feature":
        value = element.attrib.get(_ANDROID + "name")
        if value is None:
            value = element.attrib.get(_ANDROID + "glEsVersion")
    elif tag in _MATCH_BY_NAME:
        value = element.attrib.get(_ANDROID + "name")
    else:
        return None
    value = _qualified_class_name(tag, value, source_package)
    return (tag, value) if value is not None else None


def _remember_tree(element, source_path, source_package, source_files, source_packages, attribute_sources):
    source_files[id(element)] = source_path
    source_packages[id(element)] = source_package
    for name in element.attrib:
        attribute_sources[(id(element), name)] = source_path
    for child in element:
        _remember_tree(child, source_path, source_package, source_files, source_packages, attribute_sources)


def _marker_applies(element, source_package):
    selector = element.attrib.get(_TOOLS + "selector")
    return not selector or selector == source_package


def _validate_tools_attributes(element, source_path):
    for node in element.iter():
        for name, value in node.attrib.items():
            if not name.startswith(_TOOLS):
                continue
            marker = name.removeprefix(_TOOLS)
            if marker not in _TOOLS_ATTRIBUTES:
                raise ValueError(f"Unsupported tools attribute tools:{marker} in {source_path}")
            if marker == "node" and value not in _NODE_MARKERS:
                raise ValueError(f"Unsupported tools:node={value!r} in {source_path}")
            if marker == "overrideLibrary" and node.tag != "uses-sdk":
                raise ValueError(f"tools:overrideLibrary is only supported on <uses-sdk> in {source_path}")


def _marker_attributes(element, marker, source_package):
    if not _marker_applies(element, source_package):
        return set()
    values = element.attrib.get(_TOOLS + marker, "")
    attributes = set()
    for value in values.split(","):
        value = value.strip()
        if value.startswith("android:"):
            attributes.add(_ANDROID + value.removeprefix("android:"))
        elif value:
            attributes.add(value)
    return attributes


def _attribute_label(name):
    if name.startswith(_ANDROID):
        return "android:" + name.removeprefix(_ANDROID)
    return name


def _raise_attribute_conflict(high, name, high_value, low_value, high_source, source_path):
    high_text = "<absent>" if high_value is None else repr(high_value)
    low_text = "<absent>" if low_value is None else repr(low_value)
    raise ValueError(
        f"Manifest merge conflict for <{high.tag}> attribute {_attribute_label(name)}: "
        f"{high_text} from {high_source} conflicts with {low_text} from {source_path}; "
        "add a tools:replace marker to the higher-priority manifest."
    )


def _strip_tools_markers(element):
    for parent in element.iter():
        for child in list(parent):
            if child.attrib.get(_TOOLS + "node") in {"remove", "removeAll"}:
                parent.remove(child)
    for node in element.iter():
        for name in list(node.attrib):
            if name.startswith(_TOOLS):
                del node.attrib[name]


def _element_signature(element):
    attributes = tuple(
        sorted((name, value) for name, value in element.attrib.items() if not name.startswith(_TOOLS))
    )
    children = tuple(_element_signature(child) for child in element)
    return element.tag, attributes, children


def _replace_placeholders(element, config, source_path):
    values = dict(getattr(config, "manifest_placeholders", {}) or {})
    application_id = getattr(config, "package_name", None) or element.attrib.get("package")
    if application_id:
        values["applicationId"] = application_id

    def replace(match):
        key = match.group(1)
        if key not in values:
            raise ValueError(f"Unknown manifest placeholder ${{{key}}} in {source_path}")
        value = values[key]
        return str(value).lower() if isinstance(value, bool) else str(value)

    for node in element.iter():
        for name, value in list(node.attrib.items()):
            expanded = re.sub(r"\$\{([^}]+)\}", replace, value)
            if "${" in expanded:
                raise ValueError(f"Malformed manifest placeholder in {source_path}: {expanded}")
            node.attrib[name] = expanded


def _apply_sdk_configuration(root, config):
    sdk_values = {}
    if hasattr(config, "min_sdk"):
        sdk_values[_ANDROID + "minSdkVersion"] = str(config.min_sdk)
    if hasattr(config, "target_sdk"):
        sdk_values[_ANDROID + "targetSdkVersion"] = str(config.target_sdk)
    if not sdk_values:
        return

    uses_sdk = root.find("uses-sdk")
    if uses_sdk is None:
        uses_sdk = ET.Element("uses-sdk")
        application_index = next(
            (index for index, child in enumerate(root) if child.tag == "application"),
            len(root),
        )
        root.insert(application_index, uses_sdk)
    uses_sdk.attrib.update(sdk_values)


def _validate_min_sdk(high, low, source_path, source_package):
    app_min_sdk = high.attrib.get(_ANDROID + "minSdkVersion")
    library_min_sdk = low.attrib.get(_ANDROID + "minSdkVersion")
    if app_min_sdk is None or library_min_sdk is None:
        return

    try:
        app_version = int(app_min_sdk)
        library_version = int(library_min_sdk)
    except ValueError:
        if app_min_sdk != library_min_sdk:
            raise ValueError(
                f"Cannot validate library minSdkVersion {library_min_sdk!r} from {source_path} "
                f"against app minSdkVersion {app_min_sdk!r}; use numeric SDK versions or the "
                "official Android Gradle Plugin manifest merger."
            )
        return

    if library_version <= app_version:
        return
    overrides = {
        value.strip()
        for value in high.attrib.get(_TOOLS + "overrideLibrary", "").split(",")
        if value.strip()
    }
    if source_package not in overrides:
        raise ValueError(
            f"Library {source_package or source_path} requires minSdkVersion "
            f"{library_min_sdk}, above app minSdkVersion {app_min_sdk}; add "
            f"tools:overrideLibrary=\"{source_package or 'library.package'}\" only if the app "
            "can support it."
        )


def _merge_element(
    high, low, source_path, source_package, source_files, source_packages, source_priorities,
    attribute_sources,
):
    high_source = source_files[id(high)]
    high_is_manifest = high.tag == "manifest"
    high_is_uses_sdk = high.tag == "uses-sdk"
    node_marker = high.attrib.get(_TOOLS + "node", "merge")
    if not _marker_applies(high, source_package):
        node_marker = "merge"
    if node_marker not in _NODE_MARKERS:
        raise ValueError(f"Unsupported tools:node={node_marker!r} in {high_source}")
    if node_marker in {"replace", "remove", "removeAll"}:
        return
    if node_marker == "strict":
        if _element_signature(high) != _element_signature(low):
            raise ValueError(
                f"tools:node=\"strict\" mismatch for <{high.tag}> between "
                f"{high_source} and {source_path}."
            )
        return
    if high_is_uses_sdk:
        _validate_min_sdk(high, low, source_path, source_package)
    replace_attributes = _marker_attributes(high, "replace", source_package)
    remove_attributes = _marker_attributes(high, "remove", source_package)
    strict_attributes = _marker_attributes(high, "strict", source_package)

    if not high_is_manifest:
        for name in strict_attributes:
            if name in replace_attributes or name in remove_attributes:
                continue
            if high.attrib.get(name) != low.attrib.get(name):
                _raise_attribute_conflict(
                    high,
                    name,
                    high.attrib.get(name),
                    low.attrib.get(name),
                    attribute_sources.get((id(high), name), high_source),
                    source_path,
                )

        for name, value in low.attrib.items():
            if name.startswith(_TOOLS):
                continue
            if name in remove_attributes:
                continue
            if (
                high.tag in {"uses-feature", "uses-library"}
                and name == _ANDROID + "required"
                and name in high.attrib
                and name not in replace_attributes
                and high.attrib[name] != value
            ):
                if high.attrib[name] in {"true", "false"} and value in {"true", "false"}:
                    high.attrib[name] = "true" if "true" in {high.attrib[name], value} else "false"
                    attribute_sources[(id(high), name)] = source_path
                    continue
            if name in high.attrib:
                if high.attrib[name] != value and not high_is_uses_sdk:
                    if (
                        high.tag in _CLASS_NAME_TAGS
                        and name == _ANDROID + "name"
                        and _qualified_class_name(
                            high.tag, high.attrib[name], source_packages.get(id(high))
                        )
                        == _qualified_class_name(high.tag, value, source_package)
                    ):
                        continue
                    if name in replace_attributes:
                        continue
                    previous_source = attribute_sources[(id(high), name)]
                    _raise_attribute_conflict(
                        high, name, high.attrib[name], value, previous_source, source_path
                    )
            else:
                high.attrib[name] = value
                attribute_sources[(id(high), name)] = source_path

        for name in remove_attributes:
            high.attrib.pop(name, None)
            attribute_sources.pop((id(high), name), None)

    if node_marker != "mergeOnlyAttributes":
        _merge_children(
            high,
            low,
            source_path,
            source_package,
            source_files,
            source_packages,
            source_priorities,
            attribute_sources,
        )


def _merge_children(
    high_parent, low_parent, source_path, source_package, source_files, source_packages,
    source_priorities, attribute_sources,
):
    for low in low_parent:
        remove_all = next(
            (
                candidate
                for candidate in high_parent
                if candidate.tag == low.tag
                and candidate.attrib.get(_TOOLS + "node") == "removeAll"
                and _marker_applies(candidate, source_package)
            ),
            None,
        )
        if remove_all is not None:
            marker_source = source_files[id(remove_all)]
            marker_priority = source_priorities[marker_source]
            for candidate in list(high_parent):
                candidate_source = source_files[id(candidate)]
                if (
                    candidate.tag == low.tag
                    and candidate is not remove_all
                    and source_priorities[candidate_source] > marker_priority
                ):
                    high_parent.remove(candidate)
            continue

        key = _match_key(low, source_package)
        high = None
        if key is not None:
            high = next(
                (
                    candidate
                    for candidate in high_parent
                    if _match_key(candidate, source_packages.get(id(candidate))) == key
                ),
                None,
            )
        if high is None:
            high_parent.append(low)
            _remember_tree(
                low, source_path, source_package, source_files, source_packages, attribute_sources
            )
        else:
            marker = high.attrib.get(_TOOLS + "node", "merge")
            if not _marker_applies(high, source_package):
                marker = "merge"
            if marker in {"remove", "replace"}:
                continue
            _merge_element(
                high,
                low,
                source_path,
                source_package,
                source_files,
                source_packages,
                source_priorities,
                attribute_sources,
            )


def _ordered_manifest_paths(config, manifest_paths):
    remaining = set(manifest_paths)
    ordered = []
    for coordinate in getattr(config, "dependencies", []) or []:
        if not isinstance(coordinate, str):
            continue
        parts = coordinate.split(":")
        if len(parts) != 3:
            continue
        directory = f"{parts[1]}-{parts[2]}"
        matches = sorted(
            path
            for path in remaining
            if os.path.relpath(path, config.libs_dir).split(os.sep, 1)[0] == directory
        )
        ordered.extend(matches)
        remaining.difference_update(matches)
    ordered.extend(sorted(remaining))
    return ordered


def merge(config):
    source_manifest_path = getattr(config, "manifest_source_path", None)
    if not source_manifest_path:
        source_manifest_path = config.manifest_path
        config.manifest_source_path = source_manifest_path

    lib_manifests = []
    if os.path.isdir(config.libs_dir):
        for root_dir, directories, files in os.walk(config.libs_dir):
            directories.sort()
            if "AndroidManifest.xml" in files:
                manifest_path = os.path.join(root_dir, "AndroidManifest.xml")
                if os.path.islink(manifest_path):
                    raise ValueError(f"Library manifest must not be a symlink: {manifest_path}")
                if not os.path.isfile(manifest_path):
                    raise ValueError(f"Library manifest must be a regular file: {manifest_path}")
                lib_manifests.append(manifest_path)
    lib_manifests = _ordered_manifest_paths(config, lib_manifests)

    ET.register_namespace("android", _ANDROID_NS)
    ET.register_namespace("tools", _TOOLS_NS)
    try:
        main_tree = ET.parse(source_manifest_path)
    except ET.ParseError as error:
        raise ValueError(f"Failed to parse app manifest {source_manifest_path}: {error}") from error
    main_root = main_tree.getroot()
    if main_root.tag != "manifest":
        raise ValueError(f"App manifest root element must be <manifest>: {source_manifest_path}")
    _validate_tools_attributes(main_root, source_manifest_path)
    _replace_placeholders(main_root, config, source_manifest_path)
    _apply_sdk_configuration(main_root, config)
    source_files = {}
    source_packages = {}
    attribute_sources = {}
    _remember_tree(
        main_root,
        source_manifest_path,
        main_root.attrib.get("package"),
        source_files,
        source_packages,
        attribute_sources,
    )
    source_priorities = {source_manifest_path: 0}

    if lib_manifests:
        log.info("Merging %d library manifests", len(lib_manifests))
    for priority, manifest_path in enumerate(lib_manifests, 1):
        try:
            library_root = ET.parse(manifest_path).getroot()
        except ET.ParseError as error:
            raise ValueError(f"Failed to parse library manifest {manifest_path}: {error}") from error
        if library_root.tag != "manifest":
            raise ValueError(f"Library manifest root element must be <manifest>: {manifest_path}")
        _validate_tools_attributes(library_root, manifest_path)
        _replace_placeholders(library_root, config, manifest_path)
        source_priorities[manifest_path] = priority
        _merge_children(
            main_root,
            library_root,
            manifest_path,
            library_root.attrib.get("package"),
            source_files,
            source_packages,
            source_priorities,
            attribute_sources,
        )

    _strip_tools_markers(main_root)
    os.makedirs(config.build_dir, exist_ok=True)
    merged_path = os.path.join(config.build_dir, "AndroidManifest.xml")
    if os.path.islink(merged_path):
        raise ValueError(f"Merged manifest output path must not be a symlink: {merged_path}")
    if os.path.realpath(merged_path) == os.path.realpath(source_manifest_path):
        merged_path = os.path.join(config.build_dir, "AndroidManifest.merged.xml")
        if os.path.islink(merged_path):
            raise ValueError(f"Merged manifest output path must not be a symlink: {merged_path}")
        if os.path.realpath(merged_path) == os.path.realpath(source_manifest_path):
            merged_path = os.path.join(config.build_dir, "AndroidManifest.generated.xml")
            if os.path.islink(merged_path):
                raise ValueError(f"Merged manifest output path must not be a symlink: {merged_path}")
    main_tree.write(merged_path, xml_declaration=True, encoding="utf-8")
    config.manifest_path = merged_path
