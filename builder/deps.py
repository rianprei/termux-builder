import json
import hashlib
import os
import re
import shutil
import stat
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

import requests
from builder.utils import ensure_dir, log

MAVEN_REPOS = [
    "https://repo1.maven.org/maven2",
    "https://dl.google.com/dl/android/maven2",
]
MAX_AAR_ENTRIES = 100_000
MAX_AAR_UNCOMPRESSED_BYTES = 512 * 1024 * 1024


def _normalize_maven_version(version):
    exact_range = re.fullmatch(r"\[([A-Za-z0-9._+-]+)\]", version)
    if exact_range:
        return exact_range.group(1)
    if any(marker in version for marker in "[](),"):
        raise ValueError(
            f"Unsupported Maven version range {version}; only exact versions and [version] are supported"
        )
    return version


def _maven_group_segments(group):
    segments = group.split(".")
    if not segments or any(
        not re.fullmatch(r"[A-Za-z0-9_-]+", segment) for segment in segments
    ):
        raise ValueError(f"Unsafe Maven groupId: {group}")
    return segments


def _maven_dependency_dir(libs_dir, group_segments, artifact, version, dependency_type):
    artifact_dir = f"{artifact}-{version}"
    if dependency_type and dependency_type != "jar":
        artifact_dir += f"-{dependency_type}"
    return os.path.join(
        libs_dir, ".termux-builder", "maven", *group_segments, artifact_dir
    )


def _unpack_dependency_edge(edge):
    if not isinstance(edge, (tuple, list)) or len(edge) not in (2, 3):
        raise ValueError(f"Invalid cached Maven dependency edge: {edge!r}")
    coordinate, exclusions = edge[:2]
    dependency_type = edge[2] if len(edge) == 3 else None
    if dependency_type not in (None, "jar", "aar"):
        raise ValueError(f"Unsupported Maven dependency type: {dependency_type}")
    return coordinate, exclusions, dependency_type


def _ensure_safe_directory(root, *segments):
    directory = os.path.abspath(ensure_dir(root))
    for segment in segments:
        if (
            segment in ("", ".", "..")
            or os.sep in segment
            or (os.altsep is not None and os.altsep in segment)
        ):
            raise ValueError(f"Unsafe dependency cache path component: {segment!r}")
        directory = os.path.join(directory, segment)
        if os.path.islink(directory):
            raise RuntimeError(f"Refusing symlink dependency cache directory: {directory}")
        if os.path.lexists(directory) and not os.path.isdir(directory):
            raise RuntimeError(f"Dependency cache path is not a directory: {directory}")
        ensure_dir(directory)
    return directory


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dependency_file_hashes(directory):
    metadata_names = {
        ".termux-builder-coordinate",
        ".termux-builder-transitive.json",
        ".termux-builder-artifact.json",
        ".transitive",
    }
    directory = os.path.abspath(directory)
    hashes = {}
    for current, directories, files in os.walk(directory, followlinks=False):
        for name in directories:
            path = os.path.join(current, name)
            if os.path.islink(path):
                raise RuntimeError(f"Refusing symlink in cached dependency: {path}")
        for name in files:
            if current == directory and name in metadata_names:
                continue
            path = os.path.join(current, name)
            if os.path.islink(path) or not os.path.isfile(path):
                raise RuntimeError(f"Invalid file in cached dependency: {path}")
            relative = os.path.relpath(path, directory).replace(os.sep, "/")
            hashes[relative] = _sha256_file(path)
    return hashes


def _read_artifact_cache_metadata(artifact_path, coordinate):
    if os.path.islink(artifact_path):
        raise RuntimeError(f"Refusing symlink Maven artifact cache: {artifact_path}")
    if not os.path.isfile(artifact_path):
        return None

    metadata_path = artifact_path + ".metadata.json"
    if os.path.islink(metadata_path):
        raise RuntimeError(f"Refusing symlink Maven artifact metadata: {metadata_path}")
    if not os.path.isfile(metadata_path):
        return None
    try:
        with open(metadata_path) as file:
            metadata = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Invalid Maven artifact cache metadata: {metadata_path}: {error}") from error

    if not isinstance(metadata, dict) or metadata.get("coordinate") != coordinate:
        raise RuntimeError(f"Maven artifact cache coordinate mismatch: {metadata_path}")
    source_url = metadata.get("source_url")
    digest = metadata.get("sha256")
    sha1 = metadata.get("sha1")
    if (
        metadata.get("schema_version") != 1
        or not isinstance(source_url, str)
        or not isinstance(digest, str)
        or not re.fullmatch(r"[a-fA-F0-9]{64}", digest)
        or (sha1 is not None and (not isinstance(sha1, str) or not re.fullmatch(r"[a-fA-F0-9]{40}", sha1)))
    ):
        raise RuntimeError(f"Invalid Maven artifact cache metadata: {metadata_path}")
    try:
        _validate_maven_url(source_url)
    except (RuntimeError, ValueError) as error:
        raise RuntimeError(f"Invalid Maven artifact source in cache metadata: {metadata_path}") from error

    if _sha256_file(artifact_path) != digest.lower():
        log.warning("Cached Maven artifact failed SHA-256 verification: %s", coordinate)
        return None
    metadata["sha256"] = digest.lower()
    metadata["sha1"] = sha1.lower() if sha1 else None
    return metadata


def _save_artifact_cache_metadata(artifact_path, coordinate, source_url, sha1):
    metadata = {
        "schema_version": 1,
        "coordinate": coordinate,
        "source_url": source_url,
        "sha256": _sha256_file(artifact_path),
        "sha1": sha1,
    }
    _write_dependency_metadata(
        artifact_path + ".metadata.json",
        json.dumps(metadata, sort_keys=True, separators=(",", ":")),
    )
    return metadata


def _read_dependency_provenance(directory, coordinate):
    marker = os.path.join(directory, ".termux-builder-coordinate")
    metadata_path = os.path.join(directory, ".termux-builder-artifact.json")
    for path in (marker, metadata_path):
        if os.path.islink(path):
            raise RuntimeError(f"Refusing symlink dependency metadata: {path}")
    if not os.path.isfile(marker):
        return None
    with open(marker) as file:
        if file.read().strip() != coordinate:
            raise RuntimeError(f"Maven dependency cache coordinate mismatch: {marker}")
    if not os.path.isfile(metadata_path):
        return None
    try:
        with open(metadata_path) as file:
            metadata = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Invalid Maven dependency metadata: {metadata_path}: {error}") from error

    source_url = metadata.get("source_url") if isinstance(metadata, dict) else None
    digest = metadata.get("artifact_sha256") if isinstance(metadata, dict) else None
    sha1 = metadata.get("sha1") if isinstance(metadata, dict) else None
    files = metadata.get("files") if isinstance(metadata, dict) else None
    if (
        not isinstance(metadata, dict)
        or metadata.get("schema_version") != 1
        or metadata.get("coordinate") != coordinate
        or metadata.get("packaging") not in ("jar", "aar")
        or not isinstance(source_url, str)
        or not isinstance(digest, str)
        or not re.fullmatch(r"[a-fA-F0-9]{64}", digest)
        or (sha1 is not None and (not isinstance(sha1, str) or not re.fullmatch(r"[a-fA-F0-9]{40}", sha1)))
        or not isinstance(files, dict)
        or any(
            not isinstance(path, str)
            or not isinstance(file_digest, str)
            or not re.fullmatch(r"[a-fA-F0-9]{64}", file_digest)
            for path, file_digest in files.items()
        )
    ):
        raise RuntimeError(f"Invalid Maven dependency metadata: {metadata_path}")
    try:
        _validate_maven_url(source_url)
    except (RuntimeError, ValueError) as error:
        raise RuntimeError(f"Invalid Maven dependency source: {metadata_path}") from error
    if _dependency_file_hashes(directory) != files:
        log.warning("Cached Maven dependency contents changed: %s", coordinate)
        return None
    metadata["artifact_sha256"] = digest.lower()
    metadata["sha1"] = sha1.lower() if sha1 else None
    return metadata


def _claim_maven_version(selected_versions, group, artifact, version, dependency_type=None):
    key = f"{group}:{artifact}:{dependency_type or 'jar'}"
    selected = selected_versions.get(key)
    if selected is None:
        selected_versions[key] = version
        return True
    if selected == version:
        return True
    log.warning(
        "Maven version conflict for %s: using nearest selected version %s; skipping %s",
        key,
        selected,
        version,
    )
    return False


def _is_maven_excluded(group, artifact, exclusions):
    return any(
        (excluded_group == "*" or excluded_group == group)
        and (excluded_artifact == "*" or excluded_artifact == artifact)
        for excluded_group, excluded_artifact in exclusions
    )


def _enqueue_transitive(queue, dependencies, inherited_exclusions):
    for edge in dependencies:
        coordinate, edge_exclusions, dependency_type = _unpack_dependency_edge(edge)
        group, artifact, _ = coordinate.split(":", 2)
        if not _is_maven_excluded(group, artifact, inherited_exclusions):
            queue.append((
                coordinate,
                frozenset(inherited_exclusions | edge_exclusions),
                dependency_type,
            ))


def resolve(config):
    _cleanup_stale_aar_staging(config.libs_dir)
    if not config.dependencies:
        config.resolved_dependency_dirs = set()
        return

    log.info("Resolving %d dependencies", len(config.dependencies))
    deps_cache = ensure_dir(os.path.join(config.cache_dir, "deps"))
    libs_dir = ensure_dir(config.libs_dir)

    resolved = set()
    selected_versions = {}
    selected_dependency_dirs = set()
    expanded_paths = set()
    transitive_by_coordinate = {}
    dependency_poms = {}
    queue = [(coord, frozenset(), None) for coord in config.dependencies]
    bom_cache = {}
    parent_cache = {}

    def fetch_pom(pom_url, coordinate):
        response = None
        try:
            response = _maven_request("get", pom_url, timeout=30)
            response.raise_for_status()
            if response.status_code != 200:
                raise requests.HTTPError(f"Unexpected POM response status {response.status_code}")
            return response.text
        except requests.RequestException as error:
            raise RuntimeError(f"Failed to fetch POM for {coordinate}: {error}") from error
        finally:
            if response is not None:
                response.close()

    def parse_remote_model(pom_data, coordinate, ancestry):
        return _parse_pom_model(
            pom_data,
            lambda group, artifact, version: load_bom(
                group, artifact, version, ancestry | {coordinate}
            ),
            lambda group, artifact, version: load_parent(
                group, artifact, version, ancestry | {coordinate}
            ),
        )

    def dependency_pom(group_path, artifact, version, coordinate):
        if coordinate not in dependency_poms:
            pom_url = _find_artifact(group_path, artifact, version, "pom")
            if not pom_url:
                raise RuntimeError(f"Dependency not found: {coordinate}")
            dependency_poms[coordinate] = (pom_url, fetch_pom(pom_url, coordinate))
        return dependency_poms[coordinate]

    def load_bom(group, artifact, version, ancestry=frozenset()):
        try:
            group_segments = _maven_group_segments(group)
        except ValueError as error:
            raise ValueError(f"Unsafe Maven BOM coordinate: {group}:{artifact}:{version}") from error
        if artifact in (".", "..") or not re.fullmatch(
            r"[A-Za-z0-9._-]+", artifact
        ) or not re.fullmatch(r"[A-Za-z0-9._+\[\](),-]+", version):
            raise ValueError(f"Unsafe Maven BOM coordinate: {group}:{artifact}:{version}")
        version = _normalize_maven_version(version)
        coordinate = f"{group}:{artifact}:{version}"
        if coordinate in ancestry:
            raise ValueError(f"Cyclic Maven BOM import: {coordinate}")
        if coordinate in bom_cache:
            return bom_cache[coordinate]
        group_path = "/".join(group_segments)
        pom_url = _find_artifact(group_path, artifact, version, "pom")
        if not pom_url:
            raise RuntimeError(f"Maven BOM not found: {coordinate}")
        pom_data = fetch_pom(pom_url, f"BOM {coordinate}")
        try:
            _, management, _ = parse_remote_model(pom_data, coordinate, ancestry)
        except ValueError as error:
            raise ValueError(f"Unsupported Maven BOM {coordinate} at {pom_url}: {error}") from error
        bom_cache[coordinate] = management
        return management

    def load_parent(group, artifact, version, ancestry=frozenset()):
        try:
            group_segments = _maven_group_segments(group)
        except ValueError as error:
            raise ValueError(f"Unsafe Maven parent coordinate: {group}:{artifact}:{version}") from error
        if artifact in (".", "..") or not re.fullmatch(
            r"[A-Za-z0-9._-]+", artifact
        ) or not re.fullmatch(r"[A-Za-z0-9._+\[\](),-]+", version):
            raise ValueError(f"Unsafe Maven parent coordinate: {group}:{artifact}:{version}")
        version = _normalize_maven_version(version)
        coordinate = f"{group}:{artifact}:{version}"
        if coordinate in ancestry:
            raise ValueError(f"Cyclic Maven parent inheritance: {coordinate}")
        if coordinate in parent_cache:
            return parent_cache[coordinate]
        group_path = "/".join(group_segments)
        pom_url = _find_artifact(group_path, artifact, version, "pom")
        if not pom_url:
            raise RuntimeError(f"Maven parent POM not found: {coordinate}")
        pom_data = fetch_pom(pom_url, f"parent {coordinate}")
        try:
            model = parse_remote_model(pom_data, coordinate, ancestry)
        except ValueError as error:
            raise ValueError(f"Unsupported Maven parent {coordinate} at {pom_url}: {error}") from error
        parent_cache[coordinate] = model
        return model

    while queue:
        coord, inherited_exclusions, requested_type = queue.pop(0)
        if not isinstance(coord, str):
            raise ValueError(f"Invalid dependency coordinate: {coord!r}")

        parts = coord.split(":")
        if len(parts) != 3:
            raise ValueError(f"Invalid dependency format: {coord} (expected group:artifact:version)")

        group, artifact, version = parts
        # Group and artifact form paths inside the configured Maven repositories.
        try:
            group_segments = _maven_group_segments(group)
        except ValueError as error:
            raise ValueError(f"Unsafe dependency coordinate: {coord}") from error
        if artifact in (".", "..") or not re.fullmatch(r"[A-Za-z0-9._-]+", artifact):
            raise ValueError(f"Unsafe dependency coordinate: {coord}")
        if not re.fullmatch(r"[A-Za-z0-9._+\[\](),-]+", version):
            raise ValueError(f"Unsafe dependency coordinate: {coord}")
        version = _normalize_maven_version(version)
        if _is_maven_excluded(group, artifact, inherited_exclusions):
            continue
        coord = f"{group}:{artifact}:{version}"
        group_path = "/".join(group_segments)
        _ensure_safe_directory(libs_dir, ".termux-builder", "maven", *group_segments)

        cache_types = [requested_type, None]
        if requested_type is None:
            cache_types.insert(0, "aar")
        if requested_type in (None, "jar"):
            cache_types.append("legacy-jar")
        cache_candidates = []
        for cache_type in cache_types:
            if cache_type == "legacy-jar":
                candidate = os.path.join(
                    libs_dir,
                    ".termux-builder",
                    "maven",
                    *group_segments,
                    f"{artifact}-{version}-jar",
                )
            else:
                candidate = _maven_dependency_dir(
                    libs_dir, group_segments, artifact, version, cache_type
                )
            if candidate not in cache_candidates:
                cache_candidates.append(candidate)

        cached_entries = []
        for candidate in cache_candidates:
            if os.path.islink(candidate):
                raise RuntimeError(f"Refusing symlink dependency directory: {candidate}")
            if not os.path.isdir(candidate):
                continue
            metadata = _read_dependency_provenance(candidate, coord)
            if metadata is not None and (
                requested_type is None or metadata["packaging"] == requested_type
            ):
                cached_entries.append((candidate, metadata))

        cached_types = {metadata["packaging"] for _, metadata in cached_entries}
        if requested_type is None and len(cached_types) > 1:
            raise RuntimeError(
                f"Ambiguous cached Maven artifact types for {coord}: {sorted(cached_types)}"
            )
        if cached_entries:
            lib_out, cached_metadata = cached_entries[0]
            effective_type = cached_metadata["packaging"]
        else:
            lib_out = None
            if requested_type is None:
                pom_url, pom_data = dependency_pom(
                    group_path, artifact, version, coord
                )
                effective_type = _detect_packaging(pom_data)
            else:
                effective_type = requested_type
        if effective_type not in ("jar", "aar"):
            raise RuntimeError(f"Unsupported Maven packaging: {effective_type} for {coord}")
        if not _claim_maven_version(
            selected_versions, group, artifact, version, effective_type
        ):
            continue

        path_key = (coord, inherited_exclusions, effective_type)
        if path_key in expanded_paths:
            continue
        expanded_paths.add(path_key)
        resolved.add((coord, effective_type))

        resolution_key = (coord, effective_type)
        if resolution_key in transitive_by_coordinate:
            _enqueue_transitive(
                queue, transitive_by_coordinate[resolution_key], inherited_exclusions
            )
            continue

        if cached_entries:
            log.debug("Cached: %s", coord)
            selected_dependency_dirs.add(os.path.abspath(lib_out))
            transitive = _read_cached_edges(lib_out)
            transitive_by_coordinate[resolution_key] = transitive
            _enqueue_transitive(queue, transitive, inherited_exclusions)
            continue

        if coord in dependency_poms:
            pom_url, pom_data = dependency_poms[coord]
        else:
            pom_url, pom_data = dependency_pom(
                group_path, artifact, version, coord
            )
        try:
            transitive, _, _ = parse_remote_model(pom_data, coord, frozenset())
        except ValueError as error:
            raise ValueError(f"Unsupported POM for {coord} at {pom_url}: {error}") from error

        packaging = effective_type
        if packaging not in ("jar", "aar"):
            raise RuntimeError(f"Unsupported Maven packaging: {packaging} for {coord}")
        lib_out = _maven_dependency_dir(
            libs_dir, group_segments, artifact, version, packaging
        )
        artifact_url = _find_artifact(group_path, artifact, version, packaging)
        if not artifact_url:
            raise RuntimeError(f"Artifact not downloadable: {coord}")

        artifact_cache_dir = _ensure_safe_directory(deps_cache, *group_segments)
        artifact_path = os.path.join(
            artifact_cache_dir, f"{artifact}-{version}.{packaging}"
        )
        artifact_metadata = _read_artifact_cache_metadata(artifact_path, coord)
        if artifact_metadata is not None and artifact_metadata["source_url"] != artifact_url:
            log.warning("Cached Maven artifact source changed for %s; downloading again", coord)
            artifact_metadata = None

        if artifact_metadata is None:
            if os.path.lexists(artifact_path):
                if not os.path.isfile(artifact_path) or os.path.islink(artifact_path):
                    raise RuntimeError(f"Invalid Maven artifact cache path: {artifact_path}")
                log.warning("Replacing unverified Maven artifact cache: %s", coord)
                os.remove(artifact_path)
            metadata_path = artifact_path + ".metadata.json"
            if os.path.lexists(metadata_path):
                if os.path.isdir(metadata_path) and not os.path.islink(metadata_path):
                    raise RuntimeError(f"Invalid Maven artifact metadata path: {metadata_path}")
                os.remove(metadata_path)
            log.info("Downloading: %s", coord)
            _download(artifact_url, artifact_path)
            sha1 = _verify_checksum(artifact_url, artifact_path, coord)
            artifact_metadata = _save_artifact_cache_metadata(
                artifact_path, coord, artifact_url, sha1
            )

        if packaging == "aar":
            _extract_aar(artifact_path, lib_out)
        else:
            if os.path.lexists(lib_out):
                if not os.path.isdir(lib_out) or os.path.islink(lib_out):
                    raise RuntimeError(f"Invalid Maven dependency output path: {lib_out}")
                shutil.rmtree(lib_out)
            ensure_dir(lib_out)
            shutil.copy2(artifact_path, os.path.join(lib_out, f"{artifact}-{version}.jar"))

        _mark_dependency(lib_out, coord)
        selected_dependency_dirs.add(os.path.abspath(lib_out))
        _save_transitive(lib_out, transitive)
        dependency_metadata = {
            "schema_version": 1,
            "coordinate": coord,
            "source_url": artifact_metadata["source_url"],
            "artifact_sha256": artifact_metadata["sha256"],
            "sha1": artifact_metadata["sha1"],
            "packaging": packaging,
            "files": _dependency_file_hashes(lib_out),
        }
        _write_dependency_metadata(
            os.path.join(lib_out, ".termux-builder-artifact.json"),
            json.dumps(dependency_metadata, sort_keys=True, separators=(",", ":")),
        )
        transitive_by_coordinate[resolution_key] = transitive
        _enqueue_transitive(queue, transitive, inherited_exclusions)

    config.resolved_dependency_dirs = selected_dependency_dirs
    log.info("Dependencies resolved: %d", len(resolved))


def tree(config):
    """Print the resolved dependency tree from cached transitive-deps files —
    CLI replacement for Android Studio's Gradle dependency explorer."""
    libs_dir = config.libs_dir

    def _print(coord, depth, seen_chain, inherited_exclusions, requested_type=None):
        indent = "  " * depth
        if coord in seen_chain:
            log.info("%s%s (cycle)", indent, coord)
            return
        log.info("%s%s", indent, coord)
        parts = coord.split(":")
        if len(parts) != 3:
            raise ValueError(f"Invalid dependency format: {coord}")
        group, artifact, version = parts
        try:
            group_segments = _maven_group_segments(group)
        except ValueError as error:
            raise ValueError(f"Unsafe dependency coordinate: {coord}") from error
        if artifact in (".", "..") or not re.fullmatch(r"[A-Za-z0-9._-]+", artifact):
            raise ValueError(f"Unsafe dependency coordinate: {coord}")
        version = _normalize_maven_version(version)
        lib_dir = _maven_dependency_dir(
            libs_dir, group_segments, artifact, version, requested_type
        )
        path = os.path.abspath(libs_dir)
        for segment in (
            ".termux-builder", "maven", *group_segments, os.path.basename(lib_dir)
        ):
            path = os.path.join(path, segment)
            if os.path.islink(path):
                raise RuntimeError(f"Refusing symlink dependency directory: {path}")
        for edge in _read_cached_edges(lib_dir):
            child, edge_exclusions, child_type = _unpack_dependency_edge(edge)
            child_group, child_artifact, _ = child.split(":", 2)
            if _is_maven_excluded(child_group, child_artifact, inherited_exclusions):
                continue
            _print(
                child,
                depth + 1,
                seen_chain | {coord},
                frozenset(inherited_exclusions | edge_exclusions),
                child_type,
            )

    if not config.dependencies:
        log.info("No dependencies declared")
        return

    for dep in config.dependencies:
        _print(dep, 0, set(), frozenset())


def _find_artifact(group_path, artifact, version, ext):
    filename = f"{artifact}-{version}.{ext}"
    failures = []
    statuses = []
    for repo in MAVEN_REPOS:
        url = f"{repo}/{group_path}/{artifact}/{version}/{filename}"
        for method in ("head", "get"):
            response = None
            try:
                response = _maven_request(
                    method,
                    url,
                    timeout=10,
                    **({"stream": True} if method == "get" else {}),
                )
                if response.status_code == 200:
                    return url
                statuses.append(response.status_code)
            except (requests.RequestException, RuntimeError) as error:
                failures.append(error)
                continue
            finally:
                if response is not None:
                    response.close()
    if failures:
        raise RuntimeError(
            f"Unable to query Maven repositories for {filename}: {failures[-1]}"
        ) from failures[-1]
    if any(status not in (404, 405) for status in statuses):
        raise RuntimeError(f"Unexpected Maven repository HTTP status for {filename}: {statuses}")
    return None


def _validate_maven_url(url):
    parsed = urlsplit(url)
    configured_origins = {urlsplit(repo).netloc for repo in MAVEN_REPOS}
    if (
        parsed.scheme != "https"
        or parsed.netloc not in configured_origins
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("URL must use a configured HTTPS Maven repository without credentials")


def _maven_request(method, url, **kwargs):
    _validate_maven_url(url)
    response = getattr(requests, method)(url, allow_redirects=False, **kwargs)
    if 300 <= response.status_code < 400:
        response.close()
        raise RuntimeError(f"Refusing Maven repository redirect for {url}")
    return response


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


def _resolve_pom_value(value, properties, project_values, resolving=None):
    match = re.search(r"\$\{([^}]+)\}", value)
    if match is None:
        return value
    if resolving is None:
        resolving = set()
    key = match.group(1)
    if key in resolving:
        raise ValueError(f"cyclic Maven property ${{{key}}}")
    if key in project_values:
        replacement = project_values[key]
    elif key in properties:
        replacement = _resolve_pom_value(
            properties[key], properties, project_values, resolving | {key}
        )
    else:
        raise ValueError(f"unresolved Maven property ${{{key}}}")
    expanded = value[:match.start()] + replacement + value[match.end():]
    return _resolve_pom_value(expanded, properties, project_values, resolving)


def _parse_pom_deps(pom_xml):
    return [edge[0] for edge in _parse_pom_edges(pom_xml)]


def _parse_pom_edges(pom_xml, bom_resolver=None):
    return _parse_pom_model(pom_xml, bom_resolver)[0]


def _parse_pom_model(pom_xml, bom_resolver=None, parent_resolver=None):
    deps = []
    try:
        root = ET.fromstring(pom_xml)
    except ET.ParseError as error:
        raise ValueError(f"Invalid Maven POM: {error}") from error

    ns = {"m": "http://maven.apache.org/POM/4.0.0"}
    if root.tag != f"{{{ns['m']}}}project":
        raise ValueError("Invalid Maven POM: root element must be <project>")
    local_properties = {}
    properties_root = root.find("m:properties", ns)
    if properties_root is not None:
        local_properties = {
            item.tag.removeprefix(f"{{{ns['m']}}}"): item.text.strip()
            for item in properties_root
            if item.text and item.text.strip()
        }
    group_node = root.find("m:groupId", ns)
    artifact_node = root.find("m:artifactId", ns)
    version_node = root.find("m:version", ns)
    project_group = group_node.text.strip() if group_node is not None and group_node.text else ""
    project_artifact = artifact_node.text.strip() if artifact_node is not None and artifact_node.text else ""
    project_version = version_node.text.strip() if version_node is not None and version_node.text else ""
    project_values = {}
    if project_group and project_artifact and project_version:
        project_values = {
            "project.groupId": project_group,
            "pom.groupId": project_group,
            "project.artifactId": project_artifact,
            "pom.artifactId": project_artifact,
            "project.version": project_version,
            "pom.version": project_version,
        }
    parent_model = {}
    parent_node = root.find("m:parent", ns)
    if parent_node is not None:
        if parent_resolver is None:
            raise ValueError("Maven parent POM inheritance requires repository resolution")
        parent_values = {}
        for key in ("groupId", "artifactId", "version"):
            node = parent_node.find(f"m:{key}", ns)
            value = node.text.strip() if node is not None and node.text else ""
            if not value:
                raise ValueError(f"Maven parent POM requires explicit {key}")
            parent_values[key] = _resolve_pom_value(value, local_properties, project_values)
        _, parent_management, parent_model = parent_resolver(
            parent_values["groupId"], parent_values["artifactId"], parent_values["version"]
        )
    else:
        parent_management = {}

    properties = {**parent_model.get("properties", {}), **local_properties}
    project_group = project_group or parent_model.get("group", "")
    project_artifact = project_artifact or parent_model.get("artifact", "")
    project_version = project_version or parent_model.get("version", "")
    if project_group and project_artifact and project_version:
        project_values = {
            "project.groupId": project_group,
            "pom.groupId": project_group,
            "project.artifactId": project_artifact,
            "pom.artifactId": project_artifact,
            "project.version": project_version,
            "pom.version": project_version,
        }
    if parent_model:
        project_values.update({
            "project.parent.groupId": parent_model.get("group", ""),
            "project.parent.artifactId": parent_model.get("artifact", ""),
            "project.parent.version": parent_model.get("version", ""),
        })
    properties = {
        name: _resolve_pom_value(value, properties, project_values)
        for name, value in properties.items()
    }
    imported_management = {}
    local_management = {}

    def dependency_exclusions(dependency):
        exclusions = set()
        for exclusion in dependency.findall("m:exclusions/m:exclusion", ns):
            group_node = exclusion.find("m:groupId", ns)
            artifact_node = exclusion.find("m:artifactId", ns)
            group = group_node.text.strip() if group_node is not None and group_node.text else ""
            artifact = artifact_node.text.strip() if artifact_node is not None and artifact_node.text else ""
            if not group or not artifact:
                raise ValueError("Maven exclusions require explicit groupId and artifactId")
            try:
                group = _resolve_pom_value(group, properties, project_values)
                artifact = _resolve_pom_value(artifact, properties, project_values)
            except ValueError as error:
                raise ValueError(f"Unable to resolve Maven exclusion: {error}") from error
            if (group != "*" and not re.fullmatch(r"[A-Za-z0-9._-]+", group)) or (
                artifact != "*" and not re.fullmatch(r"[A-Za-z0-9._-]+", artifact)
            ):
                raise ValueError(f"Invalid Maven exclusion: {group}:{artifact}")
            exclusions.add((group, artifact))
        return frozenset(exclusions)

    for managed in root.findall("m:dependencyManagement/m:dependencies/m:dependency", ns):
        g = managed.find("m:groupId", ns)
        a = managed.find("m:artifactId", ns)
        v = managed.find("m:version", ns)
        group = g.text.strip() if g is not None and g.text else ""
        artifact = a.text.strip() if a is not None and a.text else ""
        version = v.text.strip() if v is not None and v.text else ""
        if not group or not artifact or not version:
            raise ValueError("Maven dependencyManagement entries require explicit groupId, artifactId and version")
        try:
            group = _resolve_pom_value(group, properties, project_values)
            artifact = _resolve_pom_value(artifact, properties, project_values)
            version = _resolve_pom_value(version, properties, project_values)
        except ValueError as error:
            raise ValueError(f"Unable to resolve Maven dependencyManagement entry: {error}") from error
        scope = managed.find("m:scope", ns)
        scope_value = scope.text.strip() if scope is not None and scope.text else "compile"
        try:
            scope_value = _resolve_pom_value(scope_value, properties, project_values)
        except ValueError as error:
            raise ValueError(f"Unable to resolve Maven dependencyManagement scope: {error}") from error
        dependency_type = managed.find("m:type", ns)
        type_value = None
        if dependency_type is not None and dependency_type.text:
            type_value = _resolve_pom_value(
                dependency_type.text.strip(), properties, project_values
            )
        if type_value == "pom" and scope_value == "import":
            if bom_resolver is None:
                raise ValueError("Maven BOM imports require repository resolution")
            imported = bom_resolver(group, artifact, version)
            for key, value in imported.items():
                imported_management.setdefault(key, value)
            continue
        if type_value not in (None, "jar", "aar"):
            raise ValueError(f"Unsupported Maven dependencyManagement type: {type_value}")
        if scope_value not in ("compile", "runtime", "test", "provided"):
            raise ValueError(f"Unsupported Maven dependencyManagement scope: {scope_value}")
        classifier = managed.find("m:classifier", ns)
        if classifier is not None and classifier.text and classifier.text.strip():
            raise ValueError("Maven dependencyManagement classifiers are not supported")
        key = f"{group}:{artifact}"
        existing = local_management.get(key)
        if existing is not None and existing[0] != version:
            raise ValueError(f"Conflicting Maven dependencyManagement versions for {key}")
        local_management[key] = (
            version, scope_value, dependency_exclusions(managed), type_value
        )

    managed = {**parent_management, **imported_management, **local_management}

    for dep in root.findall("m:dependencies/m:dependency", ns):
        g = dep.find("m:groupId", ns)
        a = dep.find("m:artifactId", ns)
        v = dep.find("m:version", ns)
        group = g.text.strip() if g is not None and g.text else ""
        artifact = a.text.strip() if a is not None and a.text else ""
        version = v.text.strip() if v is not None and v.text else ""
        if not group or not artifact:
            raise ValueError("Maven dependency requires explicit groupId and artifactId")
        try:
            group = _resolve_pom_value(group, properties, project_values)
            artifact = _resolve_pom_value(artifact, properties, project_values)
        except ValueError as error:
            raise ValueError(
                f"Unable to resolve Maven dependency coordinates: {error}"
            ) from error
        key = f"{group}:{artifact}"
        managed_version, managed_scope, managed_excluded, managed_type = managed.get(
            key, ("", "compile", frozenset(), None)
        )
        scope = dep.find("m:scope", ns)
        scope_value = scope.text.strip() if scope is not None and scope.text else managed_scope
        try:
            scope_value = _resolve_pom_value(scope_value, properties, project_values)
        except ValueError as error:
            raise ValueError(f"Unable to resolve Maven dependency scope: {error}") from error
        if scope_value in ("test", "provided"):
            continue
        if scope_value not in ("compile", "runtime"):
            raise ValueError(f"Unsupported Maven dependency scope: {scope_value}")
        optional = dep.find("m:optional", ns)
        if optional is not None and optional.text and optional.text.strip().lower() == "true":
            continue
        classifier = dep.find("m:classifier", ns)
        if classifier is not None and classifier.text and classifier.text.strip():
            raise ValueError("Maven dependency classifiers are not supported")
        dependency_type = dep.find("m:type", ns)
        if dependency_type is not None and dependency_type.text:
            try:
                dependency_type = _resolve_pom_value(
                    dependency_type.text.strip(), properties, project_values
                )
            except ValueError as error:
                raise ValueError(f"Unable to resolve Maven dependency type: {error}") from error
            if dependency_type not in ("jar", "aar"):
                raise ValueError(f"Unsupported Maven dependency type: {dependency_type}")
        else:
            dependency_type = managed_type
        if version:
            try:
                version = _resolve_pom_value(version, properties, project_values)
            except ValueError as error:
                raise ValueError(
                    f"Dependency {group}:{artifact} requires unsupported Maven version resolution: {error}"
                ) from error
        else:
            version = managed_version
        if not version or "$" in version:
            raise ValueError(
                f"Dependency {group}:{artifact} requires unsupported Maven version resolution"
            )
        exclusions = managed_excluded | dependency_exclusions(dep)
        deps.append((f"{group}:{artifact}:{version}", exclusions, dependency_type))

    effective_dependencies = {}
    for edge in parent_model.get("dependencies", []):
        coordinate, exclusions, dependency_type = _unpack_dependency_edge(edge)
        group, artifact, version = coordinate.split(":", 2)
        key = f"{group}:{artifact}"
        managed_version, managed_scope, managed_excluded, managed_type = managed.get(
            key, ("", "compile", frozenset(), None)
        )
        if managed_scope in ("test", "provided"):
            continue
        if managed_version:
            version = managed_version
        effective_dependencies[key] = (
            f"{group}:{artifact}:{version}",
            frozenset(exclusions | managed_excluded),
            dependency_type or managed_type,
        )
    for coordinate, exclusions, dependency_type in deps:
        group, artifact, _ = coordinate.split(":", 2)
        key = f"{group}:{artifact}"
        existing = effective_dependencies.get(key)
        if existing is not None and existing[2] not in (None, dependency_type) and dependency_type is not None:
            raise ValueError(f"Multiple Maven dependency types for {key} are not supported")
        effective_dependencies[key] = (coordinate, exclusions, dependency_type)

    model = {
        "group": project_group,
        "artifact": project_artifact,
        "version": project_version,
        "properties": properties,
        "dependencies": list(effective_dependencies.values()),
    }
    return list(effective_dependencies.values()), managed, model


def _download(url, dest):
    response = _maven_request("get", url, timeout=60, stream=True)
    temporary_path = None
    try:
        response.raise_for_status()
        if response.status_code != 200:
            raise requests.HTTPError(f"Unexpected artifact response status {response.status_code}")
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=os.path.basename(dest) + ".",
            suffix=".tmp",
            dir=os.path.dirname(os.path.abspath(dest)),
        )
        with os.fdopen(descriptor, "wb") as output:
            for chunk in response.iter_content(8192):
                if chunk:
                    output.write(chunk)
        os.replace(temporary_path, dest)
    finally:
        response.close()
        if temporary_path and os.path.exists(temporary_path):
            os.remove(temporary_path)


def _verify_checksum(artifact_url, artifact_path, coord):
    """Maven Central/Google publish .sha1 alongside every artifact —
    verify it so a compromised/corrupted mirror response gets caught
    before the jar/aar lands in the build classpath."""
    response = None
    checksum_text = ""
    try:
        response = _maven_request("get", artifact_url + ".sha1", timeout=15)
        if response.status_code == 404:
            log.warning("No .sha1 available for %s — skipping checksum verification", coord)
            return
        response.raise_for_status()
        if response.status_code != 200:
            raise requests.HTTPError(f"Unexpected checksum response status {response.status_code}")
        checksum_text = response.text
    except requests.RequestException as error:
        raise RuntimeError(f"Failed to fetch checksum for {coord}: {error}") from error
    finally:
        if response is not None:
            response.close()

    fields = checksum_text.strip().split()
    if not fields or not re.fullmatch(r"[a-fA-F0-9]{40}", fields[0]):
        raise RuntimeError(f"Invalid SHA-1 checksum response for {coord}")
    expected = fields[0].lower()
    h = hashlib.sha1()
    with open(artifact_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    actual = h.hexdigest()

    if actual != expected:
        os.remove(artifact_path)
        raise RuntimeError(f"Checksum mismatch for {coord}: expected {expected}, got {actual}")
    return expected


def _extract_aar(aar_path, out_dir):
    log.debug("Extracting AAR: %s", aar_path)
    out_dir = os.path.abspath(out_dir)
    parent_dir = os.path.dirname(out_dir)
    with zipfile.ZipFile(aar_path) as z:
        members = z.infolist()
        if len(members) > MAX_AAR_ENTRIES:
            raise RuntimeError(
                f"AAR contains {len(members)} entries, exceeding the {MAX_AAR_ENTRIES} entry limit"
            )
        expanded_size = sum(member.file_size for member in members if not member.is_dir())
        if expanded_size > MAX_AAR_UNCOMPRESSED_BYTES:
            raise RuntimeError(
                f"AAR expanded size {expanded_size} exceeds the {MAX_AAR_UNCOMPRESSED_BYTES}-byte expanded size limit"
            )

        tmp_dir = tempfile.mkdtemp(
            prefix=f".aar-extract-{os.getpid()}-", dir=parent_dir
        )
        try:
            seen = set()
            for member in members:
                member_path = os.path.abspath(os.path.join(tmp_dir, member.filename))
                if os.path.commonpath((tmp_dir, member_path)) != tmp_dir:
                    raise RuntimeError(f"Unsafe AAR entry: {member.filename}")
                relative_path = os.path.relpath(member_path, tmp_dir)
                if relative_path == "." or relative_path in seen:
                    raise RuntimeError(f"Duplicate or invalid AAR entry: {member.filename}")
                seen.add(relative_path)
                # Unix symlink mode is stored in the high 16 external-attribute bits.
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise RuntimeError(f"Unsafe AAR entry: symlink {member.filename}")
                z.extract(member, tmp_dir)

            if not os.path.isfile(os.path.join(tmp_dir, "AndroidManifest.xml")):
                raise RuntimeError("AAR is missing required AndroidManifest.xml")
            classes_jar = os.path.join(tmp_dir, "classes.jar")
            if os.path.isfile(classes_jar):
                base = os.path.basename(out_dir)
                os.rename(classes_jar, os.path.join(tmp_dir, f"{base}.jar"))
            if os.path.islink(out_dir):
                raise RuntimeError(f"Refusing to replace symlink AAR output: {out_dir}")
            if os.path.isdir(out_dir):
                shutil.rmtree(out_dir)
            elif os.path.lexists(out_dir):
                raise RuntimeError(f"Refusing to replace non-directory AAR output: {out_dir}")
            os.rename(tmp_dir, out_dir)
            tmp_dir = None
        finally:
            if tmp_dir is not None:
                shutil.rmtree(tmp_dir, ignore_errors=True)


def _cleanup_stale_aar_staging(libs_dir):
    maven_root = os.path.join(libs_dir, ".termux-builder", "maven")
    if any(os.path.islink(path) for path in (
        libs_dir,
        os.path.join(libs_dir, ".termux-builder"),
        maven_root,
    )) or not os.path.isdir(maven_root):
        return

    for root, directories, _ in os.walk(maven_root, followlinks=False):
        for name in tuple(directories):
            if not name.startswith(".aar-extract-"):
                continue
            directories.remove(name)
            staging_dir = os.path.join(root, name)
            match = re.fullmatch(r"\.aar-extract-(\d+)-[A-Za-z0-9_]+", name)
            if not match or os.path.islink(staging_dir):
                continue
            try:
                os.kill(int(match.group(1)), 0)
            except ProcessLookupError:
                try:
                    shutil.rmtree(staging_dir)
                except OSError as error:
                    log.warning("Could not remove stale AAR staging directory %s: %s", staging_dir, error)
            except (PermissionError, OSError):
                continue


def _save_transitive(lib_dir, deps):
    normalized = [_unpack_dependency_edge(edge) for edge in deps]
    coordinates = [coordinate for coordinate, _, _ in normalized]
    _write_dependency_metadata(os.path.join(lib_dir, ".transitive"), "\n".join(coordinates))
    metadata = [
        {
            "coordinate": coordinate,
            "exclusions": [list(item) for item in sorted(exclusions)],
            "type": dependency_type,
        }
        for coordinate, exclusions, dependency_type in normalized
    ]
    _write_dependency_metadata(
        os.path.join(lib_dir, ".termux-builder-transitive.json"),
        json.dumps(metadata, sort_keys=True, separators=(",", ":")),
    )


def _mark_dependency(lib_dir, coordinate):
    marker = os.path.join(lib_dir, ".termux-builder-coordinate")
    _write_dependency_metadata(marker, coordinate)


def _write_dependency_metadata(path, content):
    directory = os.path.dirname(path)
    descriptor, temp_path = tempfile.mkstemp(prefix=".termux-builder-metadata.", dir=directory)
    try:
        with os.fdopen(descriptor, "w") as file:
            file.write(content)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def _read_cached_transitive(lib_dir):
    path = os.path.join(lib_dir, ".transitive")
    if os.path.islink(path):
        raise RuntimeError(f"Refusing symlink dependency metadata: {path}")
    if not os.path.isfile(path):
        return []
    with open(path) as f:
        return [l.strip() for l in f if l.strip()]


def _read_cached_edges(lib_dir):
    path = os.path.join(lib_dir, ".termux-builder-transitive.json")
    if os.path.islink(path):
        raise RuntimeError(f"Refusing symlink dependency metadata: {path}")
    if not os.path.isfile(path):
        return [
            (coordinate, frozenset(), None)
            for coordinate in _read_cached_transitive(lib_dir)
        ]
    try:
        with open(path) as file:
            metadata = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Invalid cached Maven dependency metadata: {path}: {error}") from error
    if not isinstance(metadata, list):
        raise RuntimeError(f"Invalid cached Maven dependency metadata: {path}")
    edges = []
    for entry in metadata:
        if not isinstance(entry, dict) or not isinstance(entry.get("coordinate"), str):
            raise RuntimeError(f"Invalid cached Maven dependency metadata: {path}")
        exclusions = entry.get("exclusions")
        dependency_type = entry.get("type")
        if not isinstance(exclusions, list) or any(
            not isinstance(item, list)
            or len(item) != 2
            or any(not isinstance(value, str) for value in item)
            for item in exclusions
        ) or dependency_type not in (None, "jar", "aar"):
            raise RuntimeError(f"Invalid cached Maven dependency metadata: {path}")
        edges.append((
            entry["coordinate"],
            frozenset(tuple(item) for item in exclusions),
            dependency_type,
        ))
    return edges
