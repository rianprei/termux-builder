import os
import re
import shutil
import stat
import zipfile
import xml.etree.ElementTree as ET
import requests
from builder.utils import ensure_dir, log

MAVEN_REPOS = [
    "https://repo1.maven.org/maven2",
    "https://dl.google.com/dl/android/maven2",
]


def resolve(config):
    if not config.dependencies:
        return

    log.info("Resolving %d dependencies", len(config.dependencies))
    deps_cache = ensure_dir(os.path.join(config.cache_dir, "deps"))
    libs_dir = ensure_dir(config.libs_dir)

    resolved = set()
    queue = list(config.dependencies)

    while queue:
        coord = queue.pop(0)
        if coord in resolved:
            continue
        resolved.add(coord)

        parts = coord.split(":")
        if len(parts) != 3:
            log.warning("Invalid dependency format: %s (expected group:artifact:version)", coord)
            continue

        group, artifact, version = parts
        # group/artifact: strict — no path traversal chars ever needed
        # version: allow Maven range syntax ([1.0,2.0), [1.0], etc.)
        if not re.fullmatch(r"[A-Za-z0-9._-]+", group) or not re.fullmatch(r"[A-Za-z0-9._-]+", artifact):
            log.warning("Unsafe dependency coordinate skipped: %s", coord)
            continue
        if not re.fullmatch(r"[A-Za-z0-9._+\[\](),-]+", version):
            log.warning("Unsafe dependency coordinate skipped: %s", coord)
            continue
        group_path = group.replace(".", "/")

        lib_out = os.path.join(libs_dir, f"{artifact}-{version}")
        if os.path.isdir(lib_out) and _has_jar(lib_out):
            log.debug("Cached: %s", coord)
            transitive = _read_cached_transitive(lib_out)
            for t in transitive:
                if t not in resolved:
                    queue.append(t)
            continue

        pom_url = _find_artifact(group_path, artifact, version, "pom")
        if not pom_url:
            log.warning("Dependency not found: %s", coord)
            continue

        try:
            pom_data = requests.get(pom_url, timeout=30).text
        except requests.RequestException as e:
            log.warning("Failed to fetch POM for %s: %s", coord, e)
            continue
        transitive = _parse_pom_deps(pom_data)

        packaging = _detect_packaging(pom_data)
        artifact_url = _find_artifact(group_path, artifact, version, packaging)
        if not artifact_url:
            log.warning("Artifact not downloadable: %s", coord)
            continue

        ensure_dir(lib_out)
        artifact_path = os.path.join(deps_cache, f"{artifact}-{version}.{packaging}")

        if not os.path.isfile(artifact_path):
            log.info("Downloading: %s", coord)
            _download(artifact_url, artifact_path)

        if packaging == "aar":
            _extract_aar(artifact_path, lib_out)
        else:
            import shutil
            shutil.copy2(artifact_path, os.path.join(lib_out, f"{artifact}-{version}.jar"))

        _save_transitive(lib_out, transitive)
        for t in transitive:
            if t not in resolved:
                queue.append(t)

    log.info("Dependencies resolved: %d", len(resolved))


def _find_artifact(group_path, artifact, version, ext):
    filename = f"{artifact}-{version}.{ext}"
    for repo in MAVEN_REPOS:
        url = f"{repo}/{group_path}/{artifact}/{version}/{filename}"
        try:
            r = requests.head(url, timeout=10, allow_redirects=True)
            if r.status_code == 200:
                return url
        except requests.RequestException:
            pass
        try:
            r = requests.get(url, timeout=10, stream=True, allow_redirects=True)
            if r.status_code == 200:
                return url
        except requests.RequestException:
            continue
    return None


def _detect_packaging(pom_xml):
    try:
        root = ET.fromstring(pom_xml)
        ns = {"m": "http://maven.apache.org/POM/4.0.0"}
        pkg = root.find("m:packaging", ns)
        if pkg is not None and pkg.text:
            return pkg.text.strip()
    except ET.ParseError:
        pass
    return "jar"


def _parse_pom_deps(pom_xml):
    deps = []
    try:
        root = ET.fromstring(pom_xml)
        ns = {"m": "http://maven.apache.org/POM/4.0.0"}
        for dep in root.findall(".//m:dependencies/m:dependency", ns):
            scope = dep.find("m:scope", ns)
            if scope is not None and scope.text in ("test", "provided"):
                continue
            optional = dep.find("m:optional", ns)
            if optional is not None and optional.text == "true":
                continue

            g = dep.find("m:groupId", ns)
            a = dep.find("m:artifactId", ns)
            v = dep.find("m:version", ns)
            if g is not None and a is not None and v is not None:
                if g.text and a.text and v.text and not v.text.startswith("$"):
                    deps.append(f"{g.text}:{a.text}:{v.text}")
    except ET.ParseError:
        pass
    return deps


def _download(url, dest):
    tmp = dest + ".tmp"
    r = requests.get(url, timeout=60, stream=True)
    r.raise_for_status()
    with open(tmp, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)
    os.rename(tmp, dest)


def _extract_aar(aar_path, out_dir):
    log.debug("Extracting AAR: %s", aar_path)
    tmp_dir = out_dir + ".tmp"
    if os.path.isdir(tmp_dir):
        shutil.rmtree(tmp_dir)
    os.makedirs(tmp_dir, exist_ok=True)
    with zipfile.ZipFile(aar_path) as z:
        for member in z.infolist():
            member_path = os.path.normpath(os.path.join(tmp_dir, member.filename))
            if not member_path.startswith(os.path.normpath(tmp_dir) + os.sep):
                log.warning("Skipping unsafe AAR entry: %s", member.filename)
                continue
            # symlink entries: external_attr high 16 bits hold unix mode (S_ISLNK)
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                log.warning("Skipping symlink AAR entry: %s", member.filename)
                continue
            z.extract(member, tmp_dir)
    classes_jar = os.path.join(tmp_dir, "classes.jar")
    if os.path.isfile(classes_jar):
        base = os.path.basename(out_dir)
        os.rename(classes_jar, os.path.join(tmp_dir, f"{base}.jar"))
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.rename(tmp_dir, out_dir)


def _has_jar(lib_dir):
    for f in os.listdir(lib_dir):
        if f.endswith(".jar"):
            return True
    return False


def _save_transitive(lib_dir, deps):
    if not deps:
        return
    with open(os.path.join(lib_dir, ".transitive"), "w") as f:
        f.write("\n".join(deps))


def _read_cached_transitive(lib_dir):
    path = os.path.join(lib_dir, ".transitive")
    if not os.path.isfile(path):
        return []
    with open(path) as f:
        return [l.strip() for l in f if l.strip()]
