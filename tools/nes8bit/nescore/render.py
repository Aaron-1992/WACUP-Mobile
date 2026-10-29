"""Synthesis: turn arranged notes into audio that sounds like a console, not a toy.

Two changes matter most for how this sounds:

* **drums are sampled.** The NES's delta channel plays actual samples, so the kit
  in ``samples.py`` is played back through it (7-bit, 33.1 kHz) instead of being
  faked with the noise generator. That single change does more for the sound than
  any amount of square-wave tweaking.
* **every note has a real envelope and nothing clicks.** Each note gets a short
  attack ramp, a musical decay, and a release ramp, so notes no longer start and
  stop with a digital snap. The mix then goes through a gentle low-pass, a DC
  blocker and the APU's non-linear output curve.

Waveforms are written into the buffer as runs, so a three-minute song still
renders in seconds.

* pulse     - square wave, 4-bit volume, duty 12.5/25/50/75 %
* triangle  - 32-step stepped triangle, no volume control (that is the point)
* noise     - 15-bit LFSR, hardware period table, short (metallic) mode
* saw       - VRC6's 4-bit sawtooth
* fds       - single-cycle wavetable, like the FDS's 64-step wave
* wavetable - Namco 163 style 4-bit wavetable
* psg       - SN76489 square with 4 attenuation steps
* dmc/noise - sampled percussion (kick, snare, hats, toms, crash)
"""

import math
import os
import struct
import wave
from dataclasses import dataclass
from typing import Dict, List, Optional

from . import samples
from .arrange import KIND_GAIN
from .chips import NOISE_PERIODS, channel_by_id
from .model import Note

APU_CLOCK = 1789773.0     # NTSC NES CPU clock
MAX_RUN = 64              # samples per write; short runs let the envelope move
VIBRATO_HZ = 5.5          # the wobble a MIDI CC1 slide actually sounds like
ATTACK = 0.004            # seconds; kills the start-of-note click
RELEASE = 0.012           # seconds; kills the end-of-note click
LOWPASS_HZ = 11000.0      # tames square-wave fizz without dulling the sound


@dataclass
class RenderOptions:
    rate: int = 44100
    bits: int = 16
    stereo: bool = False
    gain: float = 0.9
    nonlinear: bool = True
    dither: bool = True
    max_seconds: float = 0.0     # 0 = whole song
    vibrato: bool = True
    sampled_drums: bool = True
    lowpass: bool = True


def note_frequency(pitch: float) -> float:
    return 440.0 * (2.0 ** ((pitch - 69.0) / 12.0))


# --------------------------------------------------------------------- envelopes

def _base_level(note: Note, progress: float) -> float:
    """4-bit-ish volume over the life of a note, the way a console envelope moves."""
    if note.volume <= 0:
        return 0.0
    progress = max(0.0, min(1.0, progress))
    if note.role == "drum":
        decay = (1.0 - progress) ** 0.7
    elif note.role == "bass":
        decay = 1.0 - 0.18 * progress
    else:
        decay = 1.0 - 0.28 * progress
    level = int(round(note.volume * max(0.0, decay)))
    return max(0, min(15, level)) / 15.0


def _envelope(note: Note, elapsed: float) -> float:
    """Level at a moment in time, with ramps so nothing clicks."""
    duration = max(note.dur, 1e-4)
    if elapsed < 0 or elapsed >= duration:
        return 0.0
    base = _base_level(note, elapsed / duration)
    attack = min(1.0, elapsed / ATTACK)
    release = min(1.0, (duration - elapsed) / RELEASE)
    return base * math.sqrt(attack) * (release ** 0.45)


def _slice(buf: List[float], start: int, end: int, level: float) -> None:
    start = max(0, start)
    end = min(len(buf), end)
    if end > start:
        buf[start:end] = [level] * (end - start)


def _vibrato(note: Note, seconds: float, enabled: bool) -> float:
    """Pitch multiplier for the note's vibrato depth, as a slow LFO."""
    if not enabled or note.vibrato <= 0:
        return 1.0
    depth = note.vibrato / 12.0
    # fade the wobble in, the way a singer or a synth LFO does
    ramp = min(1.0, seconds / 0.15)
    return 1.0 + depth * ramp * math.sin(2.0 * math.pi * VIBRATO_HZ * seconds)


# ----------------------------------------------------------------- oscillators

def _emit_pulse(buf, a: int, b: int, note: Note, rate: int, gain: float,
                vibrato: bool) -> None:
    base = note_frequency(note.pitch + note.bend)
    duty = min(0.875, max(0.125, note.duty))
    pos = float(a)
    while pos < b:
        elapsed = (pos - a) / rate
        frequency = base * _vibrato(note, elapsed, vibrato)
        period = rate / max(1e-6, frequency)
        high = max(1.0, period * duty)
        phase = (pos - a) % period
        level = 1.0 if phase < high else -1.0
        nxt = pos + (high - phase) if phase < high else pos + (period - phase)
        if nxt <= pos + 0.5:
            nxt = pos + 1.0
        run_end = min(float(b), nxt, pos + MAX_RUN)
        _slice(buf, int(pos), int(run_end), level * _envelope(note, elapsed) * gain)
        pos = run_end


def _emit_steps(buf, a: int, b: int, note: Note, steps: List[float], rate: int,
                gain: float, vibrato: bool) -> None:
    """Stepped (wavetable / triangle / saw) oscillator, one step per hardware tick."""
    base = note_frequency(note.pitch + note.bend)
    count = len(steps)
    pos = float(a)
    index = 0
    while pos < b:
        elapsed = (pos - a) / rate
        frequency = base * _vibrato(note, elapsed, vibrato)
        clock = rate / max(1e-6, frequency * count)
        run_end = min(float(b), pos + max(1.0, clock), pos + MAX_RUN)
        _slice(buf, int(pos), int(run_end),
               steps[index % count] * _envelope(note, elapsed) * gain)
        index += 1
        pos = run_end


def _triangle() -> List[float]:
    """The APU's 32-entry sequence: 15 down to 0, then back up to 15."""
    steps = []
    for step in range(32):
        value = 15 - step if step < 16 else step - 16
        steps.append(value / 15.0 * 2.0 - 1.0)
    return steps


TRIANGLE_STEPS = _triangle()
SAW_STEPS = [(step / 15.0) * 2.0 - 1.0 for step in range(16)]
WAVETABLE_STEPS = [math.sin(2 * math.pi * step / 32.0) for step in range(32)]
FDS_STEPS = [math.sin(2 * math.pi * step / 64.0) for step in range(64)]
PSG_STEPS = [1.0] * 4 + [-1.0] * 4


def _emit_noise(buf, a: int, b: int, note: Note, rate: int, gain: float) -> None:
    index = max(0, min(len(NOISE_PERIODS) - 1, note.noise_period))
    period = float(NOISE_PERIODS[index])
    samples_per_step = max(1.0, rate / (APU_CLOCK / period))
    short = note.noise_short
    lfsr = 1
    pos = float(a)
    while pos < b:
        for _ in range(int(max(1, min(MAX_RUN * 4, round(samples_per_step))))):
            if short:
                bit = ((lfsr >> 6) ^ (lfsr >> 8)) & 1
                lfsr = (lfsr >> 1) | (bit << 14)
                lfsr = (lfsr & ~0x40) | (((lfsr >> 6) ^ (lfsr >> 8)) & 1) << 6
            else:
                bit = (lfsr & 1) ^ ((lfsr >> 1) & 1)
                lfsr = (lfsr >> 1) | (bit << 14)
        level = 1.0 if (lfsr & 1) else -1.0
        run_end = min(float(b), pos + samples_per_step, pos + MAX_RUN * 4)
        _slice(buf, int(pos), int(run_end),
               level * _envelope(note, (pos - a) / rate) * gain)
        pos = run_end


def _emit_sample(buf, a: int, b: int, note: Note, rate: int, gain: float) -> None:
    """Play a kit piece, resampled from the delta channel's rate."""
    piece = samples.get(samples.for_drum(note.drum or "snare", note.pitch))
    source_rate = samples.sample_rate()
    step = source_rate / float(rate)
    length = min(b - a, int(len(piece) / step))
    position = 0.0
    for index in range(length):
        sample_index = int(position)
        fraction = position - sample_index
        value = piece[sample_index]
        if sample_index + 1 < len(piece):
            value += (piece[sample_index + 1] - value) * fraction
        # a hit's own decay is baked into the sample, so only the start matters
        attack = min(1.0, index / max(1.0, ATTACK * rate))
        buf[a + index] += value * attack * gain * (note.volume / 15.0)
        position += step


# ------------------------------------------------------------------- rendering

def render_channel(notes: List[Note], spec, options: RenderOptions,
                   total_samples: int) -> List[float]:
    buf = [0.0] * total_samples
    gain = KIND_GAIN.get(spec.kind, 0.5)
    rate = options.rate
    vibrato = options.vibrato

    for note in notes:
        a = int(round(note.start * rate))
        b = int(round(note.end() * rate))
        if b <= a or a >= total_samples:
            continue
        b = min(b, total_samples)

        percussion = note.role == "drum" and spec.kind in ("noise", "dmc")

        if percussion and options.sampled_drums:
            _emit_sample(buf, a, b, note, rate, gain * 1.55)
            continue

        frequency = note_frequency(note.pitch + note.bend)
        if spec.kind not in ("noise",) and (frequency <= 20 or frequency > rate / 2.2):
            continue

        if spec.kind == "pulse":
            _emit_pulse(buf, a, b, note, rate, gain, vibrato)
        elif spec.kind == "triangle":
            _emit_steps(buf, a, b, note, TRIANGLE_STEPS, rate, gain, vibrato)
        elif spec.kind == "saw":
            _emit_steps(buf, a, b, note, SAW_STEPS, rate, gain, vibrato)
        elif spec.kind == "fds":
            _emit_steps(buf, a, b, note, FDS_STEPS, rate, gain, vibrato)
        elif spec.kind == "wavetable":
            _emit_steps(buf, a, b, note, WAVETABLE_STEPS, rate, gain, vibrato)
        elif spec.kind == "psg":
            _emit_steps(buf, a, b, note, PSG_STEPS, rate, gain, vibrato)
        elif spec.kind == "noise":
            _emit_noise(buf, a, b, note, rate, gain)
        elif spec.kind == "dmc":
            # a melodic note on the delta channel: play the hit's own pitch
            _emit_sample(buf, a, b, note, rate, gain)
    return buf


def _curve(value: float, nonlinear: bool) -> float:
    if nonlinear:
        # the APU's non-linear mixer compresses peaks; softer drive than before,
        # because the low-pass already takes the edge off
        return math.tanh(value * 1.15) / math.tanh(1.15)
    return max(-1.0, min(1.0, value))


def _polish(master: List[float], rate: int, lowpass: bool) -> List[float]:
    """Gentle low-pass, then DC blocking. Small steps, big difference."""
    if lowpass:
        alpha = (2 * math.pi * LOWPASS_HZ / rate)
        alpha = alpha / (alpha + 1.0)
        previous = 0.0
        for index in range(len(master)):
            previous += alpha * (master[index] - previous)
            master[index] = previous

    # DC blocker: square waves with a duty cycle are never symmetric
    previous_in = 0.0
    previous_out = 0.0
    for index in range(len(master)):
        value = master[index]
        out = value - previous_in + 0.9955 * previous_out
        previous_in = value
        previous_out = out
        master[index] = out
    return master


def render(notes: List[Note], channels, options: RenderOptions,
           per_channel: Optional[Dict[str, List[Note]]] = None):
    """Returns (pcm_bytes, stems_per_channel, duration_seconds)."""
    if not notes:
        return b"", {}, 0.0

    duration = max(n.end() for n in notes) + 0.05
    if options.max_seconds:
        duration = min(duration, options.max_seconds)
    total = int(round(duration * options.rate))

    grouped: Dict[str, List[Note]] = per_channel or {}
    if not grouped:
        for note in notes:
            grouped.setdefault(note.channel, []).append(note)

    master = [0.0] * total
    stems: Dict[str, List[float]] = {}
    for channel_id, channel_notes in grouped.items():
        try:
            spec = channel_by_id(channels, channel_id)
        except KeyError:
            continue
        buf = render_channel(channel_notes, spec, options, total)
        stems[channel_id] = buf
        for index, value in enumerate(buf):
            master[index] += value

    _polish(master, options.rate, options.lowpass)

    peak = max((abs(value) for value in master), default=0.0)
    scale = (options.gain / peak) if peak > 0 else 1.0

    noise = 0x1234
    frames = bytearray()
    wide = options.bits > 8
    for value in master:
        shaped = _curve(value * scale, options.nonlinear)
        if options.dither:
            noise = (noise * 1103515245 + 12345) & 0x7FFFFFFF
            shaped += ((noise / 0x7FFFFFFF) - 0.5) / (4096.0 if wide else 512.0)
        shaped = max(-1.0, min(1.0, shaped))
        if wide:
            frames += struct.pack("<h", max(-32768, min(32767,
                                                        int(round(shaped * 32767.0)))))
        else:
            frames.append(max(0, min(255, int(round((shaped * 0.5 + 0.5) * 255.0)))))

    if options.stereo:
        step = 2 if wide else 1
        stereo = bytearray()
        for index in range(0, len(frames), step):
            chunk = frames[index:index + step]
            stereo += chunk * 2
        frames = stereo

    return bytes(frames), stems, duration


def wav_bytes(pcm: bytes, options: RenderOptions) -> bytes:
    """Wrap raw PCM in a WAV container, in memory."""
    import io

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(2 if options.stereo else 1)
        handle.setsampwidth(2 if options.bits > 8 else 1)
        handle.setframerate(options.rate)
        handle.writeframes(pcm)
    return buffer.getvalue()


def write_wav(path: str, pcm: bytes, options: RenderOptions) -> None:
    with open(path, "wb") as handle:
        handle.write(wav_bytes(pcm, options))


def write_stems(directory: str, stems: Dict[str, List[float]],
                options: RenderOptions) -> List[str]:
    """One WAV per console channel, for checking the arrangement by ear."""
    os.makedirs(directory, exist_ok=True)
    written = []
    for channel_id, buf in sorted(stems.items()):
        peak = max((abs(value) for value in buf), default=0.0) or 1.0
        frames = bytearray()
        for value in buf:
            shaped = _curve(value / peak * 0.9, options.nonlinear)
            frames.append(max(0, min(255, int(round((shaped * 0.5 + 0.5) * 255.0)))))
        path = os.path.join(directory, "%s.wav" % channel_id)
        with wave.open(path, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(1)
            handle.setframerate(options.rate)
            handle.writeframes(bytes(frames))
        written.append(path)
    return written
