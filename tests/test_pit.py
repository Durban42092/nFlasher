"""Tests for nflasher.pit — PIT binary parser."""

import struct
import pytest
from nflasher.pit import (
    parse_pit, serialize_pit, pit_summary,
    PITFile, PITEntry,
    PIT_MAGIC, PIT_HEADER_SIZE, PIT_ENTRY_V1_SIZE, PIT_ENTRY_V2_SIZE,
    PITParseError,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def cstr(s: str, n: int) -> bytes:
    b = s.encode()[:n - 1]
    return b + b'\x00' * (n - len(b))


def make_header(entry_count: int) -> bytes:
    return struct.pack('<IIIIIII', PIT_MAGIC, entry_count, 0, 0, 0, 0, 0)


def make_entry_v1(
    bin_type=1, dev_type=3, ident=0, attrs=4, upd=0,
    bsz=512, bcnt=4096, foff=0, fsz=0x200000,
    pname='SYSTEM', fname='AP.tar.md5', fota=''
) -> bytes:
    e  = struct.pack('<IIIIIII', bin_type, dev_type, ident, attrs, upd, bsz, bcnt)
    e += struct.pack('<II', foff, fsz)
    e += cstr(pname, 32) + cstr(fname, 32) + cstr(fota, 32)
    assert len(e) == PIT_ENTRY_V1_SIZE
    return e


def make_entry_v2(
    bin_type=1, dev_type=3, ident=0, attrs=4, upd=0,
    bsz=512, bcnt=4096, fsz=0x200000, unk1=0, unk2=0,
    pname='SYSTEM', fname='AP.tar.md5', fota=''
) -> bytes:
    e  = struct.pack('<IIIIIII', bin_type, dev_type, ident, attrs, upd, bsz, bcnt)
    e += struct.pack('<III', fsz, unk1, unk2)          # 12 bytes (v2 has 2 unknowns)
    e += cstr(pname, 32) + cstr(fname, 32) + cstr(fota, 32)
    assert len(e) == PIT_ENTRY_V2_SIZE
    return e


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestPITMagic:
    def test_bad_magic_raises(self):
        data = struct.pack('<IIIIIII', 0xDEADBEEF, 0, 0, 0, 0, 0, 0)
        with pytest.raises(PITParseError, match="Invalid PIT magic"):
            parse_pit(data)

    def test_too_short_raises(self):
        with pytest.raises(PITParseError, match="too short"):
            parse_pit(b'\x00' * 10)

    def test_valid_header_no_entries(self):
        data = make_header(0)
        pit = parse_pit(data)
        assert pit.entry_count == 0
        assert pit.version == 1


class TestPITv1:
    def _make(self, entries=1):
        data = make_header(entries)
        for i in range(entries):
            data += make_entry_v1(pname=f'PART{i}', fname=f'FILE{i}.tar.md5')
        return data

    def test_single_entry(self):
        pit = parse_pit(self._make(1))
        assert pit.version == 1
        assert pit.entry_count == 1
        assert pit.entries[0].partition_name == 'PART0'
        assert pit.entries[0].flash_filename == 'FILE0.tar.md5'

    def test_multiple_entries(self):
        pit = parse_pit(self._make(5))
        assert pit.entry_count == 5
        for i, e in enumerate(pit.entries):
            assert e.partition_name == f'PART{i}'

    def test_size_bytes(self):
        e_data = make_entry_v1(bsz=512, bcnt=8192)
        pit = parse_pit(make_header(1) + e_data)
        assert pit.entries[0].size_bytes == 512 * 8192

    def test_type_names(self):
        e_data = make_entry_v1(bin_type=1, dev_type=3)
        pit = parse_pit(make_header(1) + e_data)
        assert pit.entries[0].binary_type_name == 'PDA'
        assert pit.entries[0].device_type_name == 'EMMC'

    def test_truncated_entry_raises(self):
        data = make_header(2) + make_entry_v1()  # only 1 entry, claims 2
        with pytest.raises(PITParseError, match="truncated"):
            parse_pit(data)


class TestPITv2:
    def _make(self, entries=1):
        data = make_header(entries)
        for i in range(entries):
            data += make_entry_v2(pname=f'PART{i}')
        return data

    def test_version_detection(self):
        pit = parse_pit(self._make(1))
        assert pit.version == 2

    def test_entry_count(self):
        pit = parse_pit(self._make(4))
        assert pit.entry_count == 4


class TestRoundTrip:
    def test_v1_roundtrip(self):
        raw = make_header(2) + make_entry_v1(pname='SYSTEM') + make_entry_v1(pname='MODEM', bin_type=2)
        pit = parse_pit(raw)
        raw2 = serialize_pit(pit)
        pit2 = parse_pit(raw2)
        assert pit2.entry_count == 2
        assert pit2.entries[0].partition_name == 'SYSTEM'
        assert pit2.entries[1].partition_name == 'MODEM'
        assert pit2.entries[1].binary_type_name == 'MODEM'

    def test_v2_roundtrip(self):
        raw = make_header(1) + make_entry_v2(pname='BOOT', fsz=0x400000)
        pit = parse_pit(raw)
        pit2 = parse_pit(serialize_pit(pit))
        assert pit2.entries[0].file_size == 0x400000
        assert pit2.entries[0].partition_name == 'BOOT'


class TestPITSummary:
    def test_summary_contains_partition_name(self):
        raw = make_header(1) + make_entry_v1(pname='USERDATA')
        pit = parse_pit(raw)
        s = pit_summary(pit)
        assert 'USERDATA' in s
        assert 'EMMC' in s

    def test_summary_has_header_row(self):
        raw = make_header(0)
        pit = parse_pit(raw)
        s = pit_summary(pit)
        assert 'Partition Count' in s


class TestEdgeCases:
    def test_null_padded_partition_name(self):
        e = make_entry_v1(pname='AB')  # 2 chars + many nulls
        pit = parse_pit(make_header(1) + e)
        assert pit.entries[0].partition_name == 'AB'

    def test_full_32_char_name_no_null(self):
        # Partition name exactly fills 32 bytes — should not crash
        long_name = 'A' * 31  # leaves 1 byte for null
        e = make_entry_v1(pname=long_name)
        pit = parse_pit(make_header(1) + e)
        assert pit.entries[0].partition_name == long_name

    def test_unknown_binary_type_name(self):
        e = make_entry_v1(bin_type=99)
        pit = parse_pit(make_header(1) + e)
        assert 'UNKNOWN' in pit.entries[0].binary_type_name
