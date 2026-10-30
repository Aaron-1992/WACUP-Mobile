"""PC Engine waveforms: 32 steps of 5-bit samples, and which one to load.

The PC Engine's six PSG channels have no fixed waveform. Each channel holds 32
samples in its own little RAM, so a channel can be a square, a sawtooth, an organ,
a soft flute or a metallic bell — whatever the composer uploaded. That is the
whole reason PC Engine music sounds richer than NES music with the same number of
voices, and it is why a guitar part on a PC Engine sounds like a guitar instead of
a buzzer.

So the converter does not just add six more squares. It looks at what each note's
instrument is, and loads the wave that instrument would have been given: a
harmonically fat wave for a bass, a thin one for a flute, a sawtooth for strings,
a bright one for brass, an inharmonic one for bells. Every table here is a real
32-entry, -16..15 waveform that the chip could hold.
"""

import math
from typing import Dict, List, Tuple

from . import gm

STEPS = 32          # one cycle of the chip's wave RAM
LEVELS = 15         # 5-bit signed: -16..15, so 15 is full scale either way


def _quantise(value: float) -> float:
    """Snap to the chip's 5-bit ladder — it cannot hold anything finer."""
    level = max(-LEVELS, min(LEVELS, int(round(value * LEVELS))))
    return level / float(LEVELS)


def _harmonics(partials: List[Tuple[float, float]], steps: int = STEPS) -> List[float]:
    """Build one cycle from a list of (harmonic number, amplitude)."""
    cycle = []
    for index in range(steps):
        position = index / float(steps)
        value = sum(amplitude * math.sin(2.0 * math.pi * number * position)
                    for number, amplitude in partials)
        cycle.append(value)
    peak = max((abs(value) for value in cycle), default=0.0) or 1.0
    return [_quantise(value / peak) for value in cycle]


def _steps(high: List[float], steps: int = STEPS) -> List[float]:
    low = [-1.0] * (steps - len(high))
    return [_quantise(value) for value in high + low]


# --------------------------------------------------------------- the wave RAM

WAVES: Dict[str, List[float]] = {
    # fixed shapes, the ones a driver hard-codes for speed
    "square12": _steps([1.0] * 4),
    "square25": _steps([1.0] * 8),
    "square50": _steps([1.0] * 16),
    "square75": _steps([1.0] * 24),
    "triangle": [_quantise(4.0 * abs(step / float(STEPS) - 0.5) - 1.0)
                 for step in range(STEPS)],
    "saw": [_quantise(1.0 - 2.0 * step / float(STEPS)) for step in range(STEPS)],
    # and the shapes that make a PC Engine sound like an instrument
    "sine": _harmonics([(1, 1.0)]),
    "pipe": _harmonics([(1, 1.0), (2, 0.10), (3, 0.05)]),
    "reed": _harmonics([(1, 1.0), (3, 0.45), (5, 0.22), (7, 0.10)]),
    "organ": _harmonics([(1, 1.0), (2, 0.5), (4, 0.35), (8, 0.18)]),
    "piano": _harmonics([(1, 1.0), (2, 0.5), (3, 0.3), (4, 0.15), (5, 0.08)]),
    "guitar": _harmonics([(1, 1.0), (2, 0.4), (3, 0.35), (4, 0.15), (5, 0.12),
                          (6, 0.08)]),
    "strings": _harmonics([(1, 1.0), (2, 0.6), (3, 0.45), (4, 0.3), (5, 0.2),
                           (6, 0.12)]),
    "brass": _harmonics([(1, 1.0), (2, 0.55), (3, 0.35), (4, 0.2), (5, 0.1)]),
    "bass": _harmonics([(1, 1.0), (2, 0.45), (3, 0.2)]),
    "pluck": _harmonics([(1, 1.0), (2, 0.3), (3, 0.18)]),
    "pad": _harmonics([(1, 1.0), (2, 0.35), (3, 0.18), (4, 0.08)]),
    "metal": _harmonics([(1, 1.0), (4, 0.6), (7, 0.4), (11, 0.25)]),
}

#: A short name for each wave, for the window and the stats.
LABELS: Dict[str, str] = {
    "square12": "PULSE 12", "square25": "PULSE 25", "square50": "SQUARE",
    "square75": "PULSE 75", "triangle": "TRIANGLE", "saw": "SAW",
    "sine": "SINE", "pipe": "FLUTE", "reed": "REED", "organ": "ORGAN",
    "piano": "PIANO", "guitar": "GUITAR", "strings": "STRINGS",
    "brass": "BRASS", "bass": "BASS", "pluck": "PLUCK", "pad": "PAD",
    "metal": "METAL",
}

# How each General MIDI family should be loaded into the wave RAM.
_FAMILY_WAVE: Dict[str, str] = {
    "piano": "piano",
    "chromatic": "metal",       # celesta, glockenspiel, music box: bright and thin
    "organ": "organ",
    "guitar": "guitar",
    "bass": "bass",
    "strings": "strings",
    "ensemble": "strings",
    "brass": "brass",
    "reed": "reed",
    "pipe": "pipe",
    "lead": "square25",
    "pad": "pad",
    "fx": "metal",
    "ethnic": "pluck",
    "percussive": "pluck",
    "sfx": "metal",
}


def for_duty(duty: float) -> str:
    """The fixed pulse shape closest to a duty cycle."""
    if duty <= 0.1875:
        return "square12"
    if duty <= 0.375:
        return "square25"
    if duty <= 0.625:
        return "square50"
    return "square75"


def for_instrument(program: int, role: str = "melody", pitch: int = 60) -> str:
    """Which wave this note's instrument would have been given.

    Two rules on top of the family table, both of them things a PC Engine
    composer does by hand: a lead follows the pulse duty the MIDI asked for, and
    a part three octaves up gets a simpler wave, because a bright wave up there is
    aliasing and hiss rather than brightness.
    """
    family = gm.family(program)
    if role == "bass":
        return "bass"
    if family == "lead":
        _kind, duty = gm.timbre(program)
        return for_duty(duty)
    # chromatic percussion (bells, glockenspiel) wants a metallic wave, not a
    # detuned piano, and the family table above already says so
    wave = _FAMILY_WAVE.get(family, "square50")
    if pitch >= 88 and wave in ("strings", "brass", "guitar", "metal",
                                "organ", "piano"):
        return "square25"           # above C6 a busy wave is just fizz
    if pitch <= 40 and wave in ("pipe", "sine", "square12"):
        return "bass"               # a thin wave down there has no body
    return wave


def level(wave: str) -> List[float]:
    """The 32 steps of a named wave, ready to be clocked out."""
    return WAVES.get(wave) or WAVES["square50"]


def describe(wave: str) -> str:
    return LABELS.get(wave, wave.upper())
