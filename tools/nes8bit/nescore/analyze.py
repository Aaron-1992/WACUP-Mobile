"""Read the MIDI like a musician would, before touching any chip.

A MIDI track is not a part: a piano track is ten fingers on one channel, a string
pad is four sustained notes, and the "melody" track is often the one with the
highest line. So the analysis does three things:

1. **Splits every track into monophonic voices** by voice leading — each new note
   continues whichever free voice is closest in pitch. A chord becomes three or
   four voices, a run of eighth notes stays one line.
2. **Names each voice's job** — melody, counter-melody, bass, harmony, pad,
   rhythm or percussion — from its register, movement, note lengths and the
   General MIDI instrument it is played on.
3. **Describes the song in words**, so the window can show what it understood.

Everything downstream (arrangement, channel choice, drum kit) is driven by this,
which is why the converter stops treating a chord as an accident.
"""

from dataclasses import dataclass, field
from typing import Dict, List

from . import gm
from .model import Note, Song

ROLES = ("melody", "counter", "bass", "harmony", "rhythm", "drum")


@dataclass
class Voice:
    """One monophonic line, extracted from a track."""

    id: int
    part: int
    notes: List[Note] = field(default_factory=list)
    track_name: str = ""
    program: int = 0
    role: str = "harmony"
    register: float = 60.0
    span: float = 0.0
    mean_duration: float = 0.0
    density: float = 0.0
    stepwise: float = 0.0
    repeated: float = 0.0
    chord_tone: bool = False
    salience: float = 0.0
    scores: Dict[str, float] = field(default_factory=dict)

    @property
    def instrument(self) -> str:
        return gm.name(self.program)

    @property
    def family(self) -> str:
        return gm.family(self.program)

    def summary(self) -> str:
        label = self.track_name or self.instrument
        return "%s · %s · %d notes · %s-%s" % (
            label, self.role, len(self.notes),
            gm.pitch_name(min(n.pitch for n in self.notes)),
            gm.pitch_name(max(n.pitch for n in self.notes)))


@dataclass
class Analysis:
    voices: List[Voice] = field(default_factory=list)
    tempo: float = 120.0
    meter: str = "4/4"
    key: str = ""
    seconds: float = 0.0
    chord_moments: int = 0
    simultaneous: int = 0
    tracks: List[str] = field(default_factory=list)
    instrument_names: List[str] = field(default_factory=list)
    notes: int = 0

    def of_role(self, role: str) -> List[Voice]:
        return [voice for voice in self.voices if voice.role == role]

    def summary_lines(self) -> List[str]:
        """The story of what the file contained, for the window."""
        tempo = ("%.0f BPM" % self.tempo) if self.tempo else "tempo unknown"
        tail = (" · " + self.key) if self.key else ""
        lines = ["%s · %s · %.1f s · %d notes%s" % (tempo, self.meter, self.seconds,
                                                    self.notes, tail)]
        if self.instrument_names:
            names = self.instrument_names[:6]
            more = "" if len(self.instrument_names) <= 6 else \
                " and %d more" % (len(self.instrument_names) - 6)
            lines.append("Instruments: " + ", ".join(names) + more)

        counts = {}
        for voice in self.voices:
            counts[voice.role] = counts.get(voice.role, 0) + 1
        if counts:
            order = [role for role in ROLES if role in counts]
            lines.append("Found " + ", ".join(
                "%d %s" % (counts[role], role) for role in order) +
                " (%d voices)" % len(self.voices))

        if self.chord_moments:
            lines.append("%d chord moments — chord notes get their own channels"
                         % self.chord_moments)
        return lines


# --------------------------------------------------------------- voice leading

def _split_part(notes: List[Note], max_voices: int = 4) -> List[List[Note]]:
    """Voice-lead a polyphonic track into monophonic lines."""
    voices: List[dict] = []
    for note in sorted(notes, key=lambda n: (n.start, n.pitch)):
        free = [v for v in voices if v["end"] <= note.start + 1e-4]
        if free:
            # continue the closest line — that is what voice leading means
            target = min(free, key=lambda v: abs(note.pitch - v["pitch"]))
        elif len(voices) < max_voices:
            target = {"notes": [], "end": 0.0, "pitch": note.pitch}
            voices.append(target)
        else:
            target = min(voices, key=lambda v: (abs(note.pitch - v["pitch"]),
                                                v["end"]))
        target["notes"].append(note)
        target["end"] = max(target["end"], note.end())
        target["pitch"] = note.pitch
    return [v["notes"] for v in voices if v["notes"]]


def _features(notes: List[Note], voice_index: int) -> Dict[str, float]:
    ordered = sorted(notes, key=lambda n: n.start)
    span = max(n.end() for n in ordered) - ordered[0].start
    span = max(0.5, span)
    pitches = [n.pitch for n in ordered]
    mean_pitch = sum(pitches) / len(pitches)
    mean_duration = sum(n.dur for n in ordered) / len(ordered)

    steps = 0
    for previous, current in zip(ordered, ordered[1:]):
        if abs(current.pitch - previous.pitch) <= 2:
            steps += 1
    stepwise = steps / max(1, len(ordered) - 1)

    repeated = 0
    for previous, current in zip(ordered, ordered[1:]):
        if current.pitch == previous.pitch:
            repeated += 1
    repeated_ratio = repeated / max(1, len(ordered) - 1)

    return {
        "register": mean_pitch,
        "low": min(pitches),
        "high": max(pitches),
        "span": span,
        "mean_duration": mean_duration,
        "density": len(ordered) / span,
        "stepwise": stepwise,
        "repeated": repeated_ratio,
        "chord_tone": 1.0 if voice_index > 0 else 0.0,
        "distinct": len(set(pitches)) / len(pitches),
    }


def _score_roles(features: Dict[str, float], program: int) -> Dict[str, float]:
    bass_t, melody_t, harmony_t, rhythm_t, sustained_t = gm.tendency(program)
    register = features["register"]
    duration = features["mean_duration"]

    low_register = 5.0 if register < 48 else 3.0 if register < 55 else 0.0
    high_register = 4.0 if register > 66 else 2.0 if register > 58 else 0.0
    short_notes = 2.0 if duration < 0.18 else 0.0
    long_notes = 2.5 if duration > 0.6 else 0.0

    scores = {
        "bass": low_register + 3.5 * bass_t + long_notes * 0.6,
        "melody": high_register + 3.5 * melody_t + 2.0 * features["stepwise"]
                  + 2.0 * features["distinct"] + short_notes * 0.5,
        "harmony": 3.0 * harmony_t + 2.5 * features["chord_tone"] + long_notes,
        "rhythm": 3.0 * rhythm_t + 2.0 * short_notes + 2.0 * features["repeated"],
        "counter": high_register * 0.5 + 2.0 * features["stepwise"] + 1.0 * long_notes,
    }
    if features["chord_tone"]:
        # a chord tone is harmony, however high it sits: the top of a chord is
        # not automatically the tune
        scores["melody"] -= 6.0
        scores["counter"] -= 3.0
        scores["harmony"] += 4.0
    if sustained_t >= 3 and features["chord_tone"]:
        scores["harmony"] += 1.5
    return scores


# ------------------------------------------------------------------- analysis

def analyse(song: Song) -> Analysis:
    """Split, classify and describe. Also stamps role onto every note."""
    analysis = Analysis()
    analysis.tempo = float(getattr(song, "tempo", 0.0) or 0.0)
    analysis.meter = getattr(song, "meter", "") or "4/4"
    analysis.key = getattr(song, "key", "") or ""
    analysis.tracks = list(getattr(song, "track_names", []) or [])
    analysis.seconds = song.duration
    analysis.notes = len(song.notes)

    parts: Dict[int, List[Note]] = {}
    for note in song.notes:
        parts.setdefault(note.part, []).append(note)

    # chords: how often three or more notes of one track sound together
    analysis.chord_moments = _count_chords(parts)
    analysis.simultaneous = _max_simultaneous(parts)

    voices: List[Voice] = []
    percussion = False
    for part, notes in sorted(parts.items()):
        if notes and notes[0].role == "drum":
            percussion = True
            voice = Voice(id=len(voices), part=part, notes=sorted(notes, key=lambda n: n.start),
                          track_name=notes[0].track_name, role="drum", program=0)
            voices.append(voice)
            continue

        track_name = ""
        program = 0
        for note in notes:
            if note.track_name:
                track_name = note.track_name
                break
        for note in notes:
            if note.program:
                program = note.program
                break

        for index, line in enumerate(_split_part(notes)):
            voice = Voice(id=len(voices), part=part, notes=line,
                          track_name=track_name, program=program)
            features = _features(line, index)
            voice.register = features["register"]
            voice.span = features["span"]
            voice.mean_duration = features["mean_duration"]
            voice.density = features["density"]
            voice.stepwise = features["stepwise"]
            voice.repeated = features["repeated"]
            voice.chord_tone = bool(index)
            voice.scores = _score_roles(features, program)
            voice.role = max(voice.scores, key=lambda role: voice.scores[role])
            voice.salience = (voice.scores.get(voice.role, 0.0)
                              + 0.5 * len(line) ** 0.5)
            voices.append(voice)

    _settle_roles(voices, percussion)

    for voice in voices:
        for note in voice.notes:
            note.role = voice.role
            note.voice = voice.id

    names = []
    for voice in voices:
        if voice.role == "drum" or not voice.notes:
            continue
        label = voice.instrument
        if label not in names:
            names.append(label)
    if percussion and "Drums" not in names:
        names.append("Drums")

    analysis.voices = voices
    analysis.instrument_names = names
    return analysis


def _settle_roles(voices: List[Voice], percussion: bool) -> None:
    """Make the result musical: there has to be one tune and one bass."""
    melodic = [v for v in voices if v.role != "drum"]
    if not melodic:
        return

    melodies = [v for v in melodic if v.role == "melody"]
    if not melodies:
        # promote the voice that most looks like a tune: high and moving
        candidate = max(melodic, key=lambda v: (v.scores.get("melody", 0.0),
                                                v.register))
        if candidate.scores.get("melody", 0) > 0:
            candidate.role = "melody"
            melodies = [candidate]

    if melodies:
        # only the most prominent one keeps the name; the rest are inner lines
        melodies.sort(key=lambda v: (-v.register, -len(v.notes)))
        for extra in melodies[1:]:
            extra.role = "harmony" if extra.chord_tone else "counter"

    basses = [v for v in melodic if v.role == "bass"]
    if not basses:
        candidate = min(melodic, key=lambda v: (v.register, -len(v.notes)))
        if candidate.register < 58 and candidate.role != "melody":
            candidate.role = "bass"
    elif len(basses) > 1:
        # keep the lowest as the real bass, the others become low harmony
        basses.sort(key=lambda v: v.register)
        for extra in basses[1:]:
            extra.role = "harmony"

    if percussion:
        for voice in voices:
            if voice.role == "drum":
                voice.salience = 100.0


def _count_chords(parts: Dict[int, List[Note]]) -> int:
    moments = 0
    for notes in parts.values():
        ordered = sorted(notes, key=lambda n: n.start)
        index = 0
        while index < len(ordered):
            start = ordered[index].start
            group = [n for n in ordered if abs(n.start - start) < 0.02]
            if len(group) >= 3:
                moments += 1
            index += len(group)
    return moments


def _max_simultaneous(parts: Dict[int, List[Note]]) -> int:
    best = 0
    for notes in parts.values():
        points = sorted([(n.start, 1) for n in notes] +
                        [(n.end(), -1) for n in notes])
        current = 0
        for _time, delta in points:
            current += delta
            best = max(best, current)
    return best


def describe(song: Song) -> List[str]:
    """Short human summary, used by the command line."""
    analysis = analyse(song)
    return analysis.summary_lines() + [voice.summary() for voice in analysis.voices]
