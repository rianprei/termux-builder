"""Reject unsafe ZIP mutations of an AAB produced by the real build pipeline."""
import argparse
from pathlib import Path
import shutil
import tempfile
import warnings
import zipfile

from builder.aab import _verify_aab

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('aab', help='Previously built and verified AAB')
args = parser.parse_args()
source = Path(args.aab).resolve(strict=True)
with tempfile.TemporaryDirectory(prefix='termux-builder-aab-negative-') as temp:
    for entry in ('BundleConfig.pb', '../escape', '/absolute', 'base//escape', 'base\\escape'):
        altered = Path(temp) / 'altered.aab'
        shutil.copyfile(source, altered)
        with zipfile.ZipFile(altered, 'a') as archive:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                archive.writestr(entry, b'negative fixture')
        try:
            _verify_aab(str(altered))
        except RuntimeError as error:
            expected = 'duplicate' if entry == 'BundleConfig.pb' else 'unsafe'
            if expected not in str(error):
                raise RuntimeError('Expected archive gate rejection before external verification') from error
        else:
            raise RuntimeError('Unsafe AAB mutation was accepted')
    empty_manifest = Path(temp) / 'empty-manifest.aab'
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(empty_manifest, 'w') as altered:
        for member in original.infolist():
            data = b'' if member.filename == 'base/manifest/AndroidManifest.xml' else original.read(member)
            altered.writestr(member, data)
    try:
        _verify_aab(str(empty_manifest))
    except RuntimeError as error:
        if 'empty base manifest' not in str(error):
            raise RuntimeError('Expected empty manifest rejection before signature verification') from error
    else:
        raise RuntimeError('Empty AAB manifest was accepted')
print('REAL AAB ARCHIVE: duplicate/unsafe entries and empty base manifest rejected')
