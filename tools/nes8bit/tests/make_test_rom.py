"""Build a small but *real* Nintendo DS ROM with a sound archive in it.

There is no way to test a DS importer without a DS file, and no ROM can be shipped
with this project, so the test suite builds one: a valid .nds header and file
table, and inside the file table a valid SDAT with one SSEQ (two tracks, a tempo,
an instrument switch, a transpose and a loop), one SBNK (two instruments whose key
zones point at two waves) and one SWAR (a PCM8 wave and a PCM16 wave).

Every structure here is written the way the hardware and the reference documents
describe it, so the reader in nescore/nds.py is being tested against the format
rather than against itself.
"""

import math
import struct


def _std_header(magic: bytes, size: int, blocks: int = 1,
                header_size: int = 0x10) -> bytes:
    return struct.pack("<4sHHIHH", magic, 0xFEFF, 0x100, size, header_size,
                       blocks)


# ------------------------------------------------------------------- sequences

def _vlq(value: int) -> bytes:
    out = bytearray([value & 0x7F])
    value >>= 7
    while value:
        out.insert(0, 0x80 | (value & 0x7F))
        value >>= 7
    return bytes(out)


def build_sseq(program_value=None, extra_melody: bytes = b"",
               head: bytes = b"", head_tempo: int = 0) -> bytes:
    """Three tracks: tempo/track list, a melody with a program change and a
    transpose, and a bass — plus a loop, which the reader must not follow.

    ``program_value`` writes the program change as a raw variable-length value
    (the bank lives in its high bits); ``extra_melody`` slips more commands into
    the melody, which is how the tests check the command table.

    ``head`` puts commands *between* the track table and the first track — which
    is where Nintendo's own sequences keep the tempo. Nothing names that region
    as a track, so a reader that only walks tracks (this one, until it was fixed)
    plays every song at the default 120 BPM.
    """
    # Assembled in two passes because the track offsets are absolute.
    header_size = 0x1C

    def track_events(events: bytes) -> bytes:
        return events

    melody = bytearray()
    if program_value is None:
        melody += bytes([0x81, 5])             # instrument 5
    else:
        melody += bytes([0x81]) + _vlq(program_value)
    melody += extra_melody
    melody += bytes([0xC3, 12])                # transpose up an octave
    melody += bytes([0xC1, 100])               # track volume
    melody += bytes([0xCA, 20])                # a little vibrato depth
    for pitch, length in ((60, 48), (64, 48), (67, 96), (72, 48), (67, 48)):
        melody += bytes([pitch, 100]) + _vlq(length)
    melody += bytes([0x94, 0x00, 0x00, 0x00])  # jump back to the top: a loop
    melody += bytes([0xFF])

    bass = bytearray()
    bass += bytes([0x81, 3])
    for pitch, length in ((36, 96), (43, 96), (41, 96), (36, 96)):
        bass += bytes([pitch, 80]) + _vlq(length)
    bass += bytes([0xFF])

    tempo_and_tracks = bytearray()
    tempo_and_tracks += bytes([0xFE, 0x07, 0x00])      # all three tracks play
    if head_tempo:
        # the tempo lives in the head, the way Nintendo's own sequences write it
        head = bytes([0xE1]) + struct.pack("<H", head_tempo) + head
    else:
        tempo_and_tracks += bytes([0xE1]) + struct.pack("<H", 150)
    tempo_and_tracks += bytes([0xFF])

    # layout: [definitions][tempo track][melody][bass]. Track offsets are
    # relative to the start of the sequence DATA block, not to the file.
    definitions = bytearray()
    tempo_offset = 3 * 5 + len(head)           # three 0x93 definitions, then head
    melody_offset = tempo_offset + len(tempo_and_tracks)
    bass_offset = melody_offset + len(melody)
    for number, offset in ((0, tempo_offset), (1, melody_offset),
                           (2, bass_offset)):
        definitions += bytes([0x93, number, offset & 0xFF, (offset >> 8) & 0xFF,
                              (offset >> 16) & 0xFF])

    body = bytearray(definitions) + head + tempo_and_tracks + melody + bass

    total = header_size + len(body)
    data = bytearray()
    data += _std_header(b"SSEQ", total)
    data += b"DATA" + struct.pack("<II", total - 0x10, header_size)
    data += body
    return bytes(data)


# ---------------------------------------------------------------------- banks

def _note_definition(wave: int, archive: int, root: int, attack: int = 127,
                     decay: int = 100, sustain: int = 90,
                     release: int = 110, pan: int = 64) -> bytes:
    return struct.pack("<HH6B", wave, archive, root, attack, decay, sustain,
                       release, pan)


def _typed_definition(wave: int, archive: int, root: int, **kwargs) -> bytes:
    """What a range/regional instrument stores: a 16-bit type then the definition."""
    return struct.pack("<H", 1) + _note_definition(wave, archive, root, **kwargs)


def build_sbnk() -> bytes:
    """Four instruments: a direct wave, a key range, an eight-region map, and a
    PSG square (which has no sample behind it, like the ones real banks mix in)."""
    direct = _note_definition(0, 0, 60)
    range_low, range_high = 40, 43
    ranged = bytes([range_low, range_high]) + b"".join(
        _typed_definition(1, 0, 60 + index, pan=40 + index * 8)
        for index in range(range_high - range_low + 1))
    regions = bytes([30, 60, 90, 0, 0, 0, 0, 0]) + b"".join(
        _typed_definition(wave, 0, root)
        for wave, root in ((1, 48), (1, 60), (2, 40)))

    psg = _note_definition(2, 0, 60)          # wave id 2 = 25% duty square

    header = 0x3C + 128 * 4                      # count + up to 128 entries
    offsets = []
    blob = bytearray()
    for chunk in (direct, ranged, regions, psg):
        offsets.append(header + len(blob))
        blob += chunk

    total = header + len(blob)
    data = bytearray()
    data += _std_header(b"SBNK", total)
    data += b"DATA" + struct.pack("<I", total - 0x10) + b"\x00" * 32
    data += struct.pack("<I", 4)
    for slot in range(128):
        if slot < len(offsets):
            kind = (1, 16, 17, 2)[slot]           # direct, range, regions, PSG
            data += struct.pack("<BHB", kind, offsets[slot], 0)
        else:
            data += struct.pack("<BHB", 0, 0, 0)
    data += blob
    return bytes(data)


def build_kit_sbnk(keys=range(36, 48)) -> bytes:
    """A bank with a drum kit: one instrument whose every key has its own wave.

    That is how a DS game stores its kit (one sample per piece), and it is the
    only thing in the bank that says "these are drums" — so the reader has to
    recognise it from the layout.
    """
    keys = list(keys)
    multisample = bytes([40, 43]) + b"".join(
        _typed_definition(1, 0, 60) for _ in keys[:4])   # four keys, one wave
    kit = bytes([keys[0], keys[-1]]) + b"".join(
        _typed_definition(index, 0, 60) for index, _key in enumerate(keys))
    header = 0x3C + 128 * 4
    blob = bytearray()
    offsets = []
    for chunk in (multisample, kit):
        offsets.append(header + len(blob))
        blob += chunk
    total = header + len(blob)
    data = bytearray()
    data += _std_header(b"SBNK", total)
    data += b"DATA" + struct.pack("<I", total - 0x10) + b"\x00" * 32
    data += struct.pack("<I", 128)
    for slot in range(128):
        if slot == 0:
            data += struct.pack("<BHB", 16, offsets[0], 0)
        elif slot == 9:
            data += struct.pack("<BHB", 16, offsets[1], 0)
        else:
            data += struct.pack("<BHB", 0, 0, 0)
    data += blob
    return bytes(data)


def build_drum_sseq() -> bytes:
    """One melody track and one drum track that uses instrument 9's kit."""
    header_size = 0x1C
    tempo = bytearray([0xFE, 0x07, 0x00]) + bytes([0xE1]) + \
        struct.pack("<H", 140) + bytes([0xFF])
    melody = bytearray([0x81, 0, 0xC1, 100])
    for pitch in (72, 74, 76, 79):
        melody += bytes([pitch, 100]) + _vlq(48)
    melody += bytes([0x94, 0x00, 0x00, 0x00, 0xFF])
    drums = bytearray([0x81, 9])
    for pitch in (36, 42, 38, 42) * 6:
        drums += bytes([pitch, 100]) + _vlq(24)
    drums += bytes([0xFF])
    tempo_offset = 3 * 5
    melody_offset = tempo_offset + len(tempo)
    drum_offset = melody_offset + len(melody)
    definitions = bytearray()
    for number, offset in ((0, tempo_offset), (1, melody_offset),
                           (2, drum_offset)):
        definitions += bytes([0x93, number, offset & 0xFF, (offset >> 8) & 0xFF,
                              (offset >> 16) & 0xFF])
    body = bytes(definitions) + bytes(tempo) + bytes(melody) + bytes(drums)
    total = header_size + len(body)
    data = bytearray(_std_header(b"SSEQ", total))
    data += b"DATA" + struct.pack("<II", total - 0x10, header_size)
    data += body
    return bytes(data)


def write_kit_rom(path: str) -> str:
    """A ROM whose soundtrack has one song playing a real drum kit."""
    sdat = build_sdat(sequences=[("BGM_KIT", build_drum_sseq())],
                      sbnk=build_kit_sbnk())
    return build_rom(path, sdat)


def build_tone_sbnk(root: int = 60) -> bytes:
    """One instrument: a single wave, played over the whole keyboard."""
    direct = _note_definition(0, 0, root)
    header = 0x3C + 128 * 4
    offset = header
    blob = direct
    total = header + len(blob)
    data = bytearray()
    data += _std_header(b"XBNK", total).replace(b"XBNK", b"SBNK")
    data += b"DATA" + struct.pack("<I", total - 0x10) + b"\x00" * 32
    data += struct.pack("<I", 1)
    data += struct.pack("<BHB", 1, offset, 0)
    for _slot in range(127):
        data += struct.pack("<BHB", 0, 0, 0)
    data += blob
    return bytes(data)


def build_tone_sseq(pitch: int = 60, length: int = 384) -> bytes:
    """One track, one long note on instrument 0 — a note you can measure."""
    header_size = 0x1C
    melody = bytearray()
    melody += bytes([0x81, 0])                    # instrument 0
    melody += bytes([0xC1, 127])                  # full track volume
    melody += bytes([pitch, 110]) + build_tone_vlq(length)
    melody += bytes([0xFF])

    definitions = bytearray()
    melody_offset = 2 * 5
    for number, offset in ((0, melody_offset), ):
        definitions += bytes([0x93, number, offset & 0xFF, (offset >> 8) & 0xFF,
                              (offset >> 16) & 0xFF])
    body = bytes(definitions) + bytes([0xFE, 0x01, 0x00]) + bytes(melody)
    total = header_size + len(body)
    data = bytearray()
    data += _std_header(b"SSEQ", total)
    data += b"DATA" + struct.pack("<II", total - 0x10, header_size)
    data += body
    return bytes(data)


def build_tone_vlq(value: int) -> bytes:
    return _vlq(value)


def build_tone_rom(path: str, root: int = 60,
                   pitch: int = 60, rate: int = 16000) -> str:
    """A ROM whose one instrument is a seamless looped sine at a known pitch.

    The tone is two full periods in 64 samples, looped from 0 to 64, so a
    playback that is pitch-correct reproduces exactly ``rate / 32`` Hz. That is
    what makes the sampled renderer measurable instead of merely listenable.
    """
    samples = [int(round(127 + 100 * math.sin(2 * math.pi * index / 32.0)))
               for index in range(64)]
    wave8 = _swav(bytes(samples), 0, rate, looped=True, loop_start=0,
                  samples=64)
    header = 0x3C + 4
    total = header + len(wave8)
    swar = bytearray()
    swar += _std_header(b"SWAR", total)
    swar += b"DATA" + struct.pack("<I", total - 0x10) + b"\x00" * 32
    swar += struct.pack("<I", 1)
    swar += struct.pack("<I", header)
    swar += wave8
    sdat = build_sdat(sequences=[("TONE", build_tone_sseq(pitch))],
                      sbnk=build_tone_sbnk(root), swar=bytes(swar))
    return build_rom(path, sdat)


# ---------------------------------------------------------------------- waves

def _swav(pcm: bytes, wave_type: int, rate: int, looped: bool = False,
          loop_start: int = 0, samples: int = 0) -> bytes:
    """A wave as it sits inside a SWAR: the info struct, then the samples.

    The size fields count 4-byte words like the hardware registers do, and the
    ADPCM state word does not count towards the length.
    (A standalone .swav file wraps these same bytes in a standard header and a
    DATA chunk; inside an archive that wrapper is left off.)
    """
    per_word = (4, 2, 8)[wave_type]
    header_words = 4 if wave_type == 2 else 0
    samples = samples or len(pcm) // (1 if wave_type in (0, 2) else 2)
    length_words = samples // per_word
    # the loop offset counts from the start of the sample, state word included
    loop_word = loop_start // per_word + (1 if wave_type == 2 else 0)
    data = bytearray()
    data += struct.pack("<BBHHHI", wave_type, 1 if looped else 0, rate, 0,
                        loop_word if looped else 0, length_words)
    data += pcm
    assert len(pcm) == length_words * 4 + header_words
    return bytes(data)


_IMA_STEPS = [
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41,
    45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190,
    209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724,
    796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499,
    2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845,
    8630, 9493, 10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385,
    24623, 27086, 29794, 32767]

_IMA_INDEX = [-1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8]


def _ima_decode_nibble(predictor: int, index: int, nibble: int):
    step = _IMA_STEPS[max(0, min(88, index))]
    difference = step >> 3
    if nibble & 1:
        difference += step >> 2
    if nibble & 2:
        difference += step >> 1
    if nibble & 4:
        difference += step
    predictor += -difference if nibble & 8 else difference
    predictor = max(-32768, min(32767, predictor))
    index = max(0, min(88, index + _IMA_INDEX[nibble & 0x07]))
    return predictor, index


def encode_adpcm(samples):
    """Nintendo's IMA ADPCM as the DS stores it.

    One 4-byte state word (16-bit predictor, 16-bit step index), then two samples
    per byte, low nibble first. The caller gets the bytes and what they should
    decode to, which is how the test tells a decoder that reads the state word
    correctly from one that does not.
    """
    out = bytearray()
    decoded = []
    index = 0
    predictor = 0
    out += struct.pack("<hH", predictor, index)
    encoded = []
    for target in samples:
        best = 0
        best_error = None
        best_state = (predictor, index)
        for nibble in range(16):
            value, next_index = _ima_decode_nibble(predictor, index, nibble)
            error = abs(value - target)
            if best_error is None or error < best_error:
                best, best_error, best_state = nibble, error, (value, next_index)
        encoded.append(best)
        predictor, index = best_state
        decoded.append(predictor)
    for offset in range(0, len(encoded), 2):
        high = encoded[offset + 1] if offset + 1 < len(encoded) else 0
        out.append((high << 4) | encoded[offset])        # low nibble first
    return bytes(out), decoded


ADPCM_SAMPLES = [int(9000 * math.sin(2 * math.pi * index / 56.0))
                 for index in range(56)]


def build_swar() -> bytes:
    """Three waves: an 8-bit sine with a loop, a 16-bit square, an ADPCM ramp.

    Real DS banks are mostly ADPCM (type 2), so the archive has to carry one for
    the test to mean anything.
    """
    sine = bytes(int(round(127 + 100 * math.sin(2 * math.pi * index / 32.0)))
                 for index in range(64))
    wave8 = _swav(sine, 0, 16000, looped=True, loop_start=8, samples=64)

    period = [12000] * 6 + [-12000] * 6
    square = b"".join(struct.pack("<h", value) for value in period * 4)
    wave16 = _swav(square, 1, 22050)

    adpcm_bytes, _decoded = encode_adpcm(ADPCM_SAMPLES)
    wave2 = _swav(adpcm_bytes, 2, 32768, looped=True, loop_start=0,
                  samples=len(ADPCM_SAMPLES))

    waves = [wave8, wave16, wave2]
    header = 0x3C + len(waves) * 4
    offsets = []
    position = header
    for wave in waves:
        offsets.append(position)
        position += len(wave)

    total = position
    data = bytearray()
    data += _std_header(b"SWAR", total)
    data += b"DATA" + struct.pack("<I", total - 0x10) + b"\x00" * 32
    data += struct.pack("<I", len(waves))
    for offset in offsets:
        data += struct.pack("<I", offset)
    data += b"".join(waves)
    return bytes(data)


# --------------------------------------------------------------------- the SDAT

def build_short_sseq() -> bytes:
    """A second, deliberately different song: 90 BPM, three notes, no transpose."""
    header_size = 0x1C

    lead = bytearray()
    lead += bytes([0x81, 0])
    for pitch in (62, 65, 69):
        lead += bytes([pitch, 90]) + _vlq(48)
    lead += bytes([0xFF])

    top = bytearray()
    top += bytes([0xFE, 0x03, 0x00])           # tracks 0 and 1 play
    top += bytes([0xE1]) + struct.pack("<H", 90)
    top += bytes([0xFF])

    definitions = bytearray()
    lead_offset = 2 * 5
    top_offset = lead_offset + len(lead)
    for number, offset in ((0, lead_offset), (1, top_offset)):
        definitions += bytes([0x93, number, offset & 0xFF, (offset >> 8) & 0xFF,
                              (offset >> 16) & 0xFF])

    body = bytearray(definitions) + lead + top
    total = header_size + len(body)
    data = bytearray()
    data += _std_header(b"SSEQ", total)
    data += b"DATA" + struct.pack("<II", total - 0x10, header_size)
    data += body
    return bytes(data)


def build_sdat(sequences=None, sbnk: bytes = b"", swar: bytes = b"",
               names=None) -> bytes:
    """Assemble a standard SDAT holding the sequences, a bank and a wave archive.

    ``sequences`` is a list of (name, sseq bytes); the default is one song. Every
    block is written the way the reference documents (and the tools that read real
    archives) lay them out: eight symbol lists, eight INFO part lists, then the
    FAT and the files themselves.
    """
    if sequences is None:
        sequences = [(names[0] if names else "BGM_MAIN", build_sseq())]
    sbnk = sbnk or build_sbnk()
    swar = swar or build_swar()
    files = [blob for _name_text, blob in sequences] + [sbnk, swar]
    bank_file = len(sequences)
    wave_file = len(sequences) + 1
    names = [name for name, _blob in sequences]

    # --- SYMB: a header, then one symbol list per sound type. Only the sequences
    # have names, which is enough to prove the reader follows the offsets.
    list_header = 0x28                      # block header + 8 part offsets
    lists_at = []
    position = list_header
    for index in range(8):
        lists_at.append(position)
        position += 4 + (4 * len(names) if index == 0 else 0)
    strings_at = position
    name_blob = bytearray()
    name_offsets = []
    for name in names:
        name_offsets.append(strings_at + len(name_blob))
        name_blob += name.encode("ascii") + b"\x00"

    symb_size = strings_at + len(name_blob)
    symb = bytearray(b"SYMB" + struct.pack("<I", symb_size))
    symb += struct.pack("<8I", *lists_at)
    symb += struct.pack("<I", len(names))
    for offset in name_offsets:
        symb += struct.pack("<I", offset)
    # Only the sequences are named; the other seven lists exist but are empty.
    symb += struct.pack("<I", 0) * 7
    symb += name_blob

    # --- INFO: sequences (part 0), banks (part 2), wave archives (part 3).
    # Each part is a count followed by *offsets* to the entries; the entries
    # themselves are packed after all eight lists. Every part gets a list, even
    # the empty ones, which is what real archives do.
    counts = [len(sequences), 0, 1, 1, 0, 0, 0, 0]
    lists_at = []
    position = 0x28
    for count in counts:
        lists_at.append(position)
        position += 4 + 4 * count
    entries_at = position
    seq_entries_at = entries_at
    bank_entry_at = seq_entries_at + 10 * len(sequences)   # <3H4B each
    wave_entry_at = bank_entry_at + 12                     # <HH4h
    info_size = wave_entry_at + 4                          # <HH

    info = bytearray(b"INFO" + struct.pack("<I", info_size))
    info += struct.pack("<8I", *lists_at)
    for index, count in enumerate(counts):
        info += struct.pack("<I", count)
        for entry in range(count):
            if index == 0:
                info += struct.pack("<I", seq_entries_at + 10 * entry)
            elif index == 2:
                info += struct.pack("<I", bank_entry_at)
            else:
                info += struct.pack("<I", wave_entry_at)
    for index in range(len(sequences)):
        info += struct.pack("<3H4B", index, 0, 0, 100, 64, 50, 0)
    info += struct.pack("<HH4h", bank_file, 0, 0, -1, -1, -1)
    info += struct.pack("<HH", wave_file, 0)

    # --- FAT: where each payload lives, once everything above is placed.
    # Real archives pad every file to 0x20 bytes; do the same.
    fat_size = 0x0C + 0x10 * len(files)
    symb_off = 0x40
    info_off = symb_off + len(symb)
    fat_off = info_off + len(info)
    file_off = fat_off + fat_size
    file_off += (-file_off) % 0x20

    padded = []
    position = file_off
    for payload in files:
        padded.append((position, payload))
        position += len(payload) + ((-len(payload)) % 0x20)

    total = position
    fat = bytearray(b"FAT " + struct.pack("<I", fat_size))
    fat += struct.pack("<I", len(files))
    for offset, payload in padded:
        fat += struct.pack("<II", offset, len(payload)) + b"\x00" * 8

    blobs = bytearray()                     # file 0 starts at file_off
    for offset, payload in padded:
        blobs += b"\x00" * (offset - (file_off + len(blobs)))
        blobs += payload
    blobs += b"\x00" * (total - (file_off + len(blobs)))

    out = bytearray()
    out += _std_header(b"SDAT", total, blocks=3, header_size=0x40)
    out += struct.pack("<8I", symb_off, len(symb), info_off, len(info),
                       fat_off, len(fat), file_off, len(blobs))
    out += b"\x00" * (0x40 - len(out))
    out += symb + info + fat
    out += b"\x00" * (file_off - len(out))
    out += blobs
    return bytes(out)


# ---------------------------------------------------------------------- the ROM

def build_rom(path: str, sdat: bytes = b"", extra: bytes = b"") -> str:
    """Write a minimal .nds whose file table holds one file: the SDAT.

    ``extra`` puts a second file into the table — another SDAT, if the test wants
    a ROM like New Super Mario Bros., which ships a soundtrack archive *and* a
    mini-games archive, and where reading only the first one gives a song list of
    nothing but jingles.
    """
    sdat = sdat or build_sdat()
    files = [sdat] + ([extra] if extra else [])
    header_size = 0x4000
    fat_off = 0x200
    fat_size = 8 * len(files)
    file_off = fat_off + 0x100

    rom = bytearray(header_size)
    rom[0:12] = b"CHIP8BIT TEST"
    rom[0x0C:0x10] = b"ABCE"
    rom[0x20:0x24] = b"ABCD"                      # maker code
    struct.pack_into("<I", rom, 0x40, header_size)     # ARM9 rom offset
    struct.pack_into("<I", rom, 0x44, 4)               # ARM9 entry
    struct.pack_into("<I", rom, 0x48, fat_off)
    struct.pack_into("<I", rom, 0x4C, fat_size)
    struct.pack_into("<I", rom, 0x50, fat_off + 0x100)  # ARM9 ram offset
    struct.pack_into("<I", rom, 0x54, 4)
    struct.pack_into("<I", rom, 0x68, 0)               # no banner
    struct.pack_into("<I", rom, 0x80, header_size +
                     sum(len(blob) for blob in files))

    rom += b"\x00" * (fat_off - len(rom))
    at = file_off
    for blob in files:
        rom += struct.pack("<II", at, at + len(blob))
        at += len(blob)
    rom += b"\x00" * (file_off - len(rom))
    for blob in files:
        rom += blob

    with open(path, "wb") as handle:
        handle.write(bytes(rom))
    return path


def write_two_archives(path: str) -> str:
    """A ROM with two sound archives, the way New Super Mario Bros. has them.

    The first archive is the small one (one jingle), the second holds the songs.
    A reader that stops at the first SDAT it finds will list the jingle and
    nothing else — which is the bug this file exists to catch.
    """
    jingles = build_sdat(sequences=[("NCS_BGM_MINIGAME", build_sseq())])
    music = build_sdat(sequences=[("BGM_MAIN", build_sseq()),
                                  ("BGM_BOSS", build_short_sseq())])
    return build_rom(path, jingles, extra=music)


def write(path: str, two_songs: bool = False) -> str:
    """Build the test ROM; with ``two_songs`` it holds a second, different song."""
    if two_songs:
        sdat = build_sdat(sequences=[("BGM_MAIN", build_sseq()),
                                     ("BGM_BOSS", build_short_sseq())])
        return build_rom(path, sdat)
    return build_rom(path)


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "test.nds"
    print(write(target))
