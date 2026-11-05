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
from typing import Dict, List, Optional

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

#: A take is one performance of a piece. Three per piece is what stops a fast drum
#: part sounding like a machine gun of one click.
TAKES = 3


def _take(take: int, spread: float) -> float:
    """A deterministic ±spread factor for take N — no randomness in the render."""
    offsets = (0.0, 0.618, -0.72, 1.31)
    return 1.0 + spread * offsets[take % len(offsets)]


def kick(take: int = 0) -> List[float]:
    """Punch, not a beep: a fast pitch drop, a beater click and a short tail."""
    count, rate = _render(0.30)
    out = []
    phase = 0.0
    for index in range(count):
        t = index / rate
        # 165 Hz down to 44 Hz in ~35 ms, the way a real kick's head tension falls
        frequency = 44.0 + 121.0 * math.exp(-t / 0.032) * _take(take, 0.05)
        phase += 2 * math.pi * frequency / rate
        body = math.sin(phase) * math.exp(-t / (0.090 * _take(take, 0.08)))
        thump = math.sin(phase * 0.5) * math.exp(-t / 0.16) * 0.25
        # the beater: harder on one take, softer on another
        click = (math.exp(-t / (0.0035 * _take(take, 0.25))) * 0.55
                 * (1.0 if index % 2 else -1.0))
        out.append(body + thump + click)
    out = _soft_clip(_normalise(out, 0.9), 1.35)
    return _quantise(_normalise(_room(out), 0.96))


def snare(take: int = 0) -> List[float]:
    """Two drum heads plus a wire rattle — the crack comes from the noise layer."""
    count, rate = _render(0.30)
    noise = _highpass(_noise(count, 11 + take * 7), 1600, rate)
    rattle = _highpass(_noise(count, 13 + take * 5), 4200, rate)
    tune = _take(take, 0.035)
    out = []
    for index in range(count):
        t = index / rate
        # heads at 185 and 278 Hz, both dropping slightly as the shell settles
        drop = 1.0 - 0.10 * min(1.0, t / 0.05)
        tone = (math.sin(2 * math.pi * 185.0 * tune * drop * t) * 0.52
                + math.sin(2 * math.pi * 278.0 * tune * drop * t) * 0.30)
        tone *= math.exp(-t / 0.045)
        crack = noise[index] * math.exp(-t / 0.012) * 0.55
        wires = rattle[index] * math.exp(-t / (0.075 * _take(take, 0.10))) * 0.55
        out.append(tone + crack + wires)
    out = _soft_clip(_normalise(out, 0.9), 1.2)
    return _quantise(_normalise(_room(out), 0.97))


def hat(open_hat: bool = False, take: int = 0) -> List[float]:
    """Metallic, not a burst of white noise: six inharmonic squares plus sizzle."""
    tune = _take(take, 0.02)
    length = (0.34 if open_hat else 0.075) * _take(take, 0.05)
    count, rate = _render(length)
    metal = _metal(tuple(f * tune for f in (205.3, 304.4, 369.6, 522.7, 540.0, 800.0)),
                   length)
    noise = _highpass(_noise(count, (23 if open_hat else 17) + take * 3), 7500, rate)
    decay = (0.19 if open_hat else 0.026) * _take(take, 0.12)
    out = []
    for index in range(count):
        t = index / rate
        envelope = math.exp(-t / decay) * (1.0 - math.exp(-t / 0.0008))
        out.append((metal[index] * 0.75 + noise[index] * 0.55) * envelope)
    out = _highpass(out, 5200.0, rate)
    return _quantise(_normalise(out, 0.6))


def tom(frequency: float = 160.0, take: int = 0) -> List[float]:
    frequency *= _take(take, 0.02)
    count, rate = _render(0.34)
    skin_noise = _highpass(_noise(count, int(frequency) + 7 + take * 3), 900, rate)
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


def crash(take: int = 0) -> List[float]:
    count, rate = _render(1.0)
    wash = _highpass(_noise(count, 41 + take * 6), 3000, rate)
    metal = _metal(tuple(f * _take(take, 0.02)
                         for f in (465.0, 697.0, 1046.0, 1568.0, 2093.0)), 1.0)
    out = []
    for index in range(count):
        t = index / rate
        envelope = math.exp(-t / 0.34) * (1.0 - math.exp(-t / 0.0015))
        bloom = math.exp(-t / 0.55) * 0.6 + 0.4
        out.append((wash[index] * 0.55 + metal[index] * 0.45 * bloom) * envelope)
    return _quantise(_normalise(out, 0.72))


def clap(take: int = 0) -> List[float]:
    count, rate = _render(0.2)
    noise = _lowpass(_highpass(_noise(count, 71 + take * 4), 900, rate), 5000, rate)
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


def rim(take: int = 0) -> List[float]:
    count, rate = _render(0.05)
    noise = _highpass(_noise(count, 91 + take * 4), 2000, rate)
    out = []
    for index in range(count):
        t = index / rate
        click = math.sin(2 * math.pi * 1750 * t) * math.exp(-t / 0.004)
        out.append(click * 0.7 + noise[index] * math.exp(-t / 0.010) * 0.5)
    return _quantise(_normalise(out, 0.7))


def ride(take: int = 0) -> List[float]:
    count, rate = _render(0.8)
    wash = _highpass(_noise(count, 53 + take * 5), 5200, rate)
    metal = _metal(tuple(f * _take(take, 0.02)
                         for f in (590.0, 883.0, 1324.0, 1985.0)), 0.8)
    out = []
    for index in range(count):
        t = index / rate
        bell = (math.sin(2 * math.pi * 1180 * t) + 0.6 * math.sin(2 * math.pi * 1760 * t))
        ping = metal[index] * math.exp(-t / 0.09) * 0.8
        out.append(wash[index] * math.exp(-t / 0.26) * 0.30
                   + bell * math.exp(-t / 0.22) * 0.25
                   + ping)
    return _quantise(_normalise(out, 0.62))


def tambourine(take: int = 0) -> List[float]:
    count, rate = _render(0.16)
    noise = _highpass(_noise(count, 61 + take * 3), 7000, rate)
    out = [noise[i] * math.exp(-(i / rate) / 0.045) for i in range(count)]
    for index in range(0, count, 7):
        out[index] *= 1.25
    return _quantise(_normalise(out, 0.6))


def shaker(take: int = 0) -> List[float]:
    count, rate = _render(0.09 * _take(take, 0.08))
    noise = _highpass(_noise(count, 67 + take * 3), 8000, rate)
    out = []
    for index in range(count):
        t = index / rate
        out.append(noise[index] * math.exp(-t / 0.025) * (1.0 - math.exp(-t / 0.004)))
    return _quantise(_normalise(out, 0.45))


def cowbell(take: int = 0) -> List[float]:
    count, rate = _render(0.22)
    out = []
    tune = _take(take, 0.02)
    for index in range(count):
        t = index / rate
        tone = (math.sin(2 * math.pi * 540 * tune * t)
                + 0.6 * math.sin(2 * math.pi * 800 * tune * t))
        out.append(tone * math.exp(-t / 0.06))
    return _quantise(_normalise(out, 0.6))


def claves(take: int = 0) -> List[float]:
    count, rate = _render(0.07)
    out = []
    for index in range(count):
        t = index / rate
        out.append(math.sin(2 * math.pi * 2350 * _take(take, 0.02) * t)
                   * math.exp(-t / 0.008))
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


class Kit:
    """A set of percussion pieces, ready to play, at one sample rate.

    Every piece has one or more *takes*: separate performances of the same drum.
    A game bank gives them for free (its kit has a sample per key); the built-in
    kit synthesises them. Which take a hit gets is chosen from the hit's position
    in the song, so a render stays byte-for-byte repeatable.
    """

    def __init__(self, pieces: Dict[str, List[List[float]]], rate: int = DMC_RATE,
                 source: str = "built-in"):
        self.pieces: Dict[str, List[List[float]]] = {}
        for name, takes in pieces.items():
            kept = [list(take) for take in takes if take]
            if kept:
                self.pieces[name] = kept
        self.rate = rate
        self.source = source                 # what to tell the user
        self.takes = sum(len(takes) for takes in self.pieces.values())
        self.key_map: Dict[int, str] = {}    # the game's own kit key -> piece name

    def has(self, piece: str) -> bool:
        return piece in self.pieces

    def names(self) -> List[str]:
        return sorted(self.pieces)

    def get(self, piece: str, variation: float = 0.5) -> List[float]:
        """One take of one piece; the nearest piece, or the snare, as a fallback."""
        takes = self.pieces.get(piece)
        if not takes:
            takes = self.pieces.get("snare") or next(iter(self.pieces.values()), [])
        if not takes:
            return []
        index = int(max(0.0, min(0.999, variation)) * len(takes))
        return takes[index]


def _level_takes(pieces: Dict[str, List[List[float]]]) -> Dict[str, List[List[float]]]:
    """Trim every take of every piece to its place in the kit."""
    out: Dict[str, List[List[float]]] = {}
    for name, takes in pieces.items():
        out[name] = [_level_kit({name: buffer})[name] for buffer in takes]
    return out


BUILTIN: Dict[str, List[List[float]]] = {}


def _builtin_takes() -> Dict[str, List[List[float]]]:
    """The synthetic kit: every piece performed three times, not recorded once."""
    pieces: Dict[str, List[List[float]]] = {}
    for take in range(TAKES):
        pieces.setdefault("kick", []).append(kick(take))
        pieces.setdefault("snare", []).append(snare(take))
        pieces.setdefault("hat", []).append(hat(False, take))
        pieces.setdefault("openhat", []).append(hat(True, take))
        pieces.setdefault("tom_low", []).append(tom(105.0, take))
        pieces.setdefault("tom_mid", []).append(tom(150.0, take))
        pieces.setdefault("tom_high", []).append(tom(210.0, take))
        pieces.setdefault("crash", []).append(crash(take))
        pieces.setdefault("clap", []).append(clap(take))
        pieces.setdefault("rim", []).append(rim(take))
        pieces.setdefault("ride", []).append(ride(take))
        pieces.setdefault("tamb", []).append(tambourine(take))
        pieces.setdefault("shaker", []).append(shaker(take))
        pieces.setdefault("cowbell", []).append(cowbell(take))
        pieces.setdefault("claves", []).append(claves(take))
        pieces.setdefault("bongo", []).append(tom(320.0, take))
        pieces.setdefault("conga", []).append(tom(220.0, take))
    return pieces


_BUILTIN_KIT: List[Kit] = []


def builtin() -> Kit:
    """The synthesised kit, built once and cached."""
    if not _BUILTIN_KIT:
        if not BUILTIN:
            BUILTIN.update(_level_takes(_builtin_takes()))
        _BUILTIN_KIT.append(Kit(BUILTIN, DMC_RATE,
                                "the built-in kit (no game file to borrow drums from)"))
    return _BUILTIN_KIT[0]


def get(name: str) -> List[float]:
    """One take of one piece of the built-in kit (the plain, unvaried hit)."""
    return builtin().get(name, 0.0)


def has(name: str) -> bool:
    return builtin().has(name)


# ------------------------------------------------------- a game's own drum kit

#: Longest we keep from a bank's percussion sample. Real delta-channel samples are
#: a fraction of a second; keeping a bank's whole 3-second cymbal would only make
#: the WAV bigger, because a hit is played for as long as its note lasts.
KIT_PIECE_LIMIT = 0.85


#: Which piece each shape of hit is, most likely first. Measured, not guessed: a DS
#: bank says nothing about its drums, and games key their kits their own way — the
#: old key-order guess called a kick keyed at 60 a "bongo". A boom that is dark and
#: tonal is a kick; a noisy mid hit is a snare; a very short bright tss is a hat.
def _classify(pcm: List[int], rate: int) -> List[str]:
    """Rank the kit pieces a decoded sample could be, from its own waveform."""
    if len(pcm) < 32 or rate <= 0:
        return []
    peak = max(abs(value) for value in pcm) or 1
    signal = [value / float(peak) for value in pcm]
    energy = sum(value * value for value in signal) or 1e-9
    differences = sum((b - a) ** 2 for a, b in zip(signal, signal[1:]))
    ratio = max(0.0, min(2.0, differences / energy))
    centroid = math.acos(1.0 - ratio / 2.0) / (2.0 * math.pi) * rate

    crossings = [index for index in range(1, len(signal))
                 if (signal[index - 1] < 0) != (signal[index] < 0)]
    gaps = [b - a for a, b in zip(crossings, crossings[1:]) if b > a]
    if len(gaps) > 3:
        mean = sum(gaps) / len(gaps)
        spread = math.sqrt(sum((gap - mean) ** 2 for gap in gaps) / len(gaps))
        jitter = spread / max(1e-9, mean)
        pitch = rate / max(1e-9, mean)
    else:
        jitter, pitch = 0.0, rate / 4.0

    tail = signal[max(1, int(len(signal) * 0.75)):]
    sustain = (sum(abs(value) for value in tail) / max(1, len(tail)))
    seconds = len(pcm) / float(rate)
    noisy = jitter > 0.45 or centroid > 5000.0

    if not noisy and pitch < 260.0:
        candidates = ["kick", "tom_low", "conga"]
    elif not noisy and pitch < 700.0:
        candidates = ["tom_low" if pitch < 180 else "tom_mid", "tom_high", "kick"]
    elif not noisy:
        candidates = ["tom_high", "conga", "rim"]
    elif seconds < 0.10 and sustain < 0.25:
        candidates = ["hat", "shaker", "claves"]
    elif seconds < 0.30 and sustain < 0.30:
        candidates = ["snare", "clap", "rim"]
    elif seconds < 0.75:
        candidates = ["openhat", "snare", "ride"]
    else:
        candidates = ["crash", "ride", "openhat"]
    if seconds < 0.06 and noisy:
        candidates = ["claves", "rim", "shaker"] + candidates
    return candidates


def _resample(pcm: List[int], source_rate: float, wanted_rate: int,
              limit: float) -> List[float]:
    """16-bit PCM at the source rate -> floats at the delta channel's rate."""
    if not pcm or source_rate <= 0:
        return []
    step = source_rate / float(wanted_rate)
    # how many output samples the whole source is worth — not how many the source
    # has: resampling 16000 Hz up to 33143 Hz makes a 72-sample wave 149 samples
    # long, and counting the source length dropped every short piece
    count = min(int(len(pcm) / step), int(limit * wanted_rate))
    out = []
    position = 0.0
    for _index in range(count):
        at = int(position)
        if at + 1 >= len(pcm):
            break
        fraction = position - at
        value = pcm[at] + (pcm[at + 1] - pcm[at]) * fraction
        out.append(value / 32768.0)
        position += step
    return out


def from_bank(archive, bank_index: int) -> Optional[Kit]:
    """The percussion a Nintendo DS bank already holds, as a playable kit.

    A DS bank stores its kit as one instrument whose keys each name their own
    sample — the kick, the snare, the hats, the toms, the cymbals, in whatever key
    order the game chose. That is the drum sound the game uses, so a conversion can
    play it instead of the built-in kit: the notes of the source music, on the
    drums of the source music. ``None`` when the bank has no kit at all.
    """
    try:
        from . import sampled            # sampled imports this module; import late
    except ImportError:                      # pragma: no cover - import cycle guard
        return None
    try:
        bank = sampled.Bank(archive, bank_index)
    except Exception:
        return None
    if not bank.kits:
        return None

    pieces: Dict[str, List[List[float]]] = {}
    key_map: Dict[int, str] = {}
    for slot, keys in sorted(bank.kits.items()):
        for key in keys:
            zone, wave = bank.zone_for(slot, key)
            if zone is None or not wave or not wave.get("pcm"):
                continue
            source_rate = float(wave.get("rate") or 32000)
            buffer = _resample(wave["pcm"], source_rate, DMC_RATE, KIT_PIECE_LIMIT)
            if len(buffer) < 64:
                continue
            buffer = _quantise(_normalise(buffer, 0.95))
            # what this hit *is*, from the hit itself: the bank's key numbering is
            # the game's own choice and says nothing about which piece it is
            candidates = _classify(wave["pcm"], int(source_rate)) or ["snare"]
            name = next((piece for piece in candidates
                         if piece not in pieces), candidates[0])
            name = _spare_name(name, pieces)
            pieces.setdefault(name, []).append(buffer)
            key_map[key] = name
    if not pieces:
        return None
    levelled = _level_takes(pieces)
    kit = Kit(levelled, DMC_RATE,
              "the game's own kit from this file's bank (%d piece%s, %d sample%s)"
              % (len(levelled), "" if len(levelled) == 1 else "s",
                 kit_takes(levelled), "" if kit_takes(levelled) == 1 else "s"))
    kit.key_map = key_map
    return kit


#: If a kit has five snares, four of them are not snares — they are the other
#: pieces nobody could measure with confidence. Extra samples become takes of a
#: *neighbouring* piece rather than piling onto one.
_SPARE = {"snare": ("clap", "rim", "tom_mid"),
          "hat": ("shaker", "tamb", "claves"),
          "kick": ("tom_low", "conga", "bongo"),
          "tom_low": ("conga", "bongo", "kick"),
          "tom_mid": ("tom_high", "conga", "bongo"),
          "tom_high": ("conga", "bongo", "claves"),
          "crash": ("ride", "openhat", "tamb"),
          "openhat": ("ride", "tamb", "shaker"),
          "clap": ("rim", "snare", "tom_mid"),
          "rim": ("claves", "cowbell", "snare"),
          "shaker": ("tamb", "claves", "hat"),
          "conga": ("bongo", "tom_low", "tom_mid"),
          "bongo": ("conga", "tom_high", "claves"),
          "ride": ("crash", "openhat", "tamb")}


def _spare_name(name: str, taken: Dict[str, List[List[float]]]) -> str:
    """A name for one more sample of a piece that is already covered."""
    if name not in taken or len(taken[name]) < TAKES:
        return name                    # a few takes of one piece is a good thing
    for other in _SPARE.get(name, ()):
        if other not in taken:
            return other
    return name


def kit_takes(pieces: Dict[str, List[List[float]]]) -> int:
    return sum(len(takes) for takes in pieces.values())


def merged_with_builtin(kit: Kit) -> Kit:
    """A game kit plus whatever the built-in kit has that the bank does not.

    A bank with six pieces and no ride should not lose its ride; but the pieces it
    *does* have must stay the game's, because those are the ones the listener
    recognises.
    """
    fallback = builtin()
    pieces: Dict[str, List[List[float]]] = {}
    for name in set(kit.pieces) | set(fallback.pieces):
        own = kit.pieces.get(name)
        pieces[name] = own if own else fallback.pieces[name]
    return Kit(pieces, DMC_RATE, kit.source)


#: Every piece a kit can hold. A note may name one of these directly — that is
#: what happens once a bank's own kit has been measured, because the name came
#: from the sample rather than from a General MIDI key.
PIECES = ("kick", "snare", "clap", "rim", "tom_low", "tom_mid", "tom_high",
          "hat", "openhat", "crash", "ride", "tamb", "shaker", "cowbell",
          "claves", "bongo", "conga")

#: What each piece is on the noise channel, for when sampled drums are switched
#: off: (period index, metallic/short mode).
NOISE_FOR = {
    "kick": (13, False), "snare": (10, False), "clap": (9, False),
    "rim": (9, False), "tom_low": (8, False), "tom_mid": (7, False),
    "tom_high": (7, False), "bongo": (8, False), "conga": (8, False),
    "hat": (4, True), "shaker": (5, True), "openhat": (2, True),
    "crash": (1, True), "ride": (3, True), "tamb": (2, True),
    "cowbell": (5, True), "claves": (4, True),
}


def noise_for(piece: str):
    """(period, short) for one piece on the noise channel."""
    return NOISE_FOR.get(piece, (9, False))


def for_drum(kind: str, pitch: int = 38) -> str:
    """Map a note's drum kind (and pitch, for toms) onto a kit piece."""
    if kind in PIECES:
        return kind                      # already the measured piece's name
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
