"""Virtual sound chips: NES APU plus the expansion "extension" chips.

Everything is described as channels so the arranger can treat the base console and
an extended one with the same code. Rendering knows how each kind of channel
actually behaves on hardware (4-bit volume, stepped triangle, LFSR noise, sawtooth,
wavetable), which is what makes the result sound like a console rather than a
square-wave synthesiser.
"""

from dataclasses import dataclass
from typing import Dict, List

# The NES APU's four noise periods we care about, as the hardware's period table
# looks from the outside: shorter index = higher pitch.
NOISE_PERIODS = [
    4, 8, 16, 32, 64, 96, 128, 160, 202, 254, 380, 508, 762, 1016, 2034, 4068,
]

# Drum machine mapping: General MIDI percussion note -> (noise index, short mode)
DRUM_MAP = {
    35: (13, False), 36: (13, False),          # kick
    38: (10, False), 40: (10, False),          # snare
    41: (8, False), 43: (8, False), 45: (7, False), 47: (7, False),  # toms
    42: (4, True), 44: (4, True),              # closed hat (metallic, short LFSR)
    46: (2, True), 51: (2, True),              # open hat / ride
    49: (1, True), 52: (1, True), 55: (0, True), 57: (0, True),   # crash
    39: (9, False), 53: (3, True), 54: (2, True), 56: (5, True),  # misc
}


@dataclass(frozen=True)
class ChannelSpec:
    """One voice the arranger can assign notes to."""

    id: str
    chip: str
    kind: str          # pulse | triangle | noise | saw | wavetable | fds | dmc | psg
    priority: int      # lower wins when choosing where a melody goes
    extension: str = ""   # "" = plain NES APU; otherwise the extension that adds it


# ------------------------------------------------------------------ base chips

BASE_CHANNELS: List[ChannelSpec] = [
    ChannelSpec("pulse1", "nes", "pulse", 0),
    ChannelSpec("pulse2", "nes", "pulse", 10),
    ChannelSpec("triangle", "nes", "triangle", 20),
    ChannelSpec("noise", "nes", "noise", 5),
]

# ------------------------------------------------------- extension chip families

EXTENSION_CHANNELS: Dict[str, List[ChannelSpec]] = {
    # Konami VRC6: two extra pulses and a sawtooth. The classic NES upgrade.
    "vrc6": [
        ChannelSpec("vrc6_pulse1", "vrc6", "pulse", 30, "vrc6"),
        ChannelSpec("vrc6_pulse2", "vrc6", "pulse", 40, "vrc6"),
        ChannelSpec("vrc6_saw", "vrc6", "saw", 25, "vrc6"),
    ],
    # Nintendo MMC5: two more pulses, slightly cleaner than the APU's.
    "mmc5": [
        ChannelSpec("mmc5_pulse1", "mmc5", "pulse", 35, "mmc5"),
        ChannelSpec("mmc5_pulse2", "mmc5", "pulse", 45, "mmc5"),
    ],
    # Famicom Disk System: one wavetable channel, good for leads and bass.
    "fds": [
        ChannelSpec("fds", "fds", "fds", 28, "fds"),
    ],
    # Namco 163: eight wavetable channels; the "wall of sound" extension.
    "n163": [
        ChannelSpec("n163_%d" % (i + 1), "n163", "wavetable", 50 + i, "n163")
        for i in range(8)
    ],
    # Sega Master System / Genesis PSG, as a nod to the source material.
    "psg": [
        ChannelSpec("psg1", "psg", "psg", 60, "psg"),
        ChannelSpec("psg2", "psg", "psg", 62, "psg"),
        ChannelSpec("psg3", "psg", "psg", 64, "psg"),
    ],
    # The APU's delta channel, used here as an extra percussion voice.
    "dmc": [
        ChannelSpec("dmc", "nes", "dmc", 70, "dmc"),
    ],
}

MELODIC_KINDS = {"pulse", "triangle", "saw", "fds", "wavetable", "psg"}


def build_channel_set(extensions) -> List[ChannelSpec]:
    """Every voice available for a run, base APU first."""
    channels = list(BASE_CHANNELS)
    for name in extensions:
        channels.extend(EXTENSION_CHANNELS.get(name, []))
    return channels


def channel_by_id(channels, channel_id) -> ChannelSpec:
    for channel in channels:
        if channel.id == channel_id:
            return channel
    raise KeyError(channel_id)
