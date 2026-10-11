import os
import struct
import zipfile
import zlib


def check_zip_directory(source, max_entries, label):
    source.seek(0, os.SEEK_END)
    size = source.tell()
    source.seek(max(0, size - 65557))
    tail = source.read()
    # Match ZipFile's no-comment fast path before searching a comment tail.
    if len(tail) >= 22 and tail[-22:-18] == b"PK\x05\x06" and tail[-2:] == b"\x00\x00":
        end = len(tail) - 22
    else:
        end = tail.rfind(b"PK\x05\x06")
    if end < 0 or end + 22 > len(tail):
        raise RuntimeError(f"{label}: invalid ZIP end record")
    record = struct.unpack_from("<4s4H2IH", tail, end)
    if end + 22 + record[7] != len(tail):
        raise RuntimeError(f"{label}: ambiguous or inconsistent ZIP end record")
    end_offset = size - len(tail) + end
    if end_offset >= 20:
        source.seek(end_offset - 20)
        if source.read(4) == b"PK\x06\x07":
            raise RuntimeError(f"{label}: unsupported ZIP64 directory")
    if (record[1] or record[2] or record[3] != record[4] or
            record[4] == 65535 or record[4] > max_entries or
            record[5] > 16 * 1024 * 1024 or
            record[6] + record[5] != end_offset):
        raise RuntimeError(f"{label}: directory limits or unsupported ZIP64/multipart format")
    source.seek(record[6])
    directory_end = record[6] + record[5]
    count = 0
    while source.tell() < directory_end:
        header = source.read(46)
        if len(header) != 46 or header[:4] != b"PK\x01\x02":
            raise RuntimeError(f"{label}: invalid ZIP directory entry")
        fields = struct.unpack("<4s6H3I5H2I", header)
        source.seek(sum(fields[10:13]), os.SEEK_CUR)
        count += 1
        if count > max_entries or source.tell() > directory_end:
            raise RuntimeError(f"{label}: directory limits exceeded")
    if count != record[4]:
        raise RuntimeError(f"{label}: ZIP entry count mismatch")


def verify_zip_payloads(source, archive, max_expanded_bytes, label):
    entries = archive.infolist()
    if len({entry.filename for entry in entries}) != len(entries):
        raise RuntimeError(f"{label}: duplicate ZIP entries")
    if any('\x00' in entry.orig_filename or entry.filename != entry.orig_filename for entry in entries):
        raise RuntimeError(f"{label}: ambiguous ZIP entry names")
    if any(entry.flag_bits & 0x41 or entry.compress_type not in
           (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED) for entry in entries):
        raise RuntimeError(f"{label}: encrypted or unsupported ZIP entries")
    if sum(entry.file_size for entry in entries) > max_expanded_bytes:
        raise RuntimeError(f"{label}: archive exceeds expanded-size limits")
    total = 0
    for entry in entries:
        # Let ZipFile check names, local headers and overlapping entries.
        with archive.open(entry):
            pass
        source.seek(entry.header_offset)
        header = source.read(30)
        fields = struct.unpack("<4s5H3I2H", header)
        source.seek(fields[9] + fields[10], os.SEEK_CUR)
        remaining = entry.compress_size
        decoder = zlib.decompressobj(-15) if entry.compress_type == zipfile.ZIP_DEFLATED else None
        size = checksum = 0
        while True:
            if decoder and decoder.unconsumed_tail:
                data = decoder.unconsumed_tail
            elif remaining:
                data = source.read(min(65536, remaining))
                if not data:
                    raise RuntimeError(f"{label}: truncated ZIP payload")
                remaining -= len(data)
            elif decoder and not decoder.eof:
                data = b""
            else:
                break
            content = decoder.decompress(data, 65536) if decoder else data
            size += len(content)
            total += len(content)
            if size > entry.file_size or total > max_expanded_bytes:
                raise RuntimeError(f"{label}: actual ZIP payload exceeds declared size or limits")
            checksum = zlib.crc32(content, checksum)
            if decoder:
                if decoder.eof and (decoder.unused_data or remaining):
                    raise RuntimeError(f"{label}: trailing data in ZIP payload")
                if not data and not content and not decoder.eof:
                    raise RuntimeError(f"{label}: incomplete ZIP compression stream")
        if size != entry.file_size or checksum != entry.CRC:
            raise RuntimeError(f"{label}: ZIP size or CRC mismatch")
