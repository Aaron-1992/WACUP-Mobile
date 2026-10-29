"""Synthesis: turn arranged notes into a console-accurate waveform.

Each channel kind is generated the way the hardware does it. Waveforms are written
into the buffer as runs (a half square wave is one slice) so a three-minute song
renders in seconds instead of minutes, while the pitch still changes sample by
sample of the envelope — that is what keeps close-together notes and vibrato clean.

* pulse     - square wave, 4-bit volume, duty 12.5/25/50/75 %
* triangle  - 32-step stepped triangle, no volume control (that is the point)
* noise     - 15-bit LFSR, hardware period table, short (metallic) mode
* saw       - VRC6's 4-bit sawtooth
* fds       - single-cycle wavetable, sine-ish like the FDS's 64-step wave
* wavetable - Namco 163 style 4-bit wavetable
* psg       - SN76489 square with 4 attenuation steps
* dmc       - the delta channel, driven as an unpitched percussion thump

The mix is pushed through the NES's non-linear output curve before quantising to
8 bits, which is where the grit of real console audio comes from.
"""

import math
import os
import struct
import wave
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from .arrange import KIND_GAIN
from .chips import NOISE_PERIODS, channel_by_id
from .model import Note

APU_CLOCK = 1789773.0     # NTSC NES CPU clock
MAX_RUN = 64              # samples per write; short runs let the envelope move
VIBRATO_HZ = 5.5          # the wobble a MIDI CC1 slide actually sounds like


@dataclass
class RenderOptions:
    rate: int = 44100
    bits: int = 8
    stereo: bool = False
    gain: float = 0.9
    nonlinear: bool = True
    dither: bool = True
    max_seconds: float = 0.0     # 0 = whole song
    vibrato: bool = True


def note_frequency(pitch: float) -> float:
    return 440.0 * (2.0 ** ((pitch - 69.0) / 12.0))


# --------------------------------------------------------------------- helpers

def _envelope(note: Note, progress: float) -> int:
    """4-bit volume over the life of a note, the way a console envelope behaves."""
    if note.volume <= 0:
        return 0
    progress = max(0.0, min(1.0, progress))
    if note.role == "drum":
        decay = 1.0 - progress ** 0.6                    # hard, fast decay
    elif note.role == "bass":
        decay = 1.0 - 0.22 * progress                    # the bass holds
    else:
        decay = 1.0 - 0.30 * progress                    # gentle singing decay
    return max(0, min(15, int(round(note.volume * decay))))


def _slice(buf: List[float], start: int, end: int, level: float) -> None:
    start = max(0, start)
    end = min(len(buf), end)
    if end > start:
        buf[start:end] = [level] * (end - start)


def _vibrato(note: Note, seconds: float, enabled: bool) -> float:
    """Pitch multiplier for the note's vibrato depth, as a slow LFO."""
    if not enabled or note.vibrato <= 0:
        return 1.0
    depth = (note.vibrato / 12.0) * (2.0 ** 0)        # semitones -> ratio at the peak
    return 1.0 + depth * math.sin(2.0 * math.pi * VIBRATO_HZ * seconds)


# ----------------------------------------------------------------- oscillators

def _emit_pulse(buf, a: int, b: int, note: Note, rate: int, gain: float,
                vibrato: bool) -> None:
    base = note_frequency(note.pitch + note.bend)
    duty = min(0.875, max(0.125, note.duty))
    pos = float(a)
    while pos < b:
        seconds = (pos - a) / rate
        frequency = base * _vibrato(note, seconds, vibrato)
        period = rate / max(1e-6, frequency)
        high = max(1.0, period * duty)
        phase = (pos - a) % period
        level = 1.0 if phase < high else -1.0
        nxt = pos + (high - phase) if phase < high else pos + (period - phase)
        if nxt <= pos + 0.5:
            nxt = pos + 1.0
        run_end = min(float(b), nxt, pos + MAX_RUN)
        volume = _envelope(note, seconds / note.dur) / 15.0
        _slice(buf, int(pos), int(run_end), level * volume * gain)
        pos = run_end


def _emit_steps(buf, a: int, b: int, note: Note, steps: List[float], rate: int,
                gain: float, vibrato: bool) -> None:
    """Stepped (wavetable / triangle / saw) oscillator, one step per hardware tick."""
    base = note_frequency(note.pitch + note.bend)
    count = len(steps)
    pos = float(a)
    index = 0
    while pos < b:
        seconds = (pos - a) / rate
        frequency = base * _vibrato(note, seconds, vibrato)
        clock = rate / max(1e-6, frequency * count)
        run_end = min(float(b), pos + max(1.0, clock), pos + MAX_RUN)
        volume = _envelope(note, seconds / note.dur) / 15.0
        _slice(buf, int(pos), int(run_end), steps[index % count] * volume * gain)
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
        shift_budget = int(max(1, min(MAX_RUN * 4, round(samples_per_step))))
        for _ in range(shift_budget):
            if short:
                bit = ((lfsr >> 6) ^ (lfsr >> 8)) & 1
                lfsr = (lfsr >> 1) | (bit << 14)
                lfsr = (lfsr & ~0x40) | (((lfsr >> 6) ^ (lfsr >> 8)) & 1) << 6
            else:
                bit = (lfsr & 1) ^ ((lfsr >> 1) & 1)
                lfsr = (lfsr >> 1) | (bit << 14)
        level = 1.0 if (lfsr & 1) else -1.0
        run_end = min(float(b), pos + samples_per_step, pos + MAX_RUN * 4)
        volume = _envelope(note, (pos - a) / rate / note.dur) / 15.0
        _slice(buf, int(pos), int(run_end), level * volume * gain)
        pos = run_end


def _emit_dmc(buf, a: int, b: int, note: Note, rate: int, gain: float) -> None:
    """Direct DAC load: a 7-bit level stepped down, i.e. a kick without a sample ROM."""
    step = max(1, int(rate / 3300))
    pos = float(a)
    length = max(1, b - a)
    while pos < b:
        progress = (pos - a) / length
        # a fast rise then an exponential fall, quantised to the DAC's 7 bits
        level = 1.0 if progress < 0.08 else max(0.0, 1.0 - (progress - 0.08) * 1.9)
        level = round(level * 12.0) / 12.0
        run_end = min(float(b), pos + step, pos + MAX_RUN)
        volume = _envelope(note, progress) / 15.0
        _slice(buf, int(pos), int(run_end), (level * 2.0 - 1.0) * volume * gain)
        pos = run_end


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
        frequency = note_frequency(note.pitch + note.bend)
        if spec.kind != "noise" and spec.kind != "dmc":
            if frequency <= 20 or frequency > rate / 2.2:
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
            _emit_dmc(buf, a, b, note, rate, gain)
    return buf


def _curve(value: float, nonlinear: bool) -> float:
    if nonlinear:
        # Approximates the APU's non-linear mixer: it compresses peaks, which is
        # why real NES audio never sounds like raw square waves.
        return math.tanh(value * 1.35) / math.tanh(1.35)
    return max(-1.0, min(1.0, value))


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
        master = [a + b for a, b in zip(master, buf)]

    peak = max((abs(value) for value in master), default=0.0)
    scale = (options.gain / peak) if peak > 0 else 1.0

    noise = 0x1234
    frames = bytearray()
    wide = options.bits > 8
    for value in master:
        shaped = _curve(value * scale, options.nonlinear)
        if options.dither:
            noise = (noise * 1103515245 + 12345) & 0x7FFFFFFF
            shaped += ((noise / 0x7FFFFFFF) - 0.5) / 512.0
        shaped = max(-1.0, min(1.0, shaped))
        if wide:
            frames += struct.pack("<h", max(-32768, min(32767, int(round(shaped * 32767.0)))))
        else:
            frames.append(max(0, min(255, int(round((shaped * 0.5 + 0.5) * 255.0)))))

    if options.stereo:
        step = 2 if wide else 1
        stereo = bytearray()
        for index in range(0, len(frames), step):
            chunk = frames[index:index + step]
            stereo += chunk + chunk
        frames = stereo

    return bytes(frames), stems, duration


def write_wav(path: str, pcm: bytes, options: RenderOptions) -> None:
    with wave.open(path, "wb") as handle:
        handle.setnchannels(2 if options.stereo else 1)
        handle.setsampwidth(2 if options.bits > 8 else 1)
        handle.setframerate(options.rate)
        handle.writeframes(pcm)


def wav_bytes(pcm: bytes, options: RenderOptions) -> bytes:
    """Wrap raw PCM in a WAV container, in memory (used by the GUI)."""
    import io

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(2 if options.stereo else 1)
        handle.setsampwidth(2 if options.bits > 8 else 1)
        handle.setframerate(options.rate)
        handle.writeframes(pcm)
    return buffer.getvalue()


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
