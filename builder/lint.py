import os
import xml.etree.ElementTree as ET
from builder.utils import log, find_files


def check(config):
    log.info("Running lint checks")
    issues = 0

    issues += _check_manifest(config)
    issues += _check_java_sources(config)
    issues += _check_resources(config)

    if issues == 0:
        log.info("Lint: no issues found")
    else:
        log.warning("Lint: %d issue(s) found", issues)

    return issues


def _check_manifest(config):
    issues = 0
    try:
        tree = ET.parse(config.manifest_path)
        root = tree.getroot()
        ns = "http://schemas.android.com/apk/res/android"

        app = root.find("application")
        if app is not None:
            for activity in app.findall("activity"):
                exported = activity.attrib.get(f"{{{ns}}}exported")
                has_filter = activity.find("intent-filter") is not None
                if has_filter and exported is None:
                    name = activity.attrib.get(f"{{{ns}}}name", "?")
                    log.warning("Lint: %s has intent-filter but no android:exported", name)
                    issues += 1

            if not app.attrib.get(f"{{{ns}}}allowBackup"):
                log.warning("Lint: application missing android:allowBackup attribute")
                issues += 1

    except ET.ParseError:
        log.warning("Lint: could not parse AndroidManifest.xml")
        issues += 1

    return issues


def _check_java_sources(config):
    issues = 0
    java_files = find_files(config.sources_dir, ".java")
    kt_files = find_files(config.sources_dir, ".kt")

    for path in java_files + kt_files:
        with open(path) as f:
            content = f.read()

        basename = os.path.basename(path)

        if "System.out.println" in content:
            log.warning("Lint: %s contains System.out.println — use Log instead", basename)
            issues += 1

        if "printStackTrace" in content:
            log.warning("Lint: %s contains printStackTrace — use Log.e instead", basename)
            issues += 1

        if "StrictMode" in content and "debug" not in basename.lower():
            log.warning("Lint: %s references StrictMode in non-debug code", basename)
            issues += 1

        if "Thread.sleep" in content:
            log.warning("Lint: %s uses Thread.sleep — avoid on main thread", basename)
            issues += 1

    return issues


def _check_resources(config):
    issues = 0

    strings_file = os.path.join(config.res_dir, "values", "strings.xml")
    if not os.path.isfile(strings_file):
        log.warning("Lint: missing res/values/strings.xml")
        issues += 1

    layout_dir = os.path.join(config.res_dir, "layout")
    if os.path.isdir(layout_dir):
        for f in os.listdir(layout_dir):
            if not f.endswith(".xml"):
                continue
            path = os.path.join(layout_dir, f)
            try:
                tree = ET.parse(path)
                root = tree.getroot()
                _check_layout_depth(root, f, 0, issues)
            except ET.ParseError:
                log.warning("Lint: could not parse layout %s", f)
                issues += 1

    return issues


def _check_layout_depth(element, filename, depth, issues):
    if depth > 10:
        log.warning("Lint: %s has deeply nested views (>10 levels)", filename)
        return issues + 1
    for child in element:
        issues = _check_layout_depth(child, filename, depth + 1, issues)
    return issues
