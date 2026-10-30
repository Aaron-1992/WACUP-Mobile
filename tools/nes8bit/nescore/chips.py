"""Virtual sound chips: NES APU plus the expansion "extension" chips.

Everything is described as channels so the arranger can treat the base console and
an extended one with the same code. Rendering knows how each kind of channel
actually behaves on hardware (4-bit volume, stepped triangle, LFSR noise, sawtooth,
wavetable, and the PC Engine's 32-step wave RAM), which is what makes the result
sound like a console rather than a square-wave synthesiser.

Two of the entries are not expansion hardware on the same cartridge but whole
other ways of playing the music:

* ``dual`` — a second NES APU wired in parallel, as in the Famicom's own add-ons
  and in the "2x NES" chips people build for tracking. Four more voices of exactly
  the hardware you already know, so a tune stops losing its harmony lines;
* ``pce`` — a Hudson HuC6280, the PC Engine's PSG: six channels, each with its own
  32-sample waveform in RAM, 5-bit volume and per-channel stereo panning. This is
  the console that can actually sound like the instruments the MIDI names.
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
    kind: str          # pulse | triangle | noise | saw | wavetable | fds | dmc |
                       # psg | huc (PC Engine wave RAM)
    priority: int      # lower wins when choosing where a melody goes
    extension: str = ""   # "" = plain NES APU; otherwise the extension that adds it
    noise_capable: bool = False   # can be switched to noise for percussion
    pannable: bool = False        # has a stereo volume of its own


# ------------------------------------------------------------------ base chips

BASE_CHANNELS: List[ChannelSpec] = [
    ChannelSpec("pulse1", "nes", "pulse", 0),
    ChannelSpec("pulse2", "nes", "pulse", 10),
    ChannelSpec("triangle", "nes", "triangle", 20),
    ChannelSpec("noise", "nes", "noise", 5),
]

# ------------------------------------------------------- extension chip families

EXTENSION_CHANNELS: Dict[str, List[ChannelSpec]] = {
    # A second NES APU, wired in parallel: two pulses, a triangle and a noise
    # channel, identical to the first console's — the cheapest way to stop
    # dropping half a tune's harmony.
    "dual": [
        ChannelSpec("nes2_pulse1", "nes2", "pulse", 22, "dual"),
        ChannelSpec("nes2_pulse2", "nes2", "pulse", 32, "dual"),
        ChannelSpec("nes2_triangle", "nes2", "triangle", 42, "dual"),
        ChannelSpec("nes2_noise", "nes2", "noise", 9, "dual"),
    ],
    # Hudson HuC6280 (PC Engine): six channels, each with its own 32-step
    # waveform, 5-bit volume and stereo panning. Channel 2 doubles as the noise
    # channel on real hardware, which is exactly what it does here.
    "pce": [
        ChannelSpec("pce1", "pce", "huc", 19, "pce", pannable=True),
        ChannelSpec("pce2", "pce", "huc", 24, "pce", pannable=True),
        ChannelSpec("pce3", "pce", "huc", 34, "pce", pannable=True),
        ChannelSpec("pce4", "pce", "huc", 46, "pce", pannable=True),
        # channels 5 and 6 of the HuC6280 can be switched to noise, so drums may
        # borrow one of them — that is the hardware's own arrangement, not ours
        ChannelSpec("pce5", "pce", "huc", 58, "pce", noise_capable=True,
                    pannable=True),
        ChannelSpec("pce6", "pce", "huc", 66, "pce", noise_capable=True,
                    pannable=True),
    ],
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

MELODIC_KINDS = {"pulse", "triangle", "saw", "fds", "wavetable", "psg", "huc"}

#: The order the window and the command line list the chips in: whole consoles
#: first, then the cartridge add-ons that only ever played one or two parts.
CHIP_ORDER: List[str] = ["dual", "pce", "vrc6", "mmc5", "fds", "n163", "psg",
                         "dmc"]

#: What each chip is called in the window.
CHIP_LABELS: Dict[str, str] = {
    "dual": "2x NES",
    "pce": "PC ENGINE",
    "vrc6": "VRC6",
    "mmc5": "MMC5",
    "fds": "FDS",
    "n163": "N163",
    "psg": "PSG",
    "dmc": "DMC",
}


def ordered_extensions() -> List[str]:
    """Every extension, in display order (a name someone stored stays valid)."""
    return [name for name in CHIP_ORDER if name in EXTENSION_CHANNELS] + \
           [name for name in EXTENSION_CHANNELS if name not in CHIP_ORDER]


def build_channel_set(extensions) -> List[ChannelSpec]:
    """Every voice available for a run, base APU first."""
    channels = list(BASE_CHANNELS)
    for name in extensions:
        channels.extend(EXTENSION_CHANNELS.get(name, []))
    return channels


def noise_channels(channels) -> List[ChannelSpec]:
    """Every channel a drum can be put on: noise, delta, or a switchable PSG."""
    return [spec for spec in channels
            if spec.kind in ("noise", "dmc") or spec.noise_capable]


def channel_by_id(channels, channel_id) -> ChannelSpec:
    for channel in channels:
        if channel.id == channel_id:
            return channel
    raise KeyError(channel_id)
