import json
import requests
from builder.utils import log

WELL_KNOWN_PATH = "/.well-known/assetlinks.json"


def verify(domain, package, fingerprint=None):
    """Fetch and validate a domain's Digital Asset Links file against a
    package (and optionally its signing SHA-256 fingerprint) — CLI
    replacement for Android Studio's App Links Assistant verification step."""
    url = f"https://{domain}{WELL_KNOWN_PATH}"
    log.info("Fetching %s", url)

    try:
        resp = requests.get(url, timeout=15)
    except requests.RequestException as e:
        raise RuntimeError(f"Could not reach {url}: {e}")

    if resp.status_code != 200:
        raise RuntimeError(f"{url} returned HTTP {resp.status_code} (expected 200)")

    try:
        statements = resp.json()
    except (json.JSONDecodeError, ValueError):
        raise RuntimeError(f"{url} is not valid JSON")

    matches = []
    for stmt in statements:
        target = stmt.get("target", {})
        if target.get("package_name") != package:
            continue
        if "delegate_permission/common.handle_all_urls" not in stmt.get("relation", []):
            continue
        fps = target.get("sha256_cert_fingerprints", [])
        if fingerprint and fingerprint.upper() not in [f.upper() for f in fps]:
            continue
        matches.append(stmt)

    if not matches:
        raise RuntimeError(
            f"No matching statement for package={package}"
            + (f" fingerprint={fingerprint}" if fingerprint else "")
            + f" in {url}"
        )

    log.info("Verified: %d matching statement(s)", len(matches))
    for stmt in matches:
        log.info("  package: %s", stmt["target"]["package_name"])
        log.info("  fingerprints: %s", ", ".join(stmt["target"].get("sha256_cert_fingerprints", [])))

    return matches
