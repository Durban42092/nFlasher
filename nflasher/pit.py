"""
PIT (Partition Information Table) parser for Samsung devices.
Supports PIT v1 and v2 formats as used in Odin/Heimdall.
"""

import struct
from dataclasses import dataclass, field
from enum import IntEnum


class PITBinaryType(IntEnum):
    PHONE_BOOT = 0
    PDA        = 1
    MODEM      = 2
    CSC        = 3
    USERDATA   = 4
    UNKNOWN    = 255


class PITDeviceType(IntEnum):
    ONENAND  = 0
    NAND     = 1
    MOVINAND = 2
    EMMC     = 3
    SPI      = 4
    IDE      = 5
    NAND_X16 = 6
    NAND_ONLY = 7
    UNKNOWN  = 255


class PITAttributeType(IntEnum):
    WRITE_ONCE = 0
    STL        = 1
    BMLWRITE   = 2
    CRC        = 0x100
    UNKNOWN    = 0xFFFF


class PITFilesystemType(IntEnum):
    NONE     = 0
    MOVINAND = 1
    YAFFS2   = 2
    EXT4     = 4
    FAT      = 8
    UNKNOWN  = 0xFF


PIT_MAGIC         = 0x12349876
PIT_ENTRY_V1_SIZE = 132
PIT_ENTRY_V2_SIZE = 136
PIT_HEADER_SIZE   = 28


@dataclass
class PITEntry:
    binary_type:    int = 0
    device_type:    int = 0
    identifier:     int = 0
    attributes:     int = 0
    update_attrib:  int = 0
    block_size:     int = 0
    block_count:    int = 0
    file_offset:    int = 0  # v1 only
    file_size:      int = 0
    partition_name: str = ""
    flash_filename: str = ""
    fota_filename:  str = ""
    # v2 extras (+8 bytes = 136 total)
    unknown1:       int = 0
    unknown2:       int = 0

    @property
    def size_bytes(self) -> int:
        return self.block_size * self.block_count

    @property
    def binary_type_name(self) -> str:
        try:
            return PITBinaryType(self.binary_type).name
        except ValueError:
            return f"UNKNOWN({self.binary_type})"

    @property
    def device_type_name(self) -> str:
        try:
            return PITDeviceType(self.device_type).name
        except ValueError:
            return f"UNKNOWN({self.device_type})"

    @property
    def filesystem_type_name(self) -> str:
        try:
            return PITFilesystemType(self.attributes & 0xFF).name
        except ValueError:
            return f"UNKNOWN({self.attributes & 0xFF})"


@dataclass
class PITFile:
    version:   int              = 1
    gang_name: str              = ""
    project:   str              = ""
    entries:   list[PITEntry]   = field(default_factory=list)

    @property
    def entry_count(self) -> int:
        return len(self.entries)


class PITParseError(Exception):
    pass


def parse_pit(data: bytes) -> PITFile:
    """Parse raw PIT binary data into a PITFile object."""
    if len(data) < PIT_HEADER_SIZE:
        raise PITParseError(f"Data too short: {len(data)} bytes")

    magic, entry_count, *_ = struct.unpack_from("<IIIIIII", data, 0)

    if magic != PIT_MAGIC:
        raise PITParseError(f"Invalid PIT magic: 0x{magic:08X}, expected 0x{PIT_MAGIC:08X}")

    pit = PITFile()

    remaining = len(data) - PIT_HEADER_SIZE
    if entry_count > 0:
        if remaining % PIT_ENTRY_V2_SIZE == 0 and remaining // PIT_ENTRY_V2_SIZE == entry_count:
            pit.version = 2
        else:
            pit.version = 1

    entry_size = PIT_ENTRY_V2_SIZE if pit.version == 2 else PIT_ENTRY_V1_SIZE
    offset = PIT_HEADER_SIZE

    for i in range(entry_count):
        if offset + entry_size > len(data):
            raise PITParseError(f"Entry {i} truncated at offset {offset}")
        entry = _parse_entry(data, offset, pit.version)
        pit.entries.append(entry)
        offset += entry_size

    return pit


def _parse_entry(data: bytes, offset: int, version: int) -> PITEntry:
    e = PITEntry()

    e.binary_type, e.device_type, e.identifier, e.attributes, e.update_attrib, \
        e.block_size, e.block_count = struct.unpack_from("<IIIIIII", data, offset)
    offset += 28

    if version == 1:
        e.file_offset, e.file_size = struct.unpack_from("<II", data, offset)
        offset += 8
    else:
        e.file_size, e.unknown1, e.unknown2 = struct.unpack_from("<III", data, offset)
        offset += 12

    e.partition_name = _read_cstr(data, offset, 32)
    offset += 32
    e.flash_filename = _read_cstr(data, offset, 32)
    offset += 32
    e.fota_filename  = _read_cstr(data, offset, 32)

    return e


def _read_cstr(data: bytes, offset: int, max_len: int) -> str:
    chunk = data[offset:offset + max_len]
    null_pos = chunk.find(b'\x00')
    if null_pos >= 0:
        chunk = chunk[:null_pos]
    try:
        return chunk.decode('utf-8', errors='replace')
    except Exception:
        return chunk.decode('latin-1', errors='replace')


def serialize_pit(pit: PITFile) -> bytes:
    """Serialize a PITFile back to binary format."""
    header = struct.pack(
        "<IIIIIII",
        PIT_MAGIC,
        len(pit.entries),
        0, 0, 0, 0, 0,  # reserved unknowns
    )
    entries_data = b''.join(_serialize_entry(e, pit.version) for e in pit.entries)
    return header + entries_data


def _serialize_entry(e: PITEntry, version: int) -> bytes:
    data = struct.pack(
        "<IIIIIII",
        e.binary_type, e.device_type, e.identifier,
        e.attributes, e.update_attrib, e.block_size, e.block_count,
    )
    if version == 1:
        data += struct.pack("<II", e.file_offset, e.file_size)
    else:
        data += struct.pack("<III", e.file_size, e.unknown1, e.unknown2)

    data += _write_cstr(e.partition_name, 32)
    data += _write_cstr(e.flash_filename, 32)
    data += _write_cstr(e.fota_filename, 32)
    return data


def _write_cstr(s: str, max_len: int) -> bytes:
    encoded = s.encode('utf-8', errors='replace')[:max_len - 1]
    return encoded + b'\x00' * (max_len - len(encoded))


def pit_summary(pit: PITFile) -> str:
    """Return a human-readable summary of a PIT file."""
    lines = [
        f"PIT Format Version : {pit.version}",
        f"Partition Count    : {pit.entry_count}",
        "",
        f"{'#':<4} {'Name':<20} {'Type':<12} {'Device':<12} {'Blocks':<10} {'Size':<14} {'Flash File':<30}",
        "-" * 104,
    ]
    for i, e in enumerate(pit.entries):
        size_mb  = e.size_bytes / (1024 * 1024) if e.size_bytes else 0
        size_str = f"{size_mb:.1f} MiB" if size_mb >= 1 else f"{e.size_bytes} B"
        lines.append(
            f"{i:<4} {e.partition_name:<20} {e.binary_type_name:<12} "
            f"{e.device_type_name:<12} {e.block_count:<10} {size_str:<14} {e.flash_filename:<30}"
        )
    return "\n".join(lines)
