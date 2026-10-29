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
    """7-bit, like the delta channel's DAC — the source of the grit."""
    return [round(v * (DMC_LEVELS / 2.0)) / (DMC_LEVELS / 2.0) for v in signal]


def _render(seconds: float, rate: int = DMC_RATE):
    return int(seconds * rate), rate


# ------------------------------------------------------------------- the kit

def kick() -> List[float]:
    count, rate = _render(0.22)
    out = []
    phase = 0.0
    for index in range(count):
        t = index / rate
        # pitch drops from 150 Hz to 45 Hz in the first 60 ms
        frequency = 45.0 + 105.0 * math.exp(-t / 0.030)
        phase += 2 * math.pi * frequency / rate
        body = math.sin(phase) * math.exp(-t / 0.075)
        click = math.exp(-t / 0.004) * 0.45
        out.append(body + click)
    return _quantise(_normalise(out))


def snare() -> List[float]:
    count, rate = _render(0.24)
    noise = _highpass(_noise(count, 11), 1400, rate)
    out = []
    for index in range(count):
        t = index / rate
        tone = math.sin(2 * math.pi * 185.0 * t) * math.exp(-t / 0.030) * 0.55
        rattle = noise[index] * math.exp(-t / 0.070) * 0.9
        out.append(tone + rattle)
    return _quantise(_normalise(out))


def hat(open_hat: bool = False) -> List[float]:
    length = 0.28 if open_hat else 0.055
    count, rate = _render(length)
    noise = _highpass(_noise(count, 23 if open_hat else 17), 6000, rate)
    decay = 0.16 if open_hat else 0.018
    out = [noise[i] * math.exp(-(i / rate) / decay) for i in range(count)]
    return _quantise(_normalise(out, 0.62))


def tom(frequency: float = 160.0) -> List[float]:
    count, rate = _render(0.26)
    out = []
    phase = 0.0
    for index in range(count):
        t = index / rate
        current = frequency * (1.0 + 0.5 * math.exp(-t / 0.025))
        phase += 2 * math.pi * current / rate
        body = math.sin(phase) * math.exp(-t / 0.085)
        skin = math.exp(-t / 0.006) * 0.25
        out.append(body + skin)
    return _quantise(_normalise(out))


def crash() -> List[float]:
    count, rate = _render(0.9)
    noise = _highpass(_noise(count, 41), 3500, rate)
    out = []
    for index in range(count):
        t = index / rate
        envelope = math.exp(-t / 0.30) * (1.0 - math.exp(-t / 0.002))
        shimmer = 0.25 * math.sin(2 * math.pi * 5200 * t) * math.exp(-t / 0.12)
        out.append(noise[index] * envelope + shimmer)
    return _quantise(_normalise(out, 0.7))


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
    count, rate = _render(0.7)
    noise = _highpass(_noise(count, 53), 5000, rate)
    out = []
    for index in range(count):
        t = index / rate
        bell = (math.sin(2 * math.pi * 1180 * t) + 0.6 * math.sin(2 * math.pi * 1760 * t))
        out.append(noise[index] * math.exp(-t / 0.22) * 0.5
                   + bell * math.exp(-t / 0.18) * 0.35)
    return _quantise(_normalise(out, 0.6))


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


KIT: Dict[str, List[float]] = {}


def get(name: str) -> List[float]:
    """Lazily build and cache one kit piece."""
    if not KIT:
        KIT.update({
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
        })
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
