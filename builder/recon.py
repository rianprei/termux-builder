import html
import json
import os
import re
import xml.etree.ElementTree as ET
import zipfile

from builder.decompile import decompile
from builder.utils import find_files, log, sha256_file

_NS = "{http://schemas.android.com/apk/res/android}"

# (category, severity, confidence, regex)
_PATTERNS = [
    ("hardcoded_secret", "high", "medium", re.compile(r'(?i)(api[_-]?key|secret|password|passwd|token)\s*[:=]\s*"[^"]{6,}"')),
    ("firebase_url", "medium", "high", re.compile(r'https?://[a-zA-Z0-9_-]+\.firebaseio\.com')),
    ("aws_key", "high", "high", re.compile(r'AKIA[0-9A-Z]{16}')),
    ("url", "low", "high", re.compile(r'https?://[^\s"\']+')),
    ("cleartext_http", "medium", "high", re.compile(r'http://[^\s"\']+')),
    ("webview_js", "medium", "high", re.compile(r'setJavaScriptEnabled|addJavascriptInterface')),
    ("shell_exec", "high", "high", re.compile(r'Runtime->exec|Runtime;->exec|ProcessBuilder')),
    ("sql", "low", "medium", re.compile(r'SQLiteDatabase|execSQL|rawQuery')),
    ("weak_crypto", "medium", "high", re.compile(r'\bDES\b|\bMD5\b|\bECB\b')),
    ("base64", "low", "low", re.compile(r'Base64->decode|Base64;->decode')),
    ("shared_prefs", "low", "low", re.compile(r'getSharedPreferences')),
]


def _attr(el, name, default=None):
    return el.get(f"{_NS}{name}", default)


def _sdk_from_yml(decompiled_dir):
    yml_path = os.path.join(decompiled_dir, "apktool.yml")
    if not os.path.isfile(yml_path):
        return None, None
    text = open(yml_path).read()
    min_m = re.search(r"minSdkVersion:\s*(\S+)", text)
    target_m = re.search(r"targetSdkVersion:\s*(\S+)", text)
    return (min_m.group(1) if min_m else None), (target_m.group(1) if target_m else None)


def parse_manifest(decompiled_dir):
    """Analytical manifest parse (permissions, exported components, sdk) — for recon, not build merging."""
    manifest_path = os.path.join(decompiled_dir, "AndroidManifest.xml")
    root = ET.parse(manifest_path).getroot()

    result = {
        "package": root.get("package"),
        "version_code": root.get(f"{_NS}versionCode"),
        "version_name": root.get(f"{_NS}versionName"),
        "permissions": [],
        "min_sdk": None,
        "target_sdk": None,
        "components": {"activity": [], "service": [], "receiver": [], "provider": []},
        "debuggable": False,
        "allow_backup": True,
    }

    sdk = root.find("uses-sdk")
    if sdk is not None:
        result["min_sdk"] = _attr(sdk, "minSdkVersion")
        result["target_sdk"] = _attr(sdk, "targetSdkVersion")
    if result["min_sdk"] is None and result["target_sdk"] is None:
        result["min_sdk"], result["target_sdk"] = _sdk_from_yml(decompiled_dir)

    for perm in root.findall("uses-permission"):
        name = _attr(perm, "name")
        if name:
            result["permissions"].append(name)

    application = root.find("application")
    if application is not None:
        result["debuggable"] = _attr(application, "debuggable") == "true"
        result["allow_backup"] = _attr(application, "allowBackup") != "false"
        for kind in result["components"]:
            for el in application.findall(kind):
                exported = _attr(el, "exported")
                has_filter = el.find("intent-filter") is not None
                is_exported = exported == "true" or (exported is None and has_filter)
                result["components"][kind].append({
                    "name": _attr(el, "name"),
                    "exported": is_exported,
                    "has_intent_filter": has_filter,
                })

    return result


def scan_findings(decompiled_dir):
    """Regex scan over smali/resources — secrets, URLs, WebView JS, exec, SQL, weak crypto."""
    findings = []
    targets = find_files(decompiled_dir, ".smali") + find_files(decompiled_dir, ".xml")
    for path in targets:
        try:
            with open(path, "r", errors="ignore") as f:
                for lineno, line in enumerate(f, 1):
                    for category, severity, confidence, pattern in _PATTERNS:
                        m = pattern.search(line)
                        if m:
                            findings.append({
                                "category": category,
                                "severity": severity,
                                "confidence": confidence,
                                "file": path,
                                "line": lineno,
                                "evidence": m.group(0)[:200],
                            })
        except (OSError, UnicodeDecodeError):
            continue
    return findings


def _native_libs(apk_path):
    libs = []
    with zipfile.ZipFile(apk_path) as z:
        for info in z.infolist():
            if info.filename.startswith("lib/") and info.filename.endswith(".so"):
                libs.append(info.filename[len("lib/"):])
    return libs


def recon(apk_path, work_dir):
    """Full recon pipeline: decompile + manifest parse + pattern scan + native lib list."""
    if not os.path.isfile(apk_path):
        raise FileNotFoundError(f"APK not found: {apk_path}")

    decompiled_dir = os.path.join(work_dir, "decompiled")
    decompile(apk_path, decompiled_dir, force=True)

    manifest_data = parse_manifest(decompiled_dir)
    findings = scan_findings(decompiled_dir)
    native_libs = _native_libs(apk_path)

    report = {
        "apk": os.path.abspath(apk_path),
        "sha256": sha256_file(apk_path),
        "manifest": manifest_data,
        "native_libs": native_libs,
        "findings_by_severity": {
            sev: len([f for f in findings if f["severity"] == sev])
            for sev in ("high", "medium", "low")
        },
        "findings": findings,
    }

    high = report["findings_by_severity"]["high"]
    log.info("Recon: %s findings (%d high, %d medium, %d low)",
              len(findings), high, report["findings_by_severity"]["medium"], report["findings_by_severity"]["low"])
    if high:
        log.warning("%d HIGH severity findings", high)

    return report


def write_json(report, path):
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    return path


def write_html(report, path):
    rows = "\n".join(
        f"<tr><td>{f['severity']}</td><td>{f['category']}</td>"
        f"<td>{html.escape(f['file'])}:{f['line']}</td>"
        f"<td><code>{html.escape(f['evidence'])}</code></td></tr>"
        for f in report["findings"]
    )
    perms = "".join(f"<li>{html.escape(p)}</li>" for p in report["manifest"]["permissions"])
    body = f"""<html><head><meta charset="utf-8"><title>termux-builder recon</title>
<style>body{{font-family:monospace}} table{{border-collapse:collapse}} td,th{{border:1px solid #ccc;padding:4px}}</style>
</head><body>
<h1>{html.escape(report['manifest'].get('package') or '?')}</h1>
<p>sha256: {report['sha256']}</p>
<p>min-sdk: {report['manifest'].get('min_sdk')} target-sdk: {report['manifest'].get('target_sdk')}
debuggable: {report['manifest'].get('debuggable')} allow-backup: {report['manifest'].get('allow_backup')}</p>
<h2>Permissions ({len(report['manifest']['permissions'])})</h2><ul>{perms}</ul>
<h2>Findings ({len(report['findings'])})</h2>
<table><tr><th>severity</th><th>category</th><th>location</th><th>evidence</th></tr>
{rows}
</table>
</body></html>"""
    with open(path, "w") as f:
        f.write(body)
    return path
