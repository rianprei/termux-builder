"""Measure ZIP metadata-only inspection versus inspection plus CRC, excluding fixture creation."""
import argparse
import hashlib
import json
import platform
import random
import resource
import statistics
import subprocess
import tempfile
import time
import tracemalloc
import zipfile
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--samples', type=int, default=9)
args = parser.parse_args()
if args.samples < 3:
    parser.error('--samples must be at least 3')
results = []
with tempfile.TemporaryDirectory(prefix='termux-builder-crc-bench-') as temp:
    for mib in (1, 16, 64):
        archive_path = Path(temp) / 'fixture.aab'
        generator = random.Random(0)
        with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name in ('BundleConfig.pb', 'base/manifest/AndroidManifest.xml', 'base/resources.pb'):
                member = zipfile.ZipInfo(name)
                member.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(member, b'synthetic metadata')
            member = zipfile.ZipInfo('base/assets/payload.bin')
            member.compress_type = zipfile.ZIP_DEFLATED
            with archive.open(member, 'w') as payload:
                for _ in range(mib):
                    payload.write(generator.randbytes(1024 * 1024))
        def inspect(crc):
            started = time.perf_counter()
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                if len(names) != len(set(names)):
                    raise RuntimeError('Invalid benchmark fixture')
                if crc and archive.testzip() is not None:
                    raise RuntimeError('Corrupted benchmark fixture')
            return time.perf_counter() - started
        inspect(False)
        inspect(True)
        before, after = [], []
        for index in range(args.samples):
            order = (False, True) if index % 2 == 0 else (True, False)
            for crc in order:
                (after if crc else before).append(inspect(crc))
        tracemalloc.start()
        inspect(True)
        _, traced_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        with archive_path.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        results.append({'payload_mib': mib, 'zip_bytes': archive_path.stat().st_size,
            'sha256': digest, 'crc_python_allocation_peak_bytes': traced_peak,
            'metadata_seconds': before, 'metadata_crc_seconds': after,
            'metadata_median_seconds': statistics.median(before),
            'metadata_crc_median_seconds': statistics.median(after)})
print(json.dumps({'scope': 'synthetic ZIP inspection, warm filesystem cache; excludes fixture generation and external validators',
    'python': platform.python_version(), 'platform': platform.platform(),
    'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
    'samples': args.samples, 'process_peak_rss_kib_including_fixture_creation': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    'results': results}, indent=2))
