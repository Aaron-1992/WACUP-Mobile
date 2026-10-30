"""Nintendo DS importer: a ROM, an SDAT, or a single SSEQ.

The DS has no MIDI files and no SoundFonts; it has SSEQ sequences, SBNK banks and
SWAR sample archives inside an SDAT inside the ROM. This importer reads the
sequence (so the notes, tempo, track volumes and transpose all arrive exactly as
the game plays them) and, when converting, also writes the two things people
actually want out of a ROM:

* ``song.mid`` — the sequence as a Standard MIDI File,
* ``song.sf2`` — the bank's instruments and samples as a SoundFont.

Nothing is bundled: everything comes out of the file the user opened.
"""

import os
from typing import List, Optional, Tuple

from .. import nds
from ..model import Song
from . import register

EXTENSIONS = (".nds", ".sdat", ".sseq")
LABEL = "Nintendo DS (ROM / SDAT / SSEQ)"

# The last archive we read, so exporting the MIDI and the SoundFont after a
# conversion does not mean parsing a 64 MB ROM a second time.
_LAST: Optional[Tuple[str, nds.Archive, nds.SequenceEntry, int]] = None


def read(path: str) -> Song:
    return read_with(path, None)


def read_with(path: str, settings=None) -> Song:
    """Read a DS file, honouring the sequence and bank the user picked."""
    global _LAST
    sequence = getattr(settings, "sequence", "") if settings else ""
    bank_choice = getattr(settings, "bank", "") if settings else ""
    try:
        song, archive, entry, bank = nds.load(path, sequence, bank_choice)
    except nds.NdsError as error:
        broken = Song(source_format="nds", source_path=path)
        broken.add_warning(str(error))
        return broken
    _LAST = (path, archive, entry, bank)
    return song


def assets(path: str, directory: str, stem: str) -> List[str]:
    """Write the extracted .mid and .sf2 for a DS file we have already read."""
    global _LAST
    if _LAST is None or _LAST[0] != path:
        try:
            _song, archive, entry, bank = nds.load(path)
        except nds.NdsError:
            return []
        _LAST = (path, archive, entry, bank)
    _path, archive, entry, bank = _LAST
    try:
        return nds.extract_assets(archive, entry, bank, directory, stem)
    except nds.NdsError:
        return []


def songs(path: str):
    """Every song in a DS file as (index, bank, name), for listing and picking."""
    try:
        _song, archive, entry, _bank = nds.load(path)
    except nds.NdsError as error:
        raise ValueError(str(error))
    return [(item.index, item.bank, item.name) for item in archive.sequences]


def describe(path: str) -> str:
    """A one-line summary for the window: how many sequences a ROM holds."""
    try:
        _song, archive, _entry, _bank = nds.load(path)
    except nds.NdsError as error:
        return str(error)
    return "%d sequences, %d banks, %d wave archives" % (
        len(archive.sequences), len(archive.banks), len(archive.waves))


@register("nds", LABEL)
def _register() -> None:
    """Nothing to do: importing this module is what registers it."""
    return None


__all__ = ["EXTENSIONS", "LABEL", "read", "assets", "describe",
           "os"]
