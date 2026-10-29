"""VGM / VGZ importer: Genesis YM2612 FM plus SN76489 PSG.

Genesis music in the wild is almost always VGM (or GYM, see gym.py), so this is
the "game files" path. The importer replays the register stream, watching key-on
and key-off writes and the fnum/block registers, and turns that into notes with
real pitch and loudness — no approximation of the original tuning.
"""

import gzip
import math
import struct
from typing import List, Optional

from ..model import Note, Song
from . import register

EXTENSIONS = (".vgm", ".vgz")
LABEL = "VGM / VGZ (Genesis YM2612 + SN76489)"


# ------------------------------------------------------------------ plumbing

def _open(path: str) -> bytes:
    with open(path, "rb") as handle:
        head = handle.read(2)
    if head == b"\x1f\x8b":
        with gzip.open(path, "rb") as inner:
            return inner.read()
    with open(path, "rb") as handle:
        return handle.read()


def fm_frequency(fnum: int, block: int, clock: float) -> float:
    """The YM2612 phase increment, expressed as Hz."""
    if fnum <= 0:
        return 0.0
    return (clock / 144.0) * fnum * (2.0 ** (block - 20))


def frequency_to_pitch(frequency: float) -> float:
    if frequency <= 0:
        return 0.0
    return 69.0 + 12.0 * math.log2(frequency / 440.0)


class GenesisTracker:
    """Accumulates notes from a YM2612 + SN76489 register stream."""

    def __init__(self, ym_clock: float = 7670453.0, psg_clock: float = 3579545.0):
        self.ym_clock = ym_clock or 7670453.0
        self.psg_clock = psg_clock or 3579545.0
        self.samples = 0
        self.notes: List[Note] = []
        self.warnings: List[str] = []

        self.fm_fnum = [0] * 6
        self.fm_block = [0] * 6
        self.fm_tl = [127] * 6
        self.fm_active = [None] * 6
        self.dac_enabled = False

        self.psg_period = [0] * 4
        self.psg_att = [15] * 4
        self.psg_latch = 0
        self.psg_active = [None] * 4
        self.psg_is_noise = [False] * 4

    # ---- time

    @property
    def seconds(self) -> float:
        return self.samples / 44100.0

    def wait(self, samples: int) -> None:
        self.samples += max(0, samples)

    # ---- YM2612

    def ym_write(self, port: int, register: int, value: int) -> None:
        register &= 0xFF
        value &= 0xFF
        base = port * 3

        if register == 0x28:
            channel = (value >> 4) & 0x07
            operators = value & 0x0F
            if channel < 6:
                if operators == 0:
                    self._close_fm(channel)
                else:
                    self._open_fm(channel)
            return

        if register == 0x2B:
            self.dac_enabled = bool(value & 0x80)
            return

        if 0xA0 <= register <= 0xA2:
            channel = base + (register - 0xA0)
            if channel < 6:
                self.fm_fnum[channel] = (self.fm_fnum[channel] & 0x700) | value
            return

        if 0xA4 <= register <= 0xA6:
            channel = base + (register - 0xA4)
            if channel < 6:
                self.fm_fnum[channel] = (self.fm_fnum[channel] & 0xFF) | ((value & 0x07) << 8)
                self.fm_block[channel] = (value >> 3) & 0x07
                if self.fm_active[channel] is not None:
                    # a pitch change while held: end the note and start a new one
                    self._close_fm(channel)
                    self._open_fm(channel)
            return

        if 0x40 <= register <= 0x4F:
            # total level of operator 0, which sets how loud the channel is
            offset = (register - 0x40) % 4
            if offset == 0:
                channel = base + ((register - 0x40) // 4)
                if channel < 6:
                    self.fm_tl[channel] = value & 0x7F
            return

    def _open_fm(self, channel: int) -> None:
        if self.fm_active[channel] is not None:
            self._close_fm(channel)
        frequency = fm_frequency(self.fm_fnum[channel], self.fm_block[channel], self.ym_clock)
        if frequency <= 0:
            return
        pitch = frequency_to_pitch(frequency)
        if pitch < 12 or pitch > 120:
            return
        attenuation = self.fm_tl[channel] * 0.75       # TL is 0.75 dB per step
        velocity = int(127 * (10 ** (-attenuation / 20.0)))
        velocity = max(10, min(127, velocity))
        drum = channel == 5 and self.dac_enabled
        self.fm_active[channel] = {
            "start": self.seconds,
            "pitch": pitch,
            "velocity": velocity,
            "drum": drum,
        }

    def _close_fm(self, channel: int) -> None:
        info = self.fm_active[channel]
        if info is None:
            return
        self.fm_active[channel] = None
        end = self.seconds
        duration = end - info["start"]
        if duration < 0.02:
            return
        self.notes.append(Note(
            start=info["start"],
            dur=duration,
            pitch=int(round(info["pitch"])),
            velocity=info["velocity"],
            part=channel,                 # FM channel 0..5
            role="drum" if info["drum"] else "melody",
            program=80 + channel,
        ))

    # ---- SN76489

    def psg_write(self, value: int) -> None:
        value &= 0xFF
        if value & 0x80:                       # latch byte
            self.psg_latch = (value >> 5) & 0x03
            is_volume = bool(value & 0x10)
            self.psg_is_noise[self.psg_latch] = self.psg_latch == 3
            if is_volume:
                self._set_psg_volume((value & 0x0F))
            else:
                self.psg_period[self.psg_latch] = \
                    (self.psg_period[self.psg_latch] & 0x3F0) | (value & 0x0F)
                self._psg_retune()
        else:
            if self.psg_is_noise[self.psg_latch]:
                return                          # noise mode byte: ignore for pitch
            if self.psg_latch == 3:
                return
            self.psg_period[self.psg_latch] = \
                (self.psg_period[self.psg_latch] & 0x00F) | ((value & 0x3F) << 4)
            self._psg_retune()

    def _set_psg_volume(self, attenuation: int) -> None:
        channel = self.psg_latch
        self.psg_att[channel] = attenuation & 0x0F
        if self.psg_att[channel] >= 15:
            self._close_psg(channel)
        elif self.psg_active[channel] is not None:
            self.psg_active[channel]["velocity"] = self._psg_velocity(channel)

    def _psg_velocity(self, channel: int) -> int:
        attenuation = self.psg_att[channel] * 2.0        # 2 dB per step
        return max(10, min(127, int(127 * (10 ** (-attenuation / 20.0)))))

    def _psg_retune(self) -> None:
        channel = self.psg_latch
        if channel == 3:
            return
        period = self.psg_period[channel]
        if self.psg_att[channel] >= 15:
            return
        if self.psg_active[channel] is not None:
            self._close_psg(channel)
        self._open_psg(channel)

    def _open_psg(self, channel: int) -> None:
        period = self.psg_period[channel]
        if period <= 1:
            return
        frequency = self.psg_clock / (32.0 * period)
        pitch = frequency_to_pitch(frequency)
        if pitch < 12 or pitch > 120:
            return
        self.psg_active[channel] = {
            "start": self.seconds,
            "pitch": pitch,
            "velocity": self._psg_velocity(channel),
        }

    def _close_psg(self, channel: int) -> None:
        info = self.psg_active[channel]
        if info is None:
            return
        self.psg_active[channel] = None
        duration = self.seconds - info["start"]
        if duration < 0.02:
            return
        self.notes.append(Note(
            start=info["start"],
            dur=duration,
            pitch=int(round(info["pitch"])),
            velocity=info["velocity"],
            part=6 + channel,             # PSG channels 6..9
            role="drum" if channel == 3 else "melody",
            program=90 + channel,
        ))

    def finish(self) -> List[Note]:
        for channel in range(6):
            self._close_fm(channel)
        for channel in range(4):
            self._close_psg(channel)
        # The PSG noise channel has no pitch of its own; treat it as percussion.
        for note in self.notes:
            if note.part == 9:
                note.role = "drum"
                note.pitch = 38
        return sorted(self.notes, key=lambda n: n.start)


# -------------------------------------------------------------------- parsing

def read(path: str) -> Song:
    data = _open(path)
    song = Song(source_format="vgm", source_path=path)

    if data[:4] != b"Vgm ":
        song.add_warning("missing VGM signature")
        return song

    def u32(offset: int) -> int:
        if offset + 4 > len(data):
            return 0
        return struct.unpack("<I", data[offset:offset + 4])[0]

    ym_clock = u32(0x2C)
    psg_clock = u32(0x0C)
    data_offset = u32(0x34) or 0x40
    if data_offset < 0x40:
        data_offset = 0x40

    tracker = GenesisTracker(ym_clock, psg_clock)
    pos = data_offset
    length = len(data)

    def need(count: int) -> bool:
        return pos + count <= length

    while pos < length:
        command = data[pos]
        pos += 1

        if command == 0x66:                          # end of stream
            break
        if 0x70 <= command <= 0x7F:
            tracker.wait((command & 0x0F) + 1)
            continue
        if command == 0x61:
            if not need(2):
                break
            tracker.wait(struct.unpack("<H", data[pos:pos + 2])[0])
            pos += 2
            continue
        if command == 0x62:
            tracker.wait(735)
            continue
        if command == 0x63:
            tracker.wait(882)
            continue
        if command == 0x50:
            if not need(1):
                break
            tracker.psg_write(data[pos])
            pos += 1
            continue
        if command in (0x52, 0x53):
            if not need(2):
                break
            tracker.ym_write(1 if command == 0x53 else 0, data[pos], data[pos + 1])
            pos += 2
            continue
        if command in (0x51, 0x55, 0x5A, 0x5C, 0x5E):
            pos += 2                                 # other FM chips: skip the write
            continue
        if command == 0x4F or command == 0x30:
            pos += 1
            continue
        if 0x80 <= command <= 0x8F:                  # YM2612 DAC write + short wait
            tracker.wait(command & 0x0F)
            continue
        if command == 0x67:                          # data block
            if not need(6):
                break
            _type = data[pos]
            size = struct.unpack("<I", data[pos + 1:pos + 5])[0]
            pos += 6 + size
            continue
        if command == 0x68:
            pos += 11
            continue
        if 0x90 <= command <= 0x95:
            sizes = {0x90: 4, 0x91: 4, 0x92: 5, 0x93: 10, 0x94: 1, 0x95: 4}
            pos += sizes[command]
            continue
        if command in (0xA0, 0xA5):
            pos += 2
            continue
        if 0xC0 <= command <= 0xDF:
            pos += 3
            continue
        if 0xE0 <= command <= 0xFF:
            pos += 4
            continue

        song.add_warning("unsupported VGM command 0x%02X at byte %d; stopping" %
                         (command, pos - 1))
        break

    song.notes = tracker.finish()
    song.refresh_duration()

    if not song.notes:
        song.add_warning("no notes recovered — is this a Genesis VGM "
                         "(YM2612/SN76489), or another chip family?")
    return song


register("vgm", LABEL)(read)
