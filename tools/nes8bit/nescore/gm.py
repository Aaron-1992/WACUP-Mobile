"""General MIDI knowledge: instrument names, families, and the drum map.

Understanding a MIDI file starts here. A program number is not a number, it is a
name — "Synth Bass 1" tells the arranger to reach for the triangle; "Lead 2
(sawtooth)" says a 25 % pulse will do the job; "Timpani" says this is a tom.
"""

from typing import Dict, List, Tuple

INSTRUMENT_NAMES: List[str] = [
    "Acoustic Grand Piano", "Bright Acoustic Piano", "Electric Grand Piano",
    "Honky-tonk Piano", "Electric Piano 1", "Electric Piano 2", "Harpsichord",
    "Clavinet", "Celesta", "Glockenspiel", "Music Box", "Vibraphone",
    "Marimba", "Xylophone", "Tubular Bells", "Dulcimer",
    "Drawbar Organ", "Percussive Organ", "Rock Organ", "Church Organ",
    "Reed Organ", "Accordion", "Harmonica", "Tango Accordion",
    "Acoustic Guitar (nylon)", "Acoustic Guitar (steel)", "Electric Guitar (jazz)",
    "Electric Guitar (clean)", "Electric Guitar (muted)", "Overdriven Guitar",
    "Distortion Guitar", "Guitar Harmonics",
    "Acoustic Bass", "Electric Bass (finger)", "Electric Bass (pick)",
    "Fretless Bass", "Slap Bass 1", "Slap Bass 2", "Synth Bass 1", "Synth Bass 2",
    "Violin", "Viola", "Cello", "Contrabass", "Tremolo Strings",
    "Pizzicato Strings", "Orchestral Harp", "Timpani",
    "String Ensemble 1", "String Ensemble 2", "Synth Strings 1", "Synth Strings 2",
    "Choir Aahs", "Voice Oohs", "Synth Voice", "Orchestra Hit",
    "Trumpet", "Trombone", "Tuba", "Muted Trumpet", "French Horn",
    "Brass Section", "Synth Brass 1", "Synth Brass 2",
    "Soprano Sax", "Alto Sax", "Tenor Sax", "Baritone Sax", "Oboe",
    "English Horn", "Bassoon", "Clarinet",
    "Piccolo", "Flute", "Recorder", "Pan Flute", "Blown Bottle",
    "Shakuhachi", "Whistle", "Ocarina",
    "Lead 1 (square)", "Lead 2 (sawtooth)", "Lead 3 (calliope)", "Lead 4 (chiff)",
    "Lead 5 (charang)", "Lead 6 (voice)", "Lead 7 (fifths)", "Lead 8 (bass + lead)",
    "Pad 1 (new age)", "Pad 2 (warm)", "Pad 3 (polysynth)", "Pad 4 (choir)",
    "Pad 5 (bowed)", "Pad 6 (metallic)", "Pad 7 (halo)", "Pad 8 (sweep)",
    "FX 1 (rain)", "FX 2 (soundtrack)", "FX 3 (crystal)", "FX 4 (atmosphere)",
    "FX 5 (brightness)", "FX 6 (goblins)", "FX 7 (echoes)", "FX 8 (sci-fi)",
    "Sitar", "Banjo", "Shamisen", "Koto", "Kalimba", "Bag pipe", "Fiddle", "Shanai",
    "Tinkle Bell", "Agogo", "Steel Drums", "Woodblock", "Taiko Drum",
    "Melodic Tom", "Synth Drum", "Reverse Cymbal",
    "Guitar Fret Noise", "Breath Noise", "Seashore", "Bird Tweet",
    "Telephone Ring", "Helicopter", "Applause", "Gunshot",
]

FAMILIES: Dict[str, Tuple[int, int]] = {
    "piano": (0, 7), "chromatic": (8, 15), "organ": (16, 23), "guitar": (24, 31),
    "bass": (32, 39), "strings": (40, 47), "ensemble": (48, 55), "brass": (56, 63),
    "reed": (64, 71), "pipe": (72, 79), "lead": (80, 87), "pad": (88, 95),
    "fx": (96, 103), "ethnic": (104, 111), "percussive": (112, 119),
    "sfx": (120, 127),
}

# How each family tends to behave musically, used as a prior — never as a fact.
# (bass, melody, harmony, rhythm, sustained)
FAMILY_TENDENCY = {
    "piano": (0, 1, 2, 1, 1),
    "chromatic": (0, 1, 1, 1, 0),
    "organ": (1, 1, 2, 0, 2),
    "guitar": (1, 1, 2, 1, 1),
    "bass": (4, 0, 0, 0, 2),
    "strings": (0, 1, 3, 0, 3),
    "ensemble": (0, 1, 3, 0, 3),
    "brass": (1, 2, 2, 0, 1),
    "reed": (1, 2, 1, 0, 1),
    "pipe": (0, 3, 1, 0, 1),
    "lead": (0, 4, 0, 0, 0),
    "pad": (0, 0, 3, 0, 3),
    "fx": (0, 0, 2, 0, 2),
    "ethnic": (1, 2, 1, 1, 0),
    "percussive": (0, 1, 1, 3, 0),
    "sfx": (0, 0, 1, 1, 0),
}

# The NES has two pulse duties worth using and one triangle. Timbre hints pick
# between them; they never override what the music is doing.
FAMILY_TIMBRE = {
    "bass": ("triangle", 0.5),
    "lead": ("pulse", 0.25),
    "pipe": ("pulse", 0.5),
    "reed": ("pulse", 0.5),
    "brass": ("pulse", 0.25),
    "strings": ("pulse", 0.5),
    "ensemble": ("pulse", 0.5),
    "pad": ("pulse", 0.125),
    "organ": ("pulse", 0.5),
    "guitar": ("pulse", 0.25),
    "piano": ("pulse", 0.5),
    "chromatic": ("pulse", 0.125),
    "percussive": ("pulse", 0.125),
}


def family(program: int) -> str:
    program = max(0, min(127, int(program)))
    for name, (low, high) in FAMILIES.items():
        if low <= program <= high:
            return name
    return "piano"


def name(program: int) -> str:
    return INSTRUMENT_NAMES[max(0, min(127, int(program)))]


def tendency(program: int) -> Tuple[int, int, int, int, int]:
    return FAMILY_TENDENCY.get(family(program), (0, 1, 1, 0, 1))


def timbre(program: int) -> Tuple[str, float]:
    """(preferred channel kind, pulse duty) for this instrument."""
    return FAMILY_TIMBRE.get(family(program), ("pulse", 0.5))


# --------------------------------------------------------------- percussion

# General MIDI percussion: note -> (kind, sample in samples.py)
PERCUSSION: Dict[int, Tuple[str, str]] = {
    27: ("hat", "hat"), 28: ("hat", "hat"),
    35: ("kick", "kick"), 36: ("kick", "kick"),
    37: ("rim", "rim"), 38: ("snare", "snare"), 39: ("clap", "clap"),
    40: ("snare", "snare"), 41: ("tom_low", "tom_low"), 42: ("hat", "hat"),
    43: ("tom_low", "tom_low"), 44: ("hat", "hat"), 45: ("tom_mid", "tom_mid"),
    46: ("openhat", "openhat"), 47: ("tom_mid", "tom_mid"),
    48: ("tom_high", "tom_high"), 49: ("crash", "crash"),
    50: ("tom_high", "tom_high"), 51: ("ride", "ride"), 52: ("crash", "crash"),
    53: ("ride", "ride"), 54: ("tamb", "tamb"), 55: ("crash", "crash"),
    56: ("cowbell", "cowbell"), 57: ("crash", "crash"), 58: ("shaker", "shaker"),
    59: ("ride", "ride"), 60: ("bongo", "bongo"), 61: ("bongo", "bongo"),
    62: ("conga", "conga"), 63: ("conga", "conga"), 64: ("conga", "conga"),
    65: ("conga", "conga"), 66: ("shaker", "shaker"), 67: ("shaker", "shaker"),
    68: ("shaker", "shaker"), 69: ("shaker", "shaker"), 70: ("shaker", "shaker"),
    71: ("shaker", "shaker"), 72: ("shaker", "shaker"), 73: ("shaker", "shaker"),
    74: ("shaker", "shaker"), 75: ("claves", "claves"), 76: ("claves", "claves"),
    77: ("claves", "claves"), 78: ("claves", "claves"), 79: ("claves", "claves"),
    80: ("claves", "claves"), 81: ("claves", "claves"),
}


def percussion(pitch: int) -> Tuple[str, str]:
    return PERCUSSION.get(int(pitch), ("snare", "snare"))


PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def pitch_name(pitch: int) -> str:
    pitch = int(round(pitch))
    return "%s%d" % (PITCH_NAMES[pitch % 12], pitch // 12 - 1)
