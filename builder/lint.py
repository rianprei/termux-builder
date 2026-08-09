import html
import logging
import os
import xml.etree.ElementTree as ET
from builder.utils import log, find_files


class _Collector(logging.Handler):
    """Captures 'Lint: ...' warnings emitted by the checks below, so report
    writers reuse the exact same messages instead of duplicating logic."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.messages = []

    def emit(self, record):
        msg = record.getMessage()
        if msg.startswith("Lint: "):
            self.messages.append(msg[len("Lint: "):])


def _run_checks(config):
    collector = _Collector()
    log.addHandler(collector)
    try:
        _check_manifest(config)
        _check_java_sources(config)
        _check_resources(config)
        _check_unused_resources(config)
        _check_deprecated_apis(config)
    finally:
        log.removeHandler(collector)
    return collector.messages


def check(config, report=None, baseline=None):
    log.info("Running lint checks")

    baseline_set = _load_baseline(baseline) if baseline else set()
    all_messages = _run_checks(config)
    new_messages = [m for m in all_messages if m not in baseline_set]
    issues = len(new_messages)

    if baseline_set:
        suppressed = len(all_messages) - issues
        if suppressed:
            log.info("Lint: %d issue(s) suppressed by baseline", suppressed)

    if issues == 0:
        log.info("Lint: no issues found")
    else:
        log.warning("Lint: %d issue(s) found", issues)

    if report:
        _write_report(report, new_messages)

    return issues


def write_baseline(config, path):
    """Snapshot current lint findings so future runs only fail on issues introduced after this point."""
    messages = _run_checks(config)
    with open(path, "w") as f:
        f.write("\n".join(messages))
    log.info("Lint baseline written: %s (%d issue(s) snapshotted)", path, len(messages))
    return len(messages)


def _load_baseline(path):
    if not os.path.isfile(path):
        return set()
    with open(path) as f:
        return {l.strip() for l in f if l.strip()}


def _write_report(path, messages):
    if path.endswith(".html"):
        rows = "\n".join(f"<tr><td>{html.escape(m)}</td></tr>" for m in messages)
        content = (
            "<html><head><title>Lint Report</title></head><body>"
            f"<h1>Lint Report — {len(messages)} issue(s)</h1>"
            f"<table border=\"1\">{rows}</table></body></html>"
        )
    else:
        lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<issues>"]
        for msg in messages:
            lines.append(f'  <issue message="{html.escape(msg)}" severity="Warning" />')
        lines.append("</issues>")
        content = "\n".join(lines)
    with open(path, "w") as f:
        f.write(content)
    log.info("Lint report written: %s", path)


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
                issues += _check_layout_depth(root, f, 0)
            except ET.ParseError:
                log.warning("Lint: could not parse layout %s", f)
                issues += 1

    return issues


def _check_layout_depth(element, filename, depth):
    issues = 0
    if depth > 10:
        log.warning("Lint: %s has deeply nested views (>10 levels)", filename)
        return 1
    for child in element:
        issues += _check_layout_depth(child, filename, depth + 1)
    return issues

_DEPRECATED_APIS = {
    "android.os.AsyncTask": "use java.util.concurrent or Kotlin coroutines",
    "org.apache.http": "use java.net.HttpURLConnection or OkHttp",
    "android.app.Fragment": "use androidx.fragment.app.Fragment",
    "android.hardware.Camera": "use android.hardware.camera2 or CameraX",
    "android.webkit.WebViewFragment": "deprecated since API 28",
}


def _check_deprecated_apis(config):
    issues = 0
    java_files = find_files(config.sources_dir, ".java")
    kt_files = find_files(config.sources_dir, ".kt")

    for path in java_files + kt_files:
        with open(path) as f:
            content = f.read()
        basename = os.path.basename(path)
        for api, hint in _DEPRECATED_APIS.items():
            if api in content:
                log.warning("Lint: %s uses deprecated %s — %s", basename, api, hint)
                issues += 1

    return issues


def _check_unused_resources(config):
    issues = 0
    declared = set()

    values_dir = os.path.join(config.res_dir, "values")
    if os.path.isdir(values_dir):
        for f in os.listdir(values_dir):
            if not f.endswith(".xml"):
                continue
            try:
                tree = ET.parse(os.path.join(values_dir, f))
                for elem in tree.getroot():
                    name = elem.attrib.get("name")
                    if name:
                        declared.add(name)
            except ET.ParseError:
                continue

    for kind in ("drawable", "layout", "mipmap"):
        kind_dir = os.path.join(config.res_dir, kind)
        if os.path.isdir(kind_dir):
            for f in os.listdir(kind_dir):
                declared.add(os.path.splitext(f)[0])

    styles = set()
    if os.path.isdir(values_dir):
        for f in os.listdir(values_dir):
            if not f.endswith(".xml"):
                continue
            try:
                tree = ET.parse(os.path.join(values_dir, f))
                for elem in tree.getroot():
                    if elem.tag == "style":
                        name = elem.attrib.get("name")
                        if name:
                            styles.add(name)
            except ET.ParseError:
                continue

    if not declared:
        return 0

    referenced = set()
    all_src = (
        find_files(config.sources_dir, ".java")
        + find_files(config.sources_dir, ".kt")
        + find_files(config.res_dir, ".xml")
        + ([config.manifest_path] if os.path.isfile(config.manifest_path) else [])
    )
    for path in all_src:
        with open(path) as f:
            content = f.read()
        for name in declared:
            if name in referenced:
                continue
            if f"R.string.{name}" in content or f"R.drawable.{name}" in content \
               or f"R.layout.{name}" in content or f"R.mipmap.{name}" in content \
               or f"@string/{name}" in content or f"@drawable/{name}" in content \
               or f"@layout/{name}" in content or f"@mipmap/{name}" in content \
               or (name in styles and (f"@style/{name}" in content or f"R.style.{name}" in content \
                   or f'parent="{name}"' in content)):
                referenced.add(name)

    unused = declared - referenced
    for name in sorted(unused):
        log.warning("Lint: resource '%s' declared but never referenced", name)
        issues += 1

    return issues
