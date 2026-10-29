"""The built-in demo tune: a synthetic "Genesis style" Standard MIDI File.

The tune is deliberately busier than an NES: six parts, overlapping triads in two
of them, a bass line, a lead with a pitch bend and vibrato, and a drum track. That
is enough to exercise every rule in the arranger (direct placement, overflow onto
spare channels, channel sharing, percussion mapping) without shipping copyrighted
music in the repository.
"""

import struct

DIVISION = 480
BPM = 120
BEAT = DIVISION                      # ticks per beat
BAR = BEAT * 4


def vlq(value: int) -> bytes:
    out = bytearray([value & 0x7F])
    value >>= 7
    while value:
        out.insert(0, 0x80 | (value & 0x7F))
        value >>= 7
    return bytes(out)


class Track:
    def __init__(self, name: str):
        self.name = name
        self.events = []          # (tick, bytes)

    def add(self, tick: int, payload: bytes) -> None:
        self.events.append((tick, payload))

    def note(self, channel: int, start: int, length: int, pitch: int, velocity=100):
        self.add(start, bytes([0x90 | channel, pitch & 0x7F, velocity & 0x7F]))
        self.add(start + length, bytes([0x80 | channel, pitch & 0x7F, 0x40]))

    def program(self, channel: int, number: int) -> None:
        self.add(0, bytes([0xC0 | channel, number & 0x7F]))

    def control(self, channel: int, controller: int, value: int, tick: int = 0) -> None:
        self.add(tick, bytes([0xB0 | channel, controller & 0x7F, value & 0x7F]))

    def bend(self, channel: int, value: int, tick: int) -> None:
        value = max(0, min(16383, value))
        self.add(tick, bytes([0xE0 | channel, value & 0x7F, (value >> 7) & 0x7F]))

    def serialize(self, running_status: bool = False) -> bytes:
        body = bytearray()
        body += b"\x00\xFF\x03" + vlq(len(self.name)) + self.name.encode("ascii")
        last_tick = 0
        previous_status = 0
        for tick, payload in sorted(self.events, key=lambda item: item[0]):
            body += vlq(tick - last_tick)
            last_tick = tick
            status = payload[0]
            if running_status and status < 0xF0 and status == previous_status:
                body += payload[1:]
            else:
                body += payload
            if status < 0xF0:
                previous_status = status
            else:
                previous_status = 0
        body += b"\x00\xFF\x2F\x00"
        return b"MTrk" + struct.pack(">I", len(body)) + bytes(body)


def build() -> bytes:
    tracks = []

    # 1. lead: eighth notes, with a bend and vibrato on the long final note
    lead = Track("lead")
    lead.program(0, 81)
    lead.control(0, 7, 110)
    scale = [72, 74, 76, 79, 81, 79, 76, 74]
    for index, pitch in enumerate(scale * 2):
        lead.note(0, index * BEAT // 2, BEAT // 2 - 10, pitch,
                  90 + (index % 3) * 8)
    lead.note(0, 8 * BEAT, 4 * BEAT, 84, 110)
    lead.bend(0, 11000, 8 * BEAT + BEAT)
    lead.bend(0, 8192, 8 * BEAT + BEAT * 2)
    lead.control(0, 1, 90, 8 * BEAT + BEAT)
    tracks.append(lead)

    # 2. chords: sustained triads, the part that has to share a channel
    chords = Track("chords")
    chords.program(1, 80)
    progression = [(60, 64, 67), (57, 60, 64), (53, 57, 60), (55, 59, 62)]
    for bar, triad in enumerate(progression):
        for pitch in triad:
            chords.note(1, bar * BAR, BAR - 20, pitch, 78)
    tracks.append(chords)

    # 3. bass: triangle territory
    bass = Track("bass")
    bass.program(2, 38)
    roots = [36, 33, 29, 31]
    for bar, root in enumerate(roots):
        for beat in range(4):
            bass.note(2, bar * BAR + beat * BEAT, BEAT - 20,
                      root + (12 if beat == 3 else 0), 100)
    tracks.append(bass)

    # 4. counter melody, written with running status to exercise the parser
    counter = Track("counter")
    counter.program(3, 82)
    for index in range(16):
        pitch = [64, 67, 71, 72][index % 4]
        counter.note(3, index * BEAT, BEAT - 30, pitch, 72)
    tracks.append(counter)

    # 5. pad: four-note chords, the part that will not fit on a bare NES
    pad = Track("pad")
    pad.program(4, 89)
    for bar in range(4):
        for pitch in (48, 55, 60, 64, 67):
            pad.note(4, bar * BAR, BAR - 40, pitch, 60)
    tracks.append(pad)

    # 6. drums, general MIDI percussion
    drums = Track("drums")
    for step in range(64):
        tick = step * BEAT // 4
        if step % 4 == 0:
            drums.note(9, tick, 60, 36, 120)        # kick
        if step % 8 == 4:
            drums.note(9, tick, 60, 38, 110)        # snare
        drums.note(9, tick, 30, 42, 70 + (step % 2) * 20)   # hat
    tracks.append(drums)

    track_bytes = b"".join(t.serialize(running_status=(t.name == "counter"))
                           for t in tracks)

    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), DIVISION)
    tempo = Track("tempo")
    tempo.add(0, b"\xFF\x51\x03" + struct.pack(">I", 500000)[1:])   # 120 BPM
    tempo.add(0, b"\xFF\x58\x04\x04\x02\x18\x08")               # 4/4
    tempo.add(0, b"\xFF\x59\x02\x02\x00")                        # D major
    return header + tempo.serialize() + track_bytes


def build_fast() -> bytes:
    """A fast tune, the way real game music is written.

    At 226 BPM a sixteenth note is 66 ms and a thirty-second note is 33 ms, which
    is shorter than the "minimum note" the arranger used to insist on: this file
    is the regression test for "the tune must survive the tempo". It also has a
    chord part, a bass and drums, so the channel spreading gets exercised too.
    """
    import struct

    division = 480
    # 226 BPM, the tempo of a certain athletic theme
    tempo_us = 265487

    def bar(n):
        return n * division * 4

    tracks = []

    # 1. melody: thirty-second notes, six per beat at this tempo are 33 ms long
    lead = Track("melody")
    lead.program(0, 80)
    lead.control(0, 7, 112)
    runs = [72, 74, 76, 79, 81, 79, 76, 74, 72, 71, 72, 74]
    step = division // 8                      # 32nd note
    for index in range(96):
        pitch = runs[index % len(runs)] + (12 if index // 24 == 2 else 0)
        lead.note(0, index * step, step - 8, pitch, 96 + (index % 3) * 6)
    tracks.append(lead)

    # 2. counter melody: a second line, so the channels have to be shared out
    counter = Track("counter")
    counter.program(1, 82)
    for index in range(48):
        counter.note(1, index * step * 2, step * 2 - 10,
                     [60, 64, 67, 64][index % 4], 80)
    tracks.append(counter)

    # 3. bass line on the triangle
    bass = Track("bass")
    bass.program(2, 33)
    for index in range(24):
        bass.note(2, index * step * 4, step * 4 - 20,
                  [36, 36, 33, 33, 29, 29, 31, 31][index % 8], 104)
    tracks.append(bass)

    # 4. chords: four voices at once, a real chord and not an arpeggio
    chords = Track("chords")
    chords.program(3, 89)
    progression = [(60, 64, 67, 72), (57, 60, 64, 69),
                   (53, 57, 60, 65), (55, 59, 62, 67)]
    for index, triad in enumerate(progression * 6):
        for pitch in triad:
            chords.note(3, index * step * 4, step * 4 - 30, pitch, 70)
    tracks.append(chords)

    # 5. drums
    drums = Track("drums")
    for index in range(96):
        tick = index * step
        if index % 8 == 0:
            drums.note(9, tick, 40, 36, 120)      # kick
        if index % 8 == 4:
            drums.note(9, tick, 40, 38, 108)      # snare
        drums.note(9, tick, 20, 42, 66 + (index % 2) * 24)   # 20 ms hat
    tracks.append(drums)

    track_bytes = b"".join(t.serialize() for t in tracks)
    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), division)
    tempo = Track("tempo")
    tempo.add(0, b"\xFF\x51\x03" + struct.pack(">I", tempo_us)[1:])
    tempo.add(0, b"\xFF\x58\x04\x04\x02\x18\x08")
    return header + tempo.serialize() + track_bytes


def write(path: str) -> str:
    with open(path, "wb") as handle:
        handle.write(build())
    return path


def write_fast(path: str) -> str:
    with open(path, "wb") as handle:
        handle.write(build_fast())
    return path


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "test-song.mid"
    write(target)
    print("wrote %s" % target)
