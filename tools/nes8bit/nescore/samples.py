"""Sampled percussion.

The NES plays samples through the delta channel, so drums are not square waves:
they are short recorded hits. There is no copyrighted sample data here — each kit
piece is synthesised from scratch (sine sweeps for kick and toms, filtered noise
for snare and cymbals) and then *degraded the way the hardware degrades it*: 7-bit
amplitude at the delta channel's 33.1 kHz step rate. That is why the result sounds
like a console drum kit rather than a clean drum machine.

Everything is computed once, lazily, and cached.
"""

import math
import random
from typing import Dict, List

DMC_RATE = 33143          # the NES delta channel's fastest step rate
DMC_LEVELS = 128          # its 7-bit DAC


def _noise(count: int, seed: int) -> List[float]:
    rng = random.Random(seed)
    return [rng.uniform(-1.0, 1.0) for _ in range(count)]


def _highpass(signal: List[float], cutoff: float, rate: float) -> List[float]:
    alpha = 1.0 / (1.0 + (2 * math.pi * cutoff / rate))
    out = [0.0] * len(signal)
    previous_in = 0.0
    previous_out = 0.0
    for index, value in enumerate(signal):
        result = alpha * (previous_out + value - previous_in)
        out[index] = result
        previous_in = value
        previous_out = result
    return out


def _lowpass(signal: List[float], cutoff: float, rate: float) -> List[float]:
    alpha = (2 * math.pi * cutoff / rate)
    alpha = alpha / (alpha + 1.0)
    out = [0.0] * len(signal)
    previous = 0.0
    for index, value in enumerate(signal):
        previous += alpha * (value - previous)
        out[index] = previous
    return out


def _normalise(signal: List[float], peak: float = 0.95) -> List[float]:
    top = max((abs(v) for v in signal), default=0.0)
    if top <= 0:
        return signal
    scale = peak / top
    return [v * scale for v in signal]


def _quantise(signal: List[float]) -> List[float]:
    """7-bit, like the delta channel's DAC — but with error feedback.

    Straight quantisation leaves a stair-step on every decay, which is what makes
    cheap sampled drums buzz. Feeding the rounding error into the next sample moves
    that error into noise the ear ignores, so the grit stays and the buzz does not.
    """
    scale = DMC_LEVELS / 2.0
    error = 0.0
    out = []
    for value in signal:
        wanted = value * scale + error
        stepped = round(wanted)
        error = wanted - stepped
        out.append(stepped / scale)
    return out


def _soft_clip(signal: List[float], drive: float = 1.6) -> List[float]:
    """A little saturation: a real drum hit is not a clean sine."""
    return [math.tanh(value * drive) / math.tanh(drive) for value in signal]


def _room(signal: List[float], rate: float = DMC_RATE) -> List[float]:
    """Three early reflections, quiet: the kit sits in a room instead of a vacuum."""
    taps = ((0.009, 0.20), (0.017, 0.13), (0.029, 0.08))
    out = list(signal)
    for delay, gain in taps:
        offset = int(delay * rate)
        if offset >= len(out):
            continue
        for index in range(offset, len(out)):
            out[index] += signal[index - offset] * gain
    return out


def _metal(frequencies, seconds: float, rate: float = DMC_RATE) -> List[float]:
    """The 808 trick: a handful of detuned squares through a high-pass."""
    count = int(seconds * rate)
    out = [0.0] * count
    for frequency in frequencies:
        step = 2.0 * math.pi * frequency / rate
        for index in range(count):
            out[index] += 1.0 if math.sin(step * index) >= 0.0 else -1.0
    spread = max((abs(v) for v in out), default=1.0) or 1.0
    out = [v / spread for v in out]
    return _highpass(out, 3200.0, rate)


def _render(seconds: float, rate: int = DMC_RATE):
    return int(seconds * rate), rate


# ------------------------------------------------------------------- the kit

def kick() -> List[float]:
    """Punch, not a beep: a fast pitch drop, a beater click and a short tail."""
    count, rate = _render(0.30)
    out = []
    phase = 0.0
    for index in range(count):
        t = index / rate
        # 165 Hz down to 44 Hz in ~35 ms, the way a real kick's head tension falls
        frequency = 44.0 + 121.0 * math.exp(-t / 0.032)
        phase += 2 * math.pi * frequency / rate
        body = math.sin(phase) * math.exp(-t / 0.090)
        thump = math.sin(phase * 0.5) * math.exp(-t / 0.16) * 0.25
        click = math.exp(-t / 0.0035) * 0.55 * (1.0 if index % 2 else -1.0)
        out.append(body + thump + click)
    out = _soft_clip(_normalise(out, 0.9), 1.35)
    return _quantise(_normalise(_room(out), 0.96))


def snare() -> List[float]:
    """Two drum heads plus a wire rattle — the crack comes from the noise layer."""
    count, rate = _render(0.30)
    noise = _highpass(_noise(count, 11), 1600, rate)
    rattle = _highpass(_noise(count, 13), 4200, rate)
    out = []
    for index in range(count):
        t = index / rate
        # heads at 185 and 278 Hz, both dropping slightly as the shell settles
        drop = 1.0 - 0.10 * min(1.0, t / 0.05)
        tone = (math.sin(2 * math.pi * 185.0 * drop * t) * 0.52
                + math.sin(2 * math.pi * 278.0 * drop * t) * 0.30)
        tone *= math.exp(-t / 0.045)
        crack = noise[index] * math.exp(-t / 0.012) * 0.55
        wires = rattle[index] * math.exp(-t / 0.075) * 0.55
        out.append(tone + crack + wires)
    out = _soft_clip(_normalise(out, 0.9), 1.2)
    return _quantise(_normalise(_room(out), 0.97))


def hat(open_hat: bool = False) -> List[float]:
    """Metallic, not a burst of white noise: six inharmonic squares plus sizzle."""
    length = 0.34 if open_hat else 0.075
    count, rate = _render(length)
    metal = _metal((205.3, 304.4, 369.6, 522.7, 540.0, 800.0), length)
    noise = _highpass(_noise(count, 23 if open_hat else 17), 7500, rate)
    decay = 0.19 if open_hat else 0.026
    out = []
    for index in range(count):
        t = index / rate
        envelope = math.exp(-t / decay) * (1.0 - math.exp(-t / 0.0008))
        out.append((metal[index] * 0.75 + noise[index] * 0.55) * envelope)
    out = _highpass(out, 5200.0, rate)
    return _quantise(_normalise(out, 0.6))


def tom(frequency: float = 160.0) -> List[float]:
    count, rate = _render(0.34)
    skin_noise = _highpass(_noise(count, int(frequency) + 7), 900, rate)
    out = []
    phase = 0.0
    for index in range(count):
        t = index / rate
        current = frequency * (1.0 + 0.42 * math.exp(-t / 0.028))
        phase += 2 * math.pi * current / rate
        body = math.sin(phase) * math.exp(-t / 0.105)
        overtone = math.sin(phase * 1.71) * math.exp(-t / 0.045) * 0.18
        skin = skin_noise[index] * math.exp(-t / 0.008) * 0.30
        out.append(body + overtone + skin)
    out = _soft_clip(_normalise(out, 0.95), 1.15)
    return _quantise(_normalise(_room(out), 0.96))


def crash() -> List[float]:
    count, rate = _render(1.0)
    wash = _highpass(_noise(count, 41), 3000, rate)
    metal = _metal((465.0, 697.0, 1046.0, 1568.0, 2093.0), 1.0)
    out = []
    for index in range(count):
        t = index / rate
        envelope = math.exp(-t / 0.34) * (1.0 - math.exp(-t / 0.0015))
        bloom = math.exp(-t / 0.55) * 0.6 + 0.4
        out.append((wash[index] * 0.55 + metal[index] * 0.45 * bloom) * envelope)
    return _quantise(_normalise(out, 0.72))


def clap() -> List[float]:
    count, rate = _render(0.2)
    noise = _lowpass(_highpass(_noise(count, 71), 900, rate), 5000, rate)
    out = []
    for index in range(count):
        t = index / rate
        # three quick bursts then a tail: that is what a clap actually is
        burst = 0.0
        for start in (0.0, 0.011, 0.022):
            if t >= start:
                burst += math.exp(-(t - start) / 0.008)
        tail_env = math.exp(-max(0.0, t - 0.03) / 0.09) if t > 0.03 else 0.0
        out.append(noise[index] * (0.6 * burst + 0.5 * tail_env))
    return _quantise(_normalise(out, 0.8))


def rim() -> List[float]:
    count, rate = _render(0.05)
    noise = _highpass(_noise(count, 91), 2000, rate)
    out = []
    for index in range(count):
        t = index / rate
        click = math.sin(2 * math.pi * 1750 * t) * math.exp(-t / 0.004)
        out.append(click * 0.7 + noise[index] * math.exp(-t / 0.010) * 0.5)
    return _quantise(_normalise(out, 0.7))


def ride() -> List[float]:
    count, rate = _render(0.8)
    wash = _highpass(_noise(count, 53), 5200, rate)
    metal = _metal((590.0, 883.0, 1324.0, 1985.0), 0.8)
    out = []
    for index in range(count):
        t = index / rate
        bell = (math.sin(2 * math.pi * 1180 * t) + 0.6 * math.sin(2 * math.pi * 1760 * t))
        ping = metal[index] * math.exp(-t / 0.09) * 0.8
        out.append(wash[index] * math.exp(-t / 0.26) * 0.30
                   + bell * math.exp(-t / 0.22) * 0.25
                   + ping)
    return _quantise(_normalise(out, 0.62))


def tambourine() -> List[float]:
    count, rate = _render(0.16)
    noise = _highpass(_noise(count, 61), 7000, rate)
    out = [noise[i] * math.exp(-(i / rate) / 0.045) for i in range(count)]
    for index in range(0, count, 7):
        out[index] *= 1.25
    return _quantise(_normalise(out, 0.6))


def shaker() -> List[float]:
    count, rate = _render(0.09)
    noise = _highpass(_noise(count, 67), 8000, rate)
    out = []
    for index in range(count):
        t = index / rate
        out.append(noise[index] * math.exp(-t / 0.025) * (1.0 - math.exp(-t / 0.004)))
    return _quantise(_normalise(out, 0.45))


def cowbell() -> List[float]:
    count, rate = _render(0.22)
    out = []
    for index in range(count):
        t = index / rate
        tone = (math.sin(2 * math.pi * 540 * t) + 0.6 * math.sin(2 * math.pi * 800 * t))
        out.append(tone * math.exp(-t / 0.06))
    return _quantise(_normalise(out, 0.6))


def claves() -> List[float]:
    count, rate = _render(0.07)
    out = []
    for index in range(count):
        t = index / rate
        out.append(math.sin(2 * math.pi * 2350 * t) * math.exp(-t / 0.008))
    return _quantise(_normalise(out, 0.65))


def bongo() -> List[float]:
    return tom(320.0)


def conga() -> List[float]:
    return tom(220.0)


# How loud each piece should sit in the kit, relative to the kick. Without this the
# kick is 6 dB over the snare and a tom buries both: pieces are recorded separately,
# so they have to be balanced like a kit, not like eight unrelated files.
PIECE_LEVEL_DB = {
    "kick": 0.0, "snare": -1.5, "clap": -3.0, "rim": -7.0,
    "hat": -8.5, "openhat": -8.0, "tamb": -9.0, "shaker": -10.0,
    "tom_low": -2.0, "tom_mid": -2.5, "tom_high": -3.0,
    "bongo": -4.0, "conga": -4.0, "cowbell": -7.0, "claves": -7.5,
    "crash": -5.0, "ride": -8.5,
}
KIT_REFERENCE_DB = -13.0        # RMS a piece at 0 dB aims for


def _level_kit(kit: Dict[str, List[float]]) -> Dict[str, List[float]]:
    """Trim every piece to its place in the kit, then keep it under full scale."""
    out = {}
    for name, buffer in kit.items():
        rms = math.sqrt(sum(v * v for v in buffer) / max(1, len(buffer)))
        wanted = 10.0 ** ((KIT_REFERENCE_DB + PIECE_LEVEL_DB.get(name, -6.0)) / 20.0)
        gain = (wanted / rms) if rms > 0 else 1.0
        scaled = [v * gain for v in buffer]
        # peaks may poke past full scale: the master stage soft-clips them, and
        # squashing a snare's transient here would take its punch away
        top = max((abs(v) for v in scaled), default=0.0)
        if top > 1.35:
            scaled = [v * (1.35 / top) for v in scaled]
        out[name] = scaled
    return out


KIT: Dict[str, List[float]] = {}


def get(name: str) -> List[float]:
    """Lazily build and cache one kit piece."""
    if not KIT:
        KIT.update(_level_kit({
            "kick": kick(),
            "snare": snare(),
            "hat": hat(False),
            "openhat": hat(True),
            "tom_low": tom(105.0),
            "tom_mid": tom(150.0),
            "tom_high": tom(210.0),
            "crash": crash(),
            "clap": clap(),
            "rim": rim(),
            "ride": ride(),
            "tamb": tambourine(),
            "shaker": shaker(),
            "cowbell": cowbell(),
            "claves": claves(),
            "bongo": bongo(),
            "conga": conga(),
        }))
    if not KIT:
        get("kick")          # build the kit
    return KIT.get(name) or KIT["snare"]


def has(name: str) -> bool:
    get("kick") if not KIT else None
    return name in KIT


def for_drum(kind: str, pitch: int = 38) -> str:
    """Map a note's drum kind (and pitch, for toms) onto a kit piece."""
    if kind == "kick":
        return "kick"
    if kind == "snare":
        return "clap" if pitch in (39, 40) else "snare"
    if kind == "hat":
        return "openhat" if pitch in (46, 51) else "hat"
    if kind == "tom":
        if pitch <= 43:
            return "tom_low"
        if pitch <= 47:
            return "tom_mid"
        return "tom_high"
    return "crash"


def sample_rate() -> int:
    return DMC_RATE
