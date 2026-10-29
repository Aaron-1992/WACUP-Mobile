"""Export the arrangement as a VGM log, so it plays in VGM-aware players.

A VGM is just a register-write timeline: exactly what a console would do, and the
most literal proof that the arrangement fits the hardware. Two honest limitations,
both reported by the tool:

* VGM can carry the NES APU (command 0xB4, clock field 0x84) and the SN76489
  (0x50), but it has no command for the VRC6, MMC5, FDS or Namco 163 — those
  chips only exist inside NSFs and emulators. Notes on those channels stay in the
  WAV rendering and are left out of the log.
* The delta channel is driven as a direct DAC load (register 0x4011), i.e. an
  unpitched percussive click, because we do not ship a sampled drum ROM.
"""

import struct
from typing import Dict, List, Tuple

from .model import Note
from .render import note_frequency

CPU_CLOCK = 1789773.0
PSG_CLOCK = 3579545
SAMPLES_PER_SECOND = 44100
FRAME = 735


def _timer(frequency: float, divisor: float) -> int:
    if frequency <= 0:
        return 0
    value = int(round(CPU_CLOCK / (divisor * frequency))) - 1
    return max(0, min(0x7FF, value))


def _pulse_events(note: Note, base: int) -> List[Tuple[int, int, int]]:
    """(address, data) pairs for the 2A03's pulse registers."""
    frequency = note_frequency(note.pitch + note.bend)
    timer = _timer(frequency, 16.0)
    duty = {0.125: 0, 0.25: 1, 0.5: 2, 0.75: 3}.get(round(note.duty, 3), 2)
    volume = max(1, min(15, note.volume))
    return [
        (base + 0, (duty << 6) | 0x10 | volume),
        (base + 1, 0x08),                       # sweep off
        (base + 2, timer & 0xFF),
        (base + 3, ((timer >> 8) & 0x07) | 0x08),
    ]


def _pulse_off(base: int) -> List[Tuple[int, int, int]]:
    return [(base + 0, 0x10)]


def _triangle_events(note: Note) -> List[Tuple[int, int, int]]:
    timer = _timer(note_frequency(note.pitch + note.bend), 32.0)
    return [
        (0x08, 0xFF),
        (0x0A, timer & 0xFF),
        (0x0B, ((timer >> 8) & 0x07) | 0x08),
    ]


def _noise_events(note: Note) -> List[Tuple[int, int, int]]:
    period = max(0, min(15, note.noise_period))
    mode = 0x80 if note.noise_short else 0x00
    return [
        (0x0C, 0x10 | max(1, min(15, note.volume))),
        (0x0E, mode | period),
        (0x0F, 0x08),
    ]


def _psg_silence(channel: int) -> List[Tuple[int, int]]:
    return [bytes([0x50, 0x90 | (channel << 5) | 0x0F])]


def _psg_note(note: Note, channel: int) -> List[bytes]:
    frequency = note_frequency(note.pitch + note.bend)
    period = int(round(PSG_CLOCK / (32.0 * max(1.0, frequency))))
    period = max(1, min(1023, period))
    attenuation = max(0, min(15, 15 - note.volume))
    return [
        bytes([0x50, 0x80 | (channel << 5) | (period & 0x0F)]),
        bytes([0x50, (period >> 4) & 0x3F]),
        bytes([0x50, 0x90 | (channel << 5) | attenuation]),
    ]


def _dmc_events(note: Note) -> List[Tuple[int, int, int]]:
    """Direct DAC loads: a decaying thump with no sample ROM needed.

    Returns (samples_from_note_start, register, value).
    """
    return [
        (0, 0x10, 0x0F),          # disable IRQ/loop, fastest rate
        (0, 0x11, 0x60),          # first DAC level
        (FRAME // 2, 0x11, 0x38),
        (FRAME, 0x11, 0x18),
        (FRAME * 2, 0x11, 0x00),
    ]


def _collect(notes: List[Note], channels) -> Tuple[List[tuple], int, List[str]]:
    """Turns notes into (sample_time, order, bytes, chip) events."""
    skipped = set()
    used = set()
    events: List[tuple] = []
    sample_rate = SAMPLES_PER_SECOND

    for note in notes:
        start = int(round(note.start * sample_rate))
        end = int(round(note.end() * sample_rate))
        channel = note.channel
        used.add(channel)

        if channel == "pulse1":
            events.append((start, 0, _nes(_pulse_events(note, 0x00)), "nes"))
            events.append((end, 1, _nes(_pulse_off(0x00)), "nes"))
        elif channel == "pulse2":
            events.append((start, 0, _nes(_pulse_events(note, 0x04)), "nes"))
            events.append((end, 1, _nes(_pulse_off(0x04)), "nes"))
        elif channel == "triangle":
            events.append((start, 0, _nes(_triangle_events(note)), "nes"))
            events.append((end, 1, _nes([(0x08, 0x00)]), "nes"))
        elif channel == "noise":
            events.append((start, 0, _nes(_noise_events(note)), "nes"))
            events.append((end, 1, _nes([(0x0C, 0x10)]), "nes"))
        elif channel == "dmc":
            for offset, address, value in _dmc_events(note):
                events.append((start + offset, 0, _nes([(address, value)]), "nes"))
        elif channel.startswith("psg"):
            index = int(channel[-1]) - 1
            events.append((start, 0, _psg_note(note, index), "psg"))
            events.append((end, 1, _psg_silence(index), "psg"))
        else:
            skipped.add(channel)

    events.sort(key=lambda item: (item[0], item[1]))
    return events, sample_rate, sorted(skipped)


def _nes(writes: List[Tuple[int, int]]) -> bytes:
    out = bytearray()
    for address, value in writes:
        out += bytes([0xB4, address & 0xFF, value & 0xFF])
    return bytes(out)


def write_vgm(path: str, notes: List[Note], channels, duration: float,
              extensions) -> List[str]:
    events, _rate, skipped = _collect(notes, channels)

    data = bytearray()
    position = 0
    for time, _order, payload, _chip in events:
        wait = max(0, time - position)
        while wait > 0:
            if wait >= 65535:
                data += bytes([0x61, 0xFF, 0xFF])
                wait -= 65535
            elif wait == FRAME:
                data.append(0x62)
                wait -= FRAME
            elif wait > FRAME and wait % FRAME == 0:
                data.append(0x62)
                wait -= FRAME
            elif 1 <= wait <= 16:
                data.append(0x70 + wait - 1)
                wait = 0
            else:
                chunk = min(65535, wait)
                data += bytes([0x61, chunk & 0xFF, (chunk >> 8) & 0xFF])
                wait -= chunk
        data += payload
        position = time

    total_samples = max(position, int(duration * SAMPLES_PER_SECOND)) + FRAME * 2
    data.append(0x66)                       # end of stream

    header = bytearray(0x100)
    header[0x00:0x04] = b"Vgm "
    struct.pack_into("<I", header, 0x04, 0x100 - 0x04 + len(data) - 4)  # EOF offset
    struct.pack_into("<I", header, 0x08, 0x171)
    if any(chip == "psg" for _t, _o, _p, chip in events):
        struct.pack_into("<I", header, 0x0C, PSG_CLOCK)     # SN76489
    struct.pack_into("<I", header, 0x18, total_samples)
    struct.pack_into("<I", header, 0x24, SAMPLES_PER_SECOND)
    struct.pack_into("<I", header, 0x34, 0x100 - 0x34)      # data offset
    struct.pack_into("<I", header, 0x84, int(CPU_CLOCK))    # NES APU clock

    with open(path, "wb") as handle:
        handle.write(bytes(header))
        handle.write(bytes(data))

    messages = []
    if skipped:
        messages.append(
            "VGM cannot address %s: those channels are in the WAV only"
            % ", ".join(skipped))
    return messages
