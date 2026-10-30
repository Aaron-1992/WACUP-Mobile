"""Nintendo DS music: read a ROM, pull the sequence and the instruments out of it.

A DS game does not contain MIDI files and does not contain SoundFonts. It contains
an **SDAT** inside the ROM, and inside that:

* **SSEQ** — a sequence: note/velocity/duration events per track, with a tempo and
  an instrument per track. Functionally MIDI, in Nintendo's own encoding.
* **SBNK** — a bank: up to 128 instruments, each a key range pointing at one wave
  (and a base pitch, envelope and pan).
* **SWAR** — a wave archive: the actual samples the bank's instruments play.

This module reads all three, converts an SSEQ into a real Standard MIDI File and an
SBNK+SWAR into a real SoundFont (`.sf2`), and hands the notes to the normal
converter. Nothing is bundled with chip8bit: everything is read from the ROM file
the user points it at, on their own machine, and written next to their output.

Format references: GBATEK's SOUND section, loveemu's NDS format notes, Nitro
Composer's SDAT layout. Ticks are 48 per quarter note, which is why the exported
MIDI uses a 48 division.
"""

import os
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .model import Note, Song

TICKS_PER_QUARTER = 48

# SSEQ command lengths, straight from the format: the byte after the command.
# Fixed-size commands, as counts of *parameters* after the command byte. The
# arithmetic and comparison commands carry a variable, a 16-bit value and an
# operator each; the rest are one-byte settings or 16-bit values.
_FIXED = {
    0x93: 4, 0x94: 3, 0x95: 3,
    0xB0: 3, 0xB1: 3, 0xB2: 3, 0xB3: 3, 0xB4: 3, 0xB5: 3, 0xB6: 3, 0xB7: 3,
    0xB8: 3, 0xB9: 3, 0xBA: 3, 0xBB: 3, 0xBC: 3, 0xBD: 3,
    0xC0: 1, 0xC1: 1, 0xC2: 1, 0xC3: 1, 0xC4: 1, 0xC5: 1, 0xC6: 1, 0xC7: 1,
    0xC8: 1, 0xC9: 1, 0xCA: 1, 0xCB: 1, 0xCC: 1, 0xCD: 1, 0xCE: 1, 0xCF: 1,
    0xD0: 1, 0xD1: 1, 0xD2: 1, 0xD3: 1, 0xD4: 1, 0xD5: 1, 0xD6: 1,
    0xE0: 2, 0xE1: 2, 0xE3: 2, 0xFE: 2,
}
_NO_PARAM = {0xFC, 0xFD, 0xFF}


class NdsError(ValueError):
    """The file is not a DS ROM / SDAT we can read."""


# --------------------------------------------------------------------- helpers

def _u16(data: bytes, at: int) -> int:
    return struct.unpack_from("<H", data, at)[0]


def _u32(data: bytes, at: int) -> int:
    return struct.unpack_from("<I", data, at)[0]


def _vlq(data: bytes, at: int) -> Tuple[int, int]:
    """SSEQ durations are variable-length: 7 bits per byte, high bit = continue."""
    value = 0
    for _ in range(4):
        if at >= len(data):
            break
        byte = data[at]
        at += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            break
    return value, at


def _cstring(data: bytes, at: int, limit: int = 64) -> str:
    end = at
    while end < min(len(data), at + limit) and data[end]:
        end += 1
    try:
        return data[at:end].decode("utf-8", "replace").strip()
    except Exception:
        return ""


# ------------------------------------------------------------------- the ROM

class Rom:
    """An .nds file: just enough of the FAT to fetch files by id."""

    def __init__(self, data: bytes):
        if len(data) < 0x200:
            raise NdsError("too small to be a DS ROM")
        self.data = data
        self.title = _cstring(data, 0, 12) or "Nintendo DS ROM"
        self.game_code = _cstring(data, 0x0C, 4)
        self.fat_offset = _u32(data, 0x48)
        self.fat_size = _u32(data, 0x4C)
        if not (0 < self.fat_offset < len(data)) or not self.fat_size:
            raise NdsError("no file table — this does not look like an .nds ROM")

    def file_count(self) -> int:
        return self.fat_size // 8

    def read_file(self, file_id: int) -> bytes:
        count = self.file_count()
        if not (0 <= file_id < count):
            raise NdsError("file id %d is out of range" % file_id)
        entry = self.fat_offset + file_id * 8
        start = _u32(self.data, entry)
        end = _u32(self.data, entry + 4)
        if not (0 <= start < end <= len(self.data)):
            raise NdsError("file %d has a broken table entry" % file_id)
        return self.data[start:end]

    def find_sdat(self) -> bytes:
        """Find the sound archive. Usually it is a plain file in the FAT."""
        for file_id in range(self.file_count()):
            try:
                blob = self.read_file(file_id)
            except NdsError:
                continue
            if blob[:4] == b"SDAT":
                return blob
        # some ROMs keep it somewhere odd: fall back to a scan of the whole image
        at = self.data.find(b"SDAT\xff\xfe")
        if at >= 0:
            blob = self.data[at:]
            if len(blob) >= 0x20:
                declared = _u32(blob, 8)
                if 0 < declared <= len(blob):
                    return blob[:declared]
                return blob
        raise NdsError("no SDAT sound archive in this ROM (many games use a "
                       "custom sound engine instead)")


# ------------------------------------------------------------------- the SDAT

@dataclass
class SequenceEntry:
    index: int
    name: str
    bank: int
    volume: int
    sseq: bytes


@dataclass
class BankEntry:
    index: int
    name: str
    sbnk: bytes
    wave_archives: List[int]


@dataclass
class Archive:
    """A parsed SDAT: sequences, banks and wave archives, all as raw blobs."""

    name: str = "SDAT"
    sequences: List[SequenceEntry] = field(default_factory=list)
    banks: List[BankEntry] = field(default_factory=list)
    waves: Dict[int, bytes] = field(default_factory=dict)

    # ------------------------------------------------------------------ parse

    @classmethod
    def from_bytes(cls, data: bytes, name: str = "SDAT") -> "Archive":
        if data[:4] != b"SDAT":
            raise NdsError("not an SDAT file")
        archive = cls(name=name)

        (symb_off, symb_size, info_off, info_size, fat_off, fat_size,
         file_off, file_size) = struct.unpack_from("<8I", data, 0x10)

        # --- the FAT: the actual payload of every file, in one block
        files: List[bytes] = []
        if fat_off and fat_size:
            count = _u32(data, fat_off + 8)
            for index in range(count):
                entry = fat_off + 0x0C + index * 0x10
                offset = _u32(data, entry)
                length = _u32(data, entry + 4)
                files.append(data[offset:offset + length])

        # --- symbols, so sequences and banks get the names the game used
        symbols: Dict[int, List[str]] = {}
        if symb_off:
            offsets = struct.unpack_from("<8I", data, symb_off + 8)
            for part, relative in enumerate(offsets):
                symbols[part] = _read_symbols(data, symb_off, relative)

        if not (info_off and info_size):
            raise NdsError("SDAT has no INFO block")
        info_offsets = struct.unpack_from("<8I", data, info_off + 8)

        def entries(part: int) -> List[Optional[int]]:
            relative = info_offsets[part] if part < len(info_offsets) else 0
            if not relative:
                return []
            count = _u32(data, info_off + relative)
            at = info_off + relative + 4
            out = []
            for _ in range(count):
                value = _u32(data, at)
                at += 4
                out.append(info_off + value if value else None)
            return out

        def payload(file_id: int) -> bytes:
            if 0 <= file_id < len(files):
                return files[file_id]
            return b""

        # info part 0 = SSEQ, 2 = SBNK, 3 = SWAR
        for index, entry in enumerate(entries(0)):
            if entry is None:
                continue
            file_id, _unknown, bank, volume, _cp, _pp, _player = \
                struct.unpack_from("<3H4B", data, entry)
            archive.sequences.append(SequenceEntry(
                index=index,
                name=_pick(symbols, 0, index, "SEQUENCE %03d" % index),
                bank=bank, volume=volume or 100, sseq=payload(file_id)))

        for index, entry in enumerate(entries(2)):
            if entry is None:
                continue
            file_id, _unknown = struct.unpack_from("<HH", data, entry)
            wave_ids = struct.unpack_from("<4h", data, entry + 4)
            archive.banks.append(BankEntry(
                index=index,
                name=_pick(symbols, 2, index, "BANK %02d" % index),
                sbnk=payload(file_id),
                wave_archives=[w for w in wave_ids if w >= 0]))

        for index, entry in enumerate(entries(3)):
            if entry is None:
                continue
            file_id, _unknown = struct.unpack_from("<HH", data, entry)
            archive.waves[index] = payload(file_id)
        return archive

    # ------------------------------------------------------------------ pick

    def best_sequence(self) -> SequenceEntry:
        """The sequence with the most playable notes — usually the main theme."""
        if not self.sequences:
            raise NdsError("this SDAT has no sequences in it")
        best, best_score = None, -1
        for entry in self.sequences:
            if not entry.sseq:
                continue
            try:
                score = len(read_sequence(entry.sseq).notes)
            except Exception:
                score = 0
            if score > best_score:
                best, best_score = entry, score
        if best is None:
            raise NdsError("no sequence in this SDAT could be read")
        return best

    def find_sequence(self, wanted: str) -> SequenceEntry:
        """Pick a sequence by index ('12') or by name fragment."""
        if not self.sequences:
            raise NdsError("this SDAT has no sequences in it")
        wanted = (wanted or "").strip()
        if not wanted:
            return self.best_sequence()
        if wanted.isdigit():
            index = int(wanted)
            for entry in self.sequences:
                if entry.index == index:
                    return entry
            raise NdsError("no sequence %s (this SDAT has %d)"
                           % (wanted, len(self.sequences)))
        lowered = wanted.lower()
        for entry in self.sequences:
            if lowered in entry.name.lower():
                return entry
        raise NdsError("no sequence called '%s'" % wanted)


def _pick(symbols: Dict[int, List[str]], part: int, index: int,
          fallback: str) -> str:
    names = symbols.get(part) or []
    if 0 <= index < len(names) and names[index]:
        return names[index]
    return fallback


def _read_symbols(data: bytes, block: int, offset: int) -> List[str]:
    if not offset:
        return []
    try:
        count = _u32(data, block + offset)
        if count > 4096:
            return []
        at = block + offset + 4
        out = []
        for _ in range(count):
            relative = _u32(data, at)
            at += 4
            out.append(_cstring(data, block + relative) if relative else "")
        return out
    except Exception:
        return []


# ------------------------------------------------------------------- the SSEQ

@dataclass
class _TrackState:
    number: int
    program: int = 0
    volume: int = 127
    expression: int = 127
    transpose: int = 0
    vibrato: int = 0


def read_sequence(data: bytes, max_seconds: float = 420.0) -> Song:
    """Parse an SSEQ into a Song: notes in seconds, tempo, track names.

    One pass only. A DS sequence loops forever, and following the loop is never
    what someone converting it wants, so the first backward jump ends a track.
    """
    if data[:4] != b"SSEQ":
        raise NdsError("not an SSEQ sequence")
    total = _u32(data, 8) or len(data)
    data_offset = _u32(data, 0x18)
    body = data[data_offset:total]

    song = Song(source_format="nds", )
    starts: List[Tuple[int, int]] = []          # (track number, offset in body)
    tempo_at: Dict[int, int] = {}               # absolute tick -> bpm
    notes: List[Note] = []
    global_volume = 127
    chosen_bank: Optional[int] = None           # from the first program change
    ticks_per_second_at: Dict[int, float] = {}

    # --- pass 1: find the tracks, and the tempo map, by walking every track
    tempo = 127
    pos = 0
    while pos < len(body):
        command = body[pos]
        if command == 0x93 and pos + 5 <= len(body):
            number = body[pos + 1]
            offset = body[pos + 2] | (body[pos + 3] << 8) | (body[pos + 4] << 16)
            starts.append((number, offset))
            pos += 5
        elif command == 0xFE and pos + 3 <= len(body):
            pos += 3
        elif command == 0xFF:
            pos += 1
        else:
            step = _command_length(body, pos)
            if step <= 0:
                break
            pos += step
        if len(starts) > 16:
            break

    if not starts:
        raise NdsError("this sequence has no tracks in it")

    # --- pass 2: walk each track, collecting notes and tempo changes
    for number, offset in starts:
        state = _TrackState(number=number)
        position = offset
        tick = 0
        loop_back = -1
        calls: List[int] = []
        visited: Dict[int, int] = {}
        guard = 0
        while 0 <= position < len(body) and guard < 200000:
            guard += 1
            command = body[position]
            if command < 0x80:                      # a note
                if position + 2 > len(body):
                    break
                velocity = body[position + 1]
                duration, after = _vlq(body, position + 2)
                pitch = command + state.transpose
                wait = max(1, duration)
                if 0 <= pitch <= 127 and velocity > 0:
                    notes.append(Note(
                        start=tick, dur=wait, pitch=pitch,
                        velocity=_scaled_velocity(velocity, state, global_volume),
                        part=number, program=state.program,
                        vibrato=(state.vibrato / 127.0) * 0.35,
                        track_name="Track %02d" % number))
                tick += wait
                position = after
                continue
            if command == 0x80:                     # rest
                duration, after = _vlq(body, position + 1)
                tick += max(1, duration)
                position = after
                continue
            if command == 0x81:
                # one variable-length value: low byte is the program, bits 8..14
                # the bank, which is how a song says which bank it wants
                value, _after = _vlq(body, position + 1)
                state.program = value & 0x7F
                if chosen_bank is None:
                    chosen_bank = (value >> 8) & 0x7F
            elif command == 0xC1:
                state.volume = body[position + 1]
            elif command == 0xD5:
                state.expression = body[position + 1]
            elif command == 0xC2:
                global_volume = body[position + 1]
            elif command == 0xC3:
                state.transpose = body[position + 1] - 256 \
                    if body[position + 1] > 127 else body[position + 1]
            elif command == 0xCA:
                state.vibrato = body[position + 1]
            elif command == 0xE1:
                value = _u16(body, position + 1)
                # the field is BPM; a few files store it pre-scaled by 0x30
                tempo = value // 0x30 if value > 0x400 else value
                tempo = max(1, min(480, tempo or 120))
                tempo_at[tick] = tempo
            elif command == 0xC8:                   # tie: extend the last note
                duration, after = _vlq(body, position + 1)
                if notes:
                    notes[-1].dur += max(1, duration)
                tick += max(1, duration)
                position = after
                continue
            elif command == 0x95:                   # call
                calls.append(position + 4)
                target = body[position + 1] | (body[position + 2] << 8) | \
                    (body[position + 3] << 16)
                position = target
                continue
            elif command == 0xFD:                   # return
                if not calls:
                    break
                position = calls.pop()
                continue
            elif command in (0x94, 0xFF):           # jump / end of track
                break                               # one pass, then stop
            elif command == 0xFC:                   # end of loop
                if loop_back >= 0:
                    position = loop_back
                    loop_back = -1
                    continue
            elif command == 0xD4:
                loop_back = position
            if position in visited and visited[position] > 2:
                break
            visited[position] = visited.get(position, 0) + 1
            step = _command_length(body, position)
            if step <= 0:
                song.add_warning(
                    "track %d uses command 0x%02X, which this reader does not "
                    "follow — the rest of that track was left out"
                    % (number, body[position]))
                break
            position += step

    if not notes:
        raise NdsError("this sequence has no notes in it (or uses a command "
                       "this reader does not know)")

    # --- ticks -> seconds, with every tempo change honoured
    changes = sorted(tempo_at.items()) or [(0, 120)]
    if changes[0][0] != 0:
        changes.insert(0, (0, changes[0][1]))
    seconds_at: Dict[int, float] = {changes[0][0]: 0.0}
    ticks_per_second_at[changes[0][0]] = changes[0][1] / 60.0 * TICKS_PER_QUARTER
    for index in range(1, len(changes)):
        previous_tick, previous_bpm = changes[index - 1]
        tick_value, bpm = changes[index]
        span = (tick_value - previous_tick) / \
            (previous_bpm / 60.0 * TICKS_PER_QUARTER)
        seconds_at[tick_value] = seconds_at[previous_tick] + span
        ticks_per_second_at[tick_value] = bpm / 60.0 * TICKS_PER_QUARTER

    def to_seconds(tick: int) -> float:
        mark = 0
        for at in seconds_at:
            if at <= tick:
                mark = at
            else:
                break
        return seconds_at[mark] + (tick - mark) / ticks_per_second_at[mark]

    converted: List[Note] = []
    latest = 0.0
    for note in notes:
        start = to_seconds(int(note.start))
        end = to_seconds(int(note.start + note.dur))
        if start > max_seconds:
            continue
        note.start = start
        note.dur = max(0.03, min(end - start, max_seconds - start))
        latest = max(latest, start)
        converted.append(note)

    song.notes = converted
    song.ds_bank = chosen_bank                  # read by load(), if the user
    song.tempo = float(changes[0][1])           # did not pick a bank himself
    song.title = "SSEQ"
    song.track_names = ["Track %02d" % number for number, _ in starts]
    song.refresh_duration()
    return song


def _scaled_velocity(velocity: int, state: _TrackState, global_volume: int) -> int:
    value = velocity / 127.0
    value *= max(0.0, min(1.0, state.volume / 127.0))
    value *= max(0.0, min(1.0, state.expression / 127.0))
    value *= max(0.0, min(1.0, global_volume / 127.0))
    return max(1, min(127, int(round(value * 127))))


def _command_length(data: bytes, at: int) -> int:
    """How many bytes this command occupies (0 = give up on the track).

    Note lengths and rests are variable length and the arithmetic commands are
    fixed; 0xA1 ("run this command with a variable argument") is the one that
    carries a nested command. A zero means "not understood", and the caller stops
    that track rather than reading the rest of it at the wrong offsets.
    """
    command = data[at]
    if command < 0x80:                            # a note
        _velocity, after = _vlq(data, at + 2)
        return max(1, after - at)
    if command == 0x80:                           # a rest
        _duration, after = _vlq(data, at + 1)
        return max(1, after - at)
    if command == 0x81:                           # bank + program, variable length
        _program, after = _vlq(data, at + 1)
        return max(1, after - at)
    if command in _NO_PARAM:
        return 1
    if command in _FIXED:
        return 1 + _FIXED[command]
    if command == 0xA1 and at + 2 <= len(data):
        # run the command in the next byte with a variable as its argument
        inner = data[at + 1]
        return 4 if 0xB0 <= inner <= 0xBD else 3
    # Anything else (0xA0's randomised commands, and the reserved gaps) has a
    # length this reader cannot work out, and guessing would turn the rest of the
    # track into nonsense. The caller stops the track and says so instead.
    return 0


# ------------------------------------------------------- SSEQ -> MIDI (export)

def sequence_to_midi(data: bytes, song: Optional[Song] = None) -> bytes:
    """Write the sequence out as a real Standard MIDI File (format 1, 48 ppqn)."""
    song = song or read_sequence(data)
    tracks: Dict[int, List[Note]] = {}
    for note in song.notes:
        tracks.setdefault(note.part, []).append(note)

    division = TICKS_PER_QUARTER
    tempo_bpm = max(1.0, song.tempo or 120.0)
    microseconds = int(round(60_000_000.0 / tempo_bpm))

    def event_bytes(delta: int, body: bytes) -> bytes:
        return _write_vlq(delta) + body

    chunks: List[bytes] = []

    # --- conductor track: tempo + track name
    meta = b""
    meta += event_bytes(0, b"\xff\x51\x03" + microseconds.to_bytes(3, "big"))
    meta += event_bytes(0, b"\xff\x58\x04\x04\x02\x18\x08")
    meta += event_bytes(0, b"\xff\x2f\x00")
    chunks.append(b"MTrk" + struct.pack(">I", len(meta)) + meta)

    for number in sorted(tracks):
        notes = sorted(tracks[number], key=lambda n: n.start)
        events: List[Tuple[float, int, bytes]] = []
        programs_done = set()
        for note in notes:
            on = note.start * division * tempo_bpm / 60.0
            off = (note.start + note.dur) * division * tempo_bpm / 60.0
            if note.program not in programs_done:
                programs_done.add(note.program)
                events.append((max(0.0, on - 0.01), 0,
                               bytes([0xC0 | (number & 0x0F),
                                      note.program & 0x7F])))
            events.append((on, 1, bytes([0x90 | (number & 0x0F),
                                         note.pitch & 0x7F,
                                         note.velocity & 0x7F])))
            events.append((off, 0, bytes([0x80 | (number & 0x0F),
                                          note.pitch & 0x7F, 0])))
        events.sort(key=lambda item: (item[0], item[1]))
        body = b""
        body += event_bytes(0, b"\xff\x03" + bytes([len("Track %02d" % number)]) +
                            ("Track %02d" % number).encode("ascii"))
        previous = 0.0
        for moment, _order, payload in events:
            tick = int(round(moment))
            body += event_bytes(max(0, tick - int(round(previous))), payload)
            previous = moment
        body += event_bytes(0, b"\xff\x2f\x00")
        chunks.append(b"MTrk" + struct.pack(">I", len(body)) + body)

    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(chunks), division)
    return header + b"".join(chunks)


def _write_vlq(value: int) -> bytes:
    value = max(0, int(value))
    out = bytearray([value & 0x7F])
    value >>= 7
    while value:
        out.insert(0, 0x80 | (value & 0x7F))
        value >>= 7
    return bytes(out)


# --------------------------------------------------- the bank and its samples

@dataclass
class Zone:
    low: int
    high: int
    wave: int                 # wave id inside the archive
    archive: int              # which SWAR it lives in
    root: int                 # the pitch the sample was recorded at
    attack: int = 127
    decay: int = 127
    sustain: int = 127
    release: int = 127
    pan: int = 64


def read_bank(sbnk: bytes, wave_archive: int = 0) -> List[List[Zone]]:
    """Parse an SBNK into 128 instrument slots, each a list of key zones."""
    if sbnk[:4] != b"SBNK":
        raise NdsError("not an SBNK bank")
    # DATA block: magic, size, 32 bytes of pad, then the instrument count.
    count = min(_u32(sbnk, 0x38), 128)
    instruments: List[List[Zone]] = []
    for slot in range(count):
        entry = 0x3C + slot * 4
        if entry + 4 > len(sbnk):
            break
        kind = sbnk[entry]                     # type is a single byte
        offset = _u16(sbnk, entry + 1)         # then a 16-bit absolute offset
        if not offset or kind == 0:
            instruments.append([])
            continue
        try:
            instruments.append(_read_instrument(sbnk, kind, offset,
                                                wave_archive))
        except Exception:
            instruments.append([])
    while len(instruments) < 128:
        instruments.append([])
    return instruments


def _note_definition(data: bytes, at: int) -> Tuple[int, int, Zone]:
    """A note definition: wave, archive, root pitch, then the envelope and pan.

    Inside a range or regional instrument each of these is preceded by a 16-bit
    *type* (PCM / PSG square / PSG noise), which is why the caller passes at + 2.
    """
    wave, archive, root, attack, decay, sustain, release, pan = \
        struct.unpack_from("<HH6B", data, at)
    return wave, archive, Zone(low=0, high=127, wave=wave, archive=archive,
                               root=root, attack=attack, decay=decay,
                               sustain=sustain, release=release, pan=pan)


def _read_instrument(data: bytes, kind: int, at: int,
                     wave_archive: int) -> List[Zone]:
    zones: List[Zone] = []
    if kind in (1, 2, 3):                      # a single note, whole keyboard
        wave, archive, zone = _note_definition(data, at)
        zone.low, zone.high = 0, 127
        zone.archive = archive if archive < 0xFFFF else wave_archive
        zones.append(zone)
    elif kind == 16:                           # one note per key in a range
        low, high = data[at], data[at + 1]
        position = at + 2
        for pitch in range(low, high + 1):
            _wave, archive, zone = _note_definition(data, position + 2)
            zone.low = zone.high = pitch
            zone.archive = archive if archive < 0xFFFF else wave_archive
            zones.append(zone)
            position += 0xC
    elif kind == 17:                           # up to eight key regions
        ends = list(data[at:at + 8])
        position = at + 8
        low = 0
        for end in ends:
            if end == 0 and position != at + 8:
                break
            _wave, archive, zone = _note_definition(data, position + 2)
            zone.low, zone.high = low, end
            zone.archive = archive if archive < 0xFFFF else wave_archive
            zones.append(zone)
            position += 0xC
            low = end + 1
    return zones


def read_wave_archive(swar: bytes) -> Dict[int, dict]:
    """Parse an SWAR into {wave id: {rate, loop, data, type}}."""
    if swar[:4] != b"SWAR":
        raise NdsError("not an SWAR wave archive")
    if swar[0x10:0x14] != b"DATA":
        raise NdsError("SWAR has no DATA block")
    count = min(_u32(swar, 0x38), 4096)
    waves: Dict[int, dict] = {}
    offsets = []
    for index in range(count):
        entry = 0x3C + index * 4
        if entry + 4 > len(swar):
            break
        offsets.append(_u32(swar, entry))
    for index, start in enumerate(offsets):
        end = len(swar)
        if index + 1 < len(offsets) and offsets[index + 1] > start:
            end = offsets[index + 1]
        if not start or start >= len(swar):
            continue
        try:
            waves[index] = _read_swav(swar[start:end])
        except Exception:
            continue
    return waves


def _read_swav(blob: bytes) -> dict:
    """One SWAV. Inside a wave archive the entry begins at the SWAV *info* struct
    — the sample data follows twelve bytes later. A standalone .swav file (some
    rips keep those) has its standard header and a DATA block in front instead.

    The two size fields count 4-byte words, not samples (the hardware's loop and
    length registers count the same way): a word holds 4 PCM8 samples, 2 PCM16
    samples, or 8 ADPCM samples — and ADPCM keeps its 4-byte state word *before*
    those samples, so its length field counts words without that header.
    """
    head = 0x18 if blob[:4] == b"SWAV" and blob[0x10:0x14] == b"DATA" else 0
    if len(blob) < head + 0xC:
        raise NdsError("SWAV is too short")
    wave_type = blob[head]
    looped = bool(blob[head + 1])
    rate = _u16(blob, head + 2) or 8000
    # 0x00 type, 0x01 loop flag, 0x02 sample rate, 0x04 time (in words),
    # 0x06 loop offset (words), 0x08 length (words); the data starts at 0x0C
    loop_word = _u16(blob, head + 6)
    length_words = _u32(blob, head + 8)
    per_word = (4, 2, 8)[wave_type] if wave_type in (0, 1, 2) else 4
    header_bytes = 4 if wave_type == 2 else 0

    payload = blob[head + 0xC:head + 0xC + length_words * 4 + header_bytes]
    # ADPCM starts the loop one word late: word 0 of the sample is its state word
    loop_start = max(0, loop_word * per_word - header_bytes * 2)
    pcm = _decode_wave(wave_type, payload)
    loop_end = loop_start + len(pcm)
    if loop_end <= loop_start:
        loop_start, loop_end = 0, len(pcm)
    return dict(type=wave_type, rate=rate, looped=looped,
                loop_start=loop_start, loop_end=loop_end,
                data=payload, pcm=pcm)


def _decode_wave(wave_type: int, payload: bytes) -> List[int]:
    """SWAV to 16-bit PCM. PCM8 and PCM16 are trivial, ADPCM is Nintendo's IMA."""
    if wave_type == 0:                                    # 8-bit unsigned
        return [(value - 128) << 8 for value in payload]
    if wave_type == 1:                                    # 16-bit signed
        count = len(payload) // 2
        return list(struct.unpack_from("<%dh" % count, payload, 0))
    if wave_type == 2:                                    # IMA ADPCM, 4-bit
        return _decode_adpcm(payload)
    return []


_IMA_STEPS = [
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41,
    45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190,
    209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724,
    796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499,
    2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845,
    8630, 9493, 10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385,
    24623, 27086, 29794, 32767]
_IMA_INDEX = [-1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8]


def _decode_adpcm(payload: bytes) -> List[int]:
    """Nintendo's IMA ADPCM: a 4-byte state word, then nibbles, low nibble first.

    The hardware (and the game's sound driver) reads a sample as a 16-bit
    predictor, a 16-bit step index and then two samples per byte — there are no
    per-block headers of the kind a WAV file would have.
    """
    if len(payload) < 4:
        return []
    predictor, step_index = struct.unpack_from("<hH", payload, 0)
    step_index = max(0, min(88, step_index))
    out: List[int] = []
    for byte in payload[4:]:
        for nibble in (byte & 0x0F, byte >> 4):
            step = _IMA_STEPS[step_index]
            difference = step >> 3
            if nibble & 1:
                difference += step >> 2
            if nibble & 2:
                difference += step >> 1
            if nibble & 4:
                difference += step
            predictor += -difference if nibble & 8 else difference
            predictor = max(-32767, min(32767, predictor))
            step_index = max(0, min(88, step_index + _IMA_INDEX[nibble & 0x07]))
            out.append(predictor)
    return out


# ------------------------------------------------------- SBNK + SWAR -> .sf2

def build_soundfont(archive: Archive, bank_index: int, path: str,
                    names: Optional[List[str]] = None) -> Tuple[str, int]:
    """Write an SF2 SoundFont from one bank and the wave archives it uses.

    Every instrument in the bank becomes a preset with its key zones intact, so
    a sampler (or any synth that reads SF2) plays the game's own sounds.
    """
    if not (0 <= bank_index < len(archive.banks)):
        raise NdsError("no bank %d in this SDAT (it has %d)"
                       % (bank_index, len(archive.banks)))
    bank = archive.banks[bank_index]

    waves: Dict[int, Dict[int, dict]] = {}
    for archive_id in bank.wave_archives:
        blob = archive.waves.get(archive_id)
        if not blob:
            continue
        try:
            waves[archive_id] = read_wave_archive(blob)
        except NdsError:
            continue

    instruments = read_bank(bank.sbnk, bank.wave_archives[0]
                            if bank.wave_archives else 0)

    pcm = bytearray()
    sample_headers = []          # (name, start, end, loop_start, loop_end)
    sample_ids: Dict[Tuple[int, int], int] = {}
    looped_by_sample: Dict[int, bool] = {}
    zones_by_instrument: List[List[Tuple[int, Zone, bool]]] = []

    for slot, zones in enumerate(instruments):
        collected = []
        for zone in zones:
            archive_waves = waves.get(zone.archive)
            if not archive_waves:
                continue
            wave = archive_waves.get(zone.wave)
            if not wave or not wave.get("pcm"):
                continue
            key = (zone.archive, zone.wave)
            if key not in sample_ids:
                samples = wave["pcm"]
                start = len(pcm) // 2
                if len(samples) % 2:
                    samples = samples + [0]
                pcm += struct.pack("<%dh" % len(samples), *samples)
                end = start + len(samples)
                if wave.get("looped"):
                    # SF2 loop end is the first sample *after* the loop; the two
                    # guard samples appended to smpl make an end at `end` safe.
                    loop_start = start + wave.get("loop_start", 0)
                    loop_end = start + wave.get("loop_end", len(samples))
                    loop_start = max(start, min(loop_start, end - 2))
                    loop_end = max(loop_start + 2, min(loop_end, end))
                else:
                    loop_start, loop_end = 0, 0
                label = "bank%d a%d w%d" % (bank_index, zone.archive, zone.wave)
                sample_ids[key] = len(sample_headers)
                sample_headers.append((label, start, end, loop_start, loop_end,
                                       wave.get("rate", 8000), zone.root))
                looped_by_sample[sample_ids[key]] = bool(wave.get("looped"))
            collected.append((sample_ids[key], zone, looped_by_sample[sample_ids[key]]))
        zones_by_instrument.append(collected)

    if not sample_headers:
        raise NdsError("this bank's samples could not be read")

    for _key, _index in list(sample_ids.items()):
        pass

    if names is None:
        names = []
    data = _sf2_bytes(pcm, sample_headers, zones_by_instrument, bank_index,
                      names)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    return path, len(sample_headers)


# DS envelopes run on a curve of their own, so the attack/decay/release numbers
# are not carried over (the samples, key ranges, root keys, loops and pans are).
# Every zone gets the same short release instead, which stops a note without the
# click an instant cut would give.
_RELEASE_TC = -1800                 # 1200 * log2(0.35 s)


def _gen(operator: int, amount: int) -> bytes:
    """One generator record of a SoundFont zone."""
    return struct.pack("<HH", operator, amount & 0xFFFF)


def _program_name(slot: int) -> str:
    """A bank slot's name, using the General MIDI name of the program it serves."""
    try:
        from . import gm
        return ("%03d " % slot) + gm.name(slot)
    except Exception:
        return "Program %03d" % slot


def _name(text: str, width: int = 20) -> bytes:
    raw = text.encode("ascii", "replace")[:width - 1]
    return raw + b"\x00" * (width - len(raw))


def _sf2_bytes(pcm: bytearray, samples, instruments, bank_index: int,
               names: List[str]) -> bytes:
    """Assemble a minimal but valid SoundFont 2 file."""
    def chunk(tag: bytes, body: bytes) -> bytes:
        return tag + struct.pack("<I", len(body)) + body + \
            (b"\x00" if len(body) % 2 else b"")

    def list_chunk(tag: bytes, body: bytes) -> bytes:
        return b"LIST" + struct.pack("<I", len(body) + 4) + tag + body

    # --- sdta: the samples, 16-bit little endian
    smpl = bytes(pcm) + b"\x00\x00\x00\x00"          # a few guard samples
    sdta = list_chunk(b"sdta", chunk(b"smpl", smpl))

    # --- pdta
    phdr: List[bytes] = []
    pbag: List[bytes] = []
    pgen: List[bytes] = []
    inst: List[bytes] = []
    ibag: List[bytes] = []
    igen: List[bytes] = []
    shdr: List[bytes] = []

    for index, (label, start, end, loop_start, loop_end, rate,
                root) in enumerate(samples):
        shdr.append(_name(label) + struct.pack(
            "<IIIIIBbHH", start, end, loop_start, loop_end, int(rate),
            max(0, min(127, root)), 0, 0, 1))    # 1 = mono sample

    preset_index = 0
    for slot, zones in enumerate(instruments):
        if not zones:
            continue
        name = names[slot] if slot < len(names) and names[slot] else \
            _program_name(slot)
        instrument_name = ("B%d " % bank_index) + name
        inst.append(_name(instrument_name) +
                    struct.pack("<H", len(ibag)))
        for sample_id, zone, looped in zones:
            ibag.append(struct.pack("<HH", len(igen), 0))
            igen.append(_gen(43, (zone.low & 0xFF) | ((zone.high & 0xFF) << 8)))
            igen.append(_gen(58, max(0, min(127, zone.root))))
            # The DS pans 0..127 with 64 in the middle; SF2 pans in 0.1 %.
            pan = int(round((max(0, min(127, zone.pan)) - 64) * 500 / 63.0))
            igen.append(_gen(17, struct.unpack("<H", struct.pack("<h", max(-500, min(500, pan))))[0]))
            if looped:
                igen.append(_gen(54, 1))          # sampleModes: loop continuously
            igen.append(_gen(38, _RELEASE_TC))    # a short release, never a click
            igen.append(_gen(53, sample_id))
        pbag.append(struct.pack("<HH", len(pgen), 0))
        pgen.append(_gen(41, preset_index))       # instrument
        phdr.append(_name(name) + struct.pack(
            "<HHHIII", preset_index, 0, len(pbag) - 1, 0, 0, 0))
        preset_index += 1

    # terminal records, as the format demands
    phdr.append(_name("EOP") + struct.pack("<HHHIII", 0, 0,
                                           len(pbag), 0, 0, 0))
    pbag.append(struct.pack("<HH", len(pgen), 0))
    pgen.append(struct.pack("<HH", 0, 0))
    inst.append(_name("EOI") + struct.pack("<H", len(ibag)))
    ibag.append(struct.pack("<HH", len(igen), 0))
    igen.append(struct.pack("<HH", 0, 0))
    shdr.append(_name("EOS") + struct.pack("<IIIIIBbHH", 0, 0, 0, 0, 0, 60, 0,
                                           0, 0))

    pdta = list_chunk(b"pdta", b"".join([
        chunk(b"phdr", b"".join(phdr)),
        chunk(b"pbag", b"".join(pbag)),
        chunk(b"pmod", struct.pack("<HHhHH", 0, 0, 0, 0, 0)),
        chunk(b"pgen", b"".join(pgen)),
        chunk(b"inst", b"".join(inst)),
        chunk(b"ibag", b"".join(ibag)),
        chunk(b"imod", struct.pack("<HHhHH", 0, 0, 0, 0, 0)),
        chunk(b"igen", b"".join(igen)),
        chunk(b"shdr", b"".join(shdr)),
    ]))

    info = list_chunk(b"INFO", b"".join([
        chunk(b"ifil", struct.pack("<HH", 2, 1)),
        chunk(b"isng", b"EMU8000\x00"),
        chunk(b"INAM", _name("DS bank %02d" % bank_index, 32)),
        chunk(b"IENG", _name("chip8bit", 32)),
        chunk(b"IPRD", _name("Nintendo DS", 32)),
        chunk(b"ICMT", _name("extracted from an SDAT", 32)),
    ]))

    body = b"sfbk" + info + sdta + pdta
    return b"RIFF" + struct.pack("<I", len(body)) + body


# --------------------------------------------------------------- the entry

def load(path: str, sequence: str = "", bank: str = "") -> Tuple[Song, Archive,
                                                                SequenceEntry,
                                                                int]:
    """Read any of .nds / .sdat / .sseq into a Song, plus what it came from."""
    with open(path, "rb") as handle:
        data = handle.read()
    return load_bytes(data, path, sequence, bank)


def load_bytes(data: bytes, path: str = "", sequence: str = "",
               bank: str = "") -> Tuple[Song, Archive, SequenceEntry, int]:
    extension = os.path.splitext(path)[1].lower()

    if data[:4] == b"SSEQ":
        entry = SequenceEntry(index=0, name=os.path.basename(path) or "SSEQ",
                              bank=int(bank) if str(bank).isdigit() else 0,
                              volume=100, sseq=data)
        archive = Archive(name=os.path.basename(path) or "SSEQ")
        archive.sequences.append(entry)
        song = read_sequence(data)
        song.source_path = path
        return song, archive, entry, entry.bank

    if data[:4] == b"SDAT":
        archive = Archive.from_bytes(data, os.path.basename(path) or "SDAT")
    elif data[:4] == b"SWAR" or data[:4] == b"SBNK":
        raise NdsError("that is a bank or a wave archive, not a ROM — drop the "
                       ".nds (or the .sdat) that contains it")
    else:
        if extension in (".nds", ""):
            rom = Rom(data)
            blob = rom.find_sdat()
            archive = Archive.from_bytes(blob, rom.title)
        else:
            raise NdsError("not a DS ROM, SDAT or SSEQ")

    entry = archive.find_sequence(sequence)
    song = read_sequence(entry.sseq)
    song.source_path = path
    song.title = "%s — %s" % (archive.name, entry.name)
    total = len(archive.sequences)
    if total > 1:
        song.add_warning(
            "this archive holds %d songs; converted '%s' (pick another one with "
            "--sequence NAME, or --list-songs to see them)"
            % (total, entry.name) if not sequence else
            "converted '%s' out of %d songs" % (entry.name, total))
    asked_for = getattr(song, "ds_bank", None)
    chosen_bank = (int(bank) if str(bank).isdigit() else
                   asked_for if asked_for is not None else entry.bank)
    if not (0 <= chosen_bank < len(archive.banks)) and archive.banks:
        chosen_bank = 0
    return song, archive, entry, chosen_bank


def extract_assets(song_archive: Archive, entry: SequenceEntry, bank: int,
                   directory: str, stem: str) -> List[str]:
    """Write the extracted MIDI and SoundFont next to the user's output."""
    written: List[str] = []
    os.makedirs(directory, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in " -_()" else "_"
                   for ch in stem).strip() or "song"

    if entry.sseq:
        midi_path = os.path.join(directory, "%s.mid" % safe)
        try:
            with open(midi_path, "wb") as handle:
                handle.write(sequence_to_midi(entry.sseq))
            written.append(midi_path)
        except OSError:
            pass

    if 0 <= bank < len(song_archive.banks):
        sf2_path = os.path.join(directory, "%s.sf2" % safe)
        try:
            build_soundfont(song_archive, bank, sf2_path)
            written.append(sf2_path)
        except (OSError, NdsError):
            pass
    return written
