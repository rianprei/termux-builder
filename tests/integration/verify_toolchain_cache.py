"""Reproduce forged ZIP metadata using a class compiled by the real JDK."""
import io
import struct
import subprocess
import tempfile
import zipfile
import zlib
from pathlib import Path

from builder.kapt import _validate_toolchain_jar


def verify():
    with tempfile.TemporaryDirectory(prefix='toolchain-cache-fixture-') as temp:
        root = Path(temp)
        source = root / 'Test.java'
        source.write_text('public class Test { public static int answer() { return 42; } }')
        subprocess.run(['javac', '-d', str(root), str(source)], check=True)
        content = (root / 'Test.class').read_bytes()
        assert len(content) > 20 and content[:4] == b'\xca\xfe\xba\xbe'
        for compression in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            output = io.BytesIO()
            with zipfile.ZipFile(output, 'w', compression=compression) as archive:
                archive.writestr('Test.class', content)
            original = root / 'valid.jar'
            original.write_bytes(output.getvalue())
            _validate_toolchain_jar(original, 'Test.class', 'JDK fixture')
            subprocess.run(['javap', '-classpath', str(original), 'Test'], check=True,
                           stdout=subprocess.DEVNULL)
            for truncated in (False, True):
                output = io.BytesIO()
                with zipfile.ZipFile(output, 'w', compression=compression) as archive:
                    archive.writestr('Test.class', content[:len(content) // 2] if truncated else content)
                data = bytearray(output.getvalue())
                central = data.index(b'PK\x01\x02')
                prefix = content[:10]
                struct.pack_into('<I', data, 14, zlib.crc32(prefix))
                struct.pack_into('<I', data, 22, len(prefix))
                struct.pack_into('<I', data, central + 16, zlib.crc32(prefix))
                struct.pack_into('<I', data, central + 24, len(prefix))
                damaged = root / 'damaged.jar'
                damaged.write_bytes(data)
                with zipfile.ZipFile(damaged) as archive:
                    assert archive.testzip() is None, 'fixture must reproduce the testzip bypass'
                if truncated:
                    result = subprocess.run(['javap', '-classpath', str(damaged), 'Test'],
                                            capture_output=True, text=True)
                    assert result.returncode != 0, 'real JDK unexpectedly accepted the truncated class'
                try:
                    _validate_toolchain_jar(damaged, 'Test.class', 'JDK fixture')
                except RuntimeError as error:
                    assert 'actual ZIP payload' in str(error), str(error)
                else:
                    raise AssertionError('forged cache payload was accepted')
                assert damaged.read_bytes() == data, 'validation modified the cached artifact'
                print(f'REJECTED forged cache: compression={compression}, truncated_class={truncated}', flush=True)
        print('Real JDK ZIP/cache regression passed: two valid JARs and four rejected mutations', flush=True)


if __name__ == '__main__':
    verify()
