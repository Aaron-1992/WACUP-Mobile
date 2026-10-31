"""The game's own instruments, played back instead of imitated.

An 8-bit conversion replaces a DS bank's samples with pulses and a triangle, and
that is the point of it — but then "it sounds nothing like the song" is sometimes
a fair complaint, because the piano, the strings and the brass *were* samples and
no pulse wave is a piano.

This module keeps them. Every note becomes the archive's own SWAV, resampled to
its pitch, looped where the sample loops, shaped by the bank's ADSR bytes and
panned where the bank pans it; all the tracks play at once, because there is no
four-voice chip to fit them into. The result is the soundtrack, not a cover of
it: the same notes, at the game's tempo, on the game's instruments.

What it is not: the DS's exact hardware envelope curve. The ADSR bytes of an SBNK
are rates against a curve table; they are mapped to times here, which gets the
shape right (an attack that is a millisecond or a fifth of a second, a decay to a
sustain level, a release) without pretending to be bit-exact. Pitch, looping and
timbre *are* exact: they are the sample played at 2^((note-root)/12).
"""

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from . import mix, nds
from .model import Note, Song

#: The DS's own output rate. Rendering there means a note at its recorded pitch
#: is a straight copy of the sample, with no resampling error at all.
NATIVE_RATE = 32768

#: Envelope segments, from the bank's 0..127 rate bytes. A rate of 127 is
#: instant; 0 is the slowest setting the hardware can express.
ATTACK_FAST, ATTACK_SLOW = 0.0006, 0.320
DECAY_FAST, DECAY_SLOW = 0.0020, 1.200
RELEASE_FAST, RELEASE_SLOW = 0.0020, 0.950

BLOCK = 24               # samples per envelope step; cheap, and still smooth


@dataclass
class SampleOptions:
    """How to render, in terms the window and the command line already use."""

    rate: int = NATIVE_RATE
    gain: float = 0.9
    stereo: bool = True
    echo: bool = False
    limit: bool = True
    compress: bool = True
    lowpass: bool = False
    max_seconds: float = 0.0


@dataclass
class SampleRender:
    """What came back: the audio, and what it did and did not have samples for."""

    pcm: bytes = b""
    seconds: float = 0.0
    rate: int = NATIVE_RATE
    voices: int = 0
    notes_played: int = 0
    notes_skipped: int = 0
    synthetic: int = 0                 # notes whose instrument is a PSG square
    instruments: int = 0
    drums: int = 0
    channels: int = 1                  # 2 when stereo: the PCM is interleaved
    tracks: Dict[str, List[Note]] = None


# ---------------------------------------------------------------- the bank

class Bank:
    """One SBNK plus the wave archives it points at, ready to play notes."""

    def __init__(self, archive: "nds.Archive", bank_index: int):
        if not (0 <= bank_index < len(archive.banks)):
            raise nds.NdsError("no bank %d in this archive (it has %d)"
                               % (bank_index, len(archive.banks)))
        self.archive = archive
        self.bank_index = bank_index
        entry = archive.banks[bank_index]
        self.wave_ids = list(entry.wave_archives)
        self.instruments = nds.read_bank(
            entry.sbnk, self.wave_ids[0] if self.wave_ids else 0)
        self.kits = nds.drum_programs(
            entry.sbnk, self.wave_ids[0] if self.wave_ids else 0)
        self.waves: Dict[int, Dict[int, dict]] = {}
        for archive_id in self.wave_ids:
            blob = archive.waves.get(archive_id)
            if not blob:
                continue
            try:
                self.waves[archive_id] = nds.read_wave_archive(blob)
            except nds.NdsError:
                continue

    # --- where a slot's sample lives

    def _archive(self, archive_id: int) -> Dict[int, dict]:
        """The wave archive a zone names — by id, or by its place in the bank."""
        if archive_id in self.waves:
            return self.waves[archive_id]
        # most banks name the archive by its index in their own four-entry list
        if 0 <= archive_id < len(self.wave_ids):
            other = self.wave_ids[archive_id]
            if other in self.waves:
                return self.waves[other]
        if len(self.waves) == 1:
            # one archive: nothing to confuse it with (and a bank merged out of
            # two SDATs keeps its own numbering, which cannot be resolved here)
            return next(iter(self.waves.values()))
        return {}

    def zone_for(self, slot: int, pitch: int
                 ) -> Tuple[Optional[nds.Zone], Optional[dict]]:
        """The zone that plays this key on this instrument, and its decoded wave."""
        if not (0 <= slot < len(self.instruments)):
            return None, None
        zones = self.instruments[slot]
        if not zones:
            return None, None
        chosen = None
        for zone in zones:
            if zone.low <= pitch <= zone.high:
                chosen = zone
                break
        if chosen is None:
            chosen = min(zones, key=lambda z: abs((z.low + z.high) / 2.0 - pitch))
        if chosen.psg:
            return chosen, None
        wave = self._archive(chosen.archive).get(chosen.wave)
        if not wave or not wave.get("pcm"):
            return chosen, None
        return chosen, wave

    def instrument_count(self) -> int:
        return sum(1 for zones in self.instruments if zones)


# ----------------------------------------------------------------- envelopes

def _time(rate_byte: int, fast: float, slow: float) -> float:
    """A bank's 0..127 rate byte as a time in seconds (127 = instant)."""
    clamped = max(0, min(127, int(rate_byte)))
    share = (127 - clamped) / 127.0
    return fast + (slow - fast) * (share ** 2)


def envelope_for(zone: nds.Zone) -> Tuple[float, float, float, float, float]:
    """(attack s, decay s, sustain 0..1, release s, total) for one zone."""
    attack = _time(zone.attack, ATTACK_FAST, ATTACK_SLOW)
    decay = _time(zone.decay, DECAY_FAST, DECAY_SLOW)
    release = _time(zone.release, RELEASE_FAST, RELEASE_SLOW)
    sustain = max(0.0, min(1.0, zone.sustain / 127.0))
    return attack, decay, sustain, release, attack + decay


def _level(t: float, duration: float, attack: float, decay: float,
           sustain: float, release: float) -> float:
    """Level of the bank's envelope at ``t`` seconds into a note of ``duration``."""
    if t < 0.0:
        return 0.0
    if t < attack:
        value = t / attack
    elif t < attack + decay:
        fallen = (t - attack) / decay
        value = 1.0 - (1.0 - sustain) * fallen
    else:
        value = sustain
    if t > duration:
        left = (t - duration) / release if release > 0.0 else 1.0
        if left >= 1.0:
            return 0.0
        value *= 1.0 - left
    return value


# ------------------------------------------------------------------ rendering

def _pan_gains(pan: float) -> Tuple[float, float]:
    angle = (max(-1.0, min(1.0, pan)) + 1.0) * (math.pi / 4.0)
    return math.cos(angle), math.sin(angle)


def _voice_gain(note: Note) -> float:
    """Velocity and expression, on the DS's square-law-ish volume curve."""
    velocity = max(0, min(127, int(note.velocity))) / 127.0
    return (velocity ** 1.5) * max(0.0, min(1.0, float(note.expression or 1.0)))


def _add_note(left: List[float], right: List[float], note: Note,
              zone: nds.Zone, wave: Optional[dict], rate: int, gain: float,
              max_seconds: float) -> int:
    """Mix one note into the two channel buffers; returns 1 if it made a sound."""
    start = note.start
    duration = max(0.01, note.dur)
    if max_seconds and start >= max_seconds:
        return 0
    if max_seconds:
        duration = min(duration, max(0.0, max_seconds - start))
        if duration <= 0.0:
            return 0

    attack, decay, sustain, release, _total = envelope_for(zone)
    # a 40 ms sixteenth cannot afford a 300 ms attack
    attack = min(attack, duration * 0.5)
    pan_left, pan_right = _pan_gains(max(-1.0, min(1.0, (zone.pan - 64) / 63.0)))
    volume = gain * _voice_gain(note)

    if wave is None:
        return _add_psg(left, right, note, zone, rate, volume, pan_left,
                        pan_right, attack, decay, sustain, release)

    pcm = wave["pcm"]
    length = len(pcm)
    if length < 4:
        return 0
    looped = bool(wave.get("looped"))
    loop_start = max(0, min(int(wave.get("loop_start", 0)), length - 2))
    loop_end = max(loop_start + 2, min(int(wave.get("loop_end", length)), length))
    source_rate = float(wave["rate"] or NATIVE_RATE)
    step = (2.0 ** ((note.pitch + note.bend - zone.root) / 12.0)
            * (source_rate / float(rate)))
    if step <= 0.0:
        return 0

    first = int(round(start * rate))
    total = min(len(left), max(0, int(round((start + duration + release) * rate))))
    if first >= total:
        return 0

    phase = 0.0
    index = first
    elapsed = 0.0
    seconds_per_sample = 1.0 / rate

    # the pan is fixed for the whole note, so fold it into the per-sample
    # amplitude once per block instead of multiplying by it every sample
    stereo = right is not None
    while index < total:
        block = min(BLOCK, total - index)
        here = _level(elapsed, duration, attack, decay, sustain, release)
        later = _level(elapsed + block * seconds_per_sample, duration, attack,
                       decay, sustain, release)
        slope = (later - here) / block * volume
        amp_left = here * volume * pan_left
        amp_right = here * volume * pan_right
        end = index + block
        while index < end:
            # The loop length is never shortened: a loop that drops its last
            # sample is a loop that detunes the instrument by a fraction every
            # cycle, which is exactly the wavering "wrong pitch" this mode is
            # supposed to end.
            if looped:
                if phase >= loop_end:
                    phase = loop_start + (phase - loop_end)
            elif phase >= length:
                break                  # a one-shot sample has simply ended
            position = int(phase)
            if position >= length:
                break
            following = position + 1
            if following >= length:
                if not looped:
                    break
                following = loop_start
            # linear interpolation: a sample read back at its own rate is an
            # exact copy, and anything else stays clean instead of buzzy
            fraction = phase - position
            start_value = pcm[position]
            value = start_value + (pcm[following] - start_value) * fraction
            left[index] += value * amp_left
            if stereo:
                right[index] += value * amp_right
            phase += step
            amp_left += slope * pan_left
            amp_right += slope * pan_right
            index += 1
        if index < end:
            break                      # the sample ran out and does not loop
        elapsed += block * seconds_per_sample
    return 1


def _add_psg(left: List[float], right: List[float], note: Note, zone: nds.Zone,
             rate: int, volume: float, pan_left: float, pan_right: float,
             attack: float, decay: float, sustain: float, release: float) -> int:
    """A bank slot with no sample behind it: a PSG square, the way the DS makes it.

    DS banks mix real "chip" instruments in with the samples, and those are just
    a duty cycle and a noise flag — there is nothing in the wave archive to read.
    Playing them as a square keeps the part audible instead of leaving a hole in
    the music, and the honest kind of wrong: a pulse where the game had a pulse.
    """
    duty_codes = {0: 0.125, 1: 0.25, 2: 0.375, 3: 0.5, 4: 0.625, 5: 0.75, 6: 0.875}
    duty = duty_codes.get(int(getattr(zone, "wave", 3)) & 0x07, 0.5)
    frequency = 440.0 * 2.0 ** ((note.pitch + note.bend - 69) / 12.0)
    if frequency <= 20.0 or frequency >= rate / 2.2:
        return 0
    duration = max(0.01, note.dur)
    first = int(round(note.start * rate))
    total = min(len(left), int(round((note.start + duration + release) * rate)))
    if first >= total:
        return 0
    period = rate / frequency
    index = first
    phase = 0.0
    elapsed = 0.0
    seconds_per_sample = 1.0 / rate
    while index < total:
        block = min(BLOCK, total - index)
        here = _level(elapsed, duration, attack, decay, sustain, release)
        later = _level(elapsed + block * seconds_per_sample, duration, attack,
                       decay, sustain, release)
        slope = (later - here) / block
        level = here
        end = index + block
        while index < end:
            value = (1.0 if (phase % period) < period * duty else -1.0)
            value *= level * volume * 0.55
            left[index] += value * pan_left
            if right is not None:
                right[index] += value * pan_right
            phase += 1.0
            level += slope
            index += 1
        elapsed += block * seconds_per_sample
    return 1


def render_song(song: Song, archive: "nds.Archive", bank_index: int,
                options: Optional[SampleOptions] = None) -> SampleRender:
    """Render a whole song on the game's own instruments."""
    options = options or SampleOptions()
    rate = max(8000, int(options.rate))
    bank = Bank(archive, bank_index)

    notes = [note for note in song.notes if note.dur > 0.0]
    if not notes:
        return SampleRender(rate=rate)
    end = max(note.end() for note in notes) + 0.05
    if options.max_seconds:
        end = min(end, options.max_seconds)
    total = int(round(end * rate))
    left = [0.0] * total
    right = [0.0] * total if options.stereo else None

    played = skipped = synthetic = 0
    for note in notes:
        zone, wave = bank.zone_for(note.program, note.pitch)
        if zone is None:
            skipped += 1
            continue
        if wave is None and not zone.psg:
            skipped += 1
            continue
        made = _add_note(left, right, note, zone, wave, rate, 1.0,
                         options.max_seconds)
        played += made
        synthetic += 1 if (made and wave is None) else 0

    seconds = total / float(rate)
    tracks = group_tracks(notes)

    # --- the same finishing chain the chip renderer ends with, so both outputs
    #     sit at a comparable level and neither clips
    channels = [left] if right is None else [left, right]
    for channel in channels:
        _polish(channel, rate, options.lowpass)
    headroom = max((max((abs(value) for value in channel), default=0.0)
                    for channel in channels), default=0.0)
    if headroom > 0.0:
        scale = 1.0 / headroom
        for channel in channels:
            channel[:] = [value * scale for value in channel]
    if options.echo:
        delay = mix.echo_delay(notes)
        for channel in channels:
            mix.echo(channel, rate, delay=delay)
    if options.compress:
        for channel in channels:
            mix.compress(channel, rate)
    if options.limit:
        ceiling = mix.choose_ceiling(channels[0], rate)
        for channel in channels:
            mix.limit(channel, rate, ceiling=ceiling)

    peak = max((max((abs(value) for value in channel), default=0.0)
                for channel in channels), default=0.0)
    if peak > 0.0:
        scale = options.gain / peak
        for channel in channels:
            channel[:] = [value * scale for value in channel]

    pcm = _pcm_bytes(channels, rate)
    return SampleRender(pcm=pcm, seconds=seconds, rate=rate,
                        voices=len(tracks), notes_played=played,
                        notes_skipped=skipped, synthetic=synthetic,
                        instruments=bank.instrument_count(),
                        drums=len(bank.kits),
                        channels=2 if options.stereo else 1, tracks=tracks)


def group_tracks(notes: List[Note]) -> Dict[str, List[Note]]:
    """The song's own tracks, named, so the pattern page can show them."""
    grouped: Dict[str, List[Note]] = {}
    for note in sorted(notes, key=lambda item: item.start):
        grouped.setdefault("trk %02d" % (int(note.part) + 1), []).append(note)
    return grouped


def _polish(channel: List[float], rate: int, lowpass: bool) -> None:
    """DC block, plus the optional gentle low-pass (the DS's own output is clean)."""
    if lowpass:
        alpha = 2 * math.pi * 11000.0 / rate
        alpha = alpha / (alpha + 1.0)
        previous = 0.0
        for index in range(len(channel)):
            previous += alpha * (channel[index] - previous)
            channel[index] = previous
    previous_in = 0.0
    previous_out = 0.0
    for index in range(len(channel)):
        value = channel[index]
        out = value - previous_in + 0.9955 * previous_out
        previous_in = value
        previous_out = out
        channel[index] = out


def _pcm_bytes(channels: List[List[float]], rate: int) -> bytes:
    """16-bit little-endian, dithered off (the source samples are already 16-bit)."""
    import struct

    if len(channels) == 2:
        left, right = channels
        frames = bytearray()
        pack = struct.Struct("<hh").pack
        for index in range(len(left)):
            frames += pack(_clamp16(left[index]), _clamp16(right[index]))
        return bytes(frames)
    frames = bytearray()
    pack = struct.Struct("<h").pack
    for value in channels[0]:
        frames += pack(_clamp16(value))
    return bytes(frames)


def _clamp16(value: float) -> int:
    scaled = int(round(max(-1.0, min(1.0, value)) * 32767.0))
    return max(-32768, min(32767, scaled))
