"""GYM importer (Genesis log format), raw or gzip-compressed.

GYM is just a stripped-down register log, so it feeds the same tracker as VGM:

    0x00  YM2612 register write   (reg, value)
    0x01  delay                   (little-endian sample count)
    0x02  SN76489 write           (value)
    0x03  end of stream
"""

import gzip
import struct

from ..model import Song
from . import register
from .vgm import GenesisTracker

EXTENSIONS = (".gym",)
LABEL = "GYM (Genesis log)"


def _open(path: str) -> bytes:
    with open(path, "rb") as handle:
        head = handle.read(2)
    if head == b"\x1f\x8b":
        with gzip.open(path, "rb") as inner:
            return inner.read()
    with open(path, "rb") as handle:
        return handle.read()


def read(path: str) -> Song:
    data = _open(path)
    song = Song(source_format="gym", source_path=path)

    if data[:3] != b"GYM":
        song.add_warning("missing GYM signature")
        return song

    tracker = GenesisTracker()
    pos = 12
    while pos < len(data):
        command = data[pos]
        pos += 1
        if command == 0x00:
            if pos + 2 > len(data):
                break
            tracker.ym_write(0, data[pos], data[pos + 1])
            pos += 2
        elif command == 0x01:
            if pos + 2 > len(data):
                break
            tracker.wait(struct.unpack("<H", data[pos:pos + 2])[0])
            pos += 2
        elif command == 0x02:
            if pos + 1 > len(data):
                break
            tracker.psg_write(data[pos])
            pos += 1
        elif command == 0x03:
            break
        else:
            song.add_warning("unknown GYM command 0x%02X at byte %d" % (command, pos - 1))
            break

    song.notes = tracker.finish()
    song.refresh_duration()
    if not song.notes:
        song.add_warning("no notes recovered from this GYM file")
    return song


register("gym", LABEL)(read)
