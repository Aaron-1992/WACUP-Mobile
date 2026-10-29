"""Core data model shared by importers, the arranger and the renderer."""

from dataclasses import dataclass, field
from typing import List


@dataclass
class Note:
    """One musical note, in seconds, before or after chip assignment."""

    start: float
    dur: float
    pitch: int              # MIDI note number (60 = middle C)
    velocity: int = 100     # 0..127 as imported
    part: int = 0           # source part: MIDI track / FM channel / PSG channel
    role: str = "melody"    # melody | harmony | bass | drum
    program: int = 0        # MIDI program or FM algorithm, used for timbre hints
    vibrato: float = 0.0    # semitones of vibrato depth
    bend: float = 0.0       # semitone offset from pitch bend

    # filled in by the arranger
    channel: str = ""
    volume: int = 15        # 0..15, the NES volume register granularity
    duty: float = 0.5       # pulse duty cycle
    shared: bool = False    # part of an arpeggio cluster (channel sharing)
    drum: str = ""          # kick | snare | hat | tom | crash when role == drum
    noise_period: int = 9   # index into the APU noise period table
    noise_short: bool = False   # metallic mode: 93-step LFSR

    def end(self) -> float:
        return self.start + self.dur

    def copy(self) -> "Note":
        return Note(**self.__dict__)


@dataclass
class Song:
    notes: List[Note] = field(default_factory=list)
    duration: float = 0.0
    title: str = ""
    source_format: str = ""
    source_path: str = ""
    warnings: List[str] = field(default_factory=list)

    def add_warning(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def refresh_duration(self) -> None:
        if not self.notes:
            self.duration = 0.0
            return
        self.duration = max(n.end() for n in self.notes)

    def parts(self):
        """Notes grouped by source part, in first-appearance order."""
        seen = {}
        for note in sorted(self.notes, key=lambda n: n.start):
            seen.setdefault(note.part, []).append(note)
        return seen
