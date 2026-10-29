"""Arrangement: put notes onto console channels, sharing them out when it runs out.

The rules are the ones an NES composer uses by hand:

* percussion goes to the noise channel (and the DMC, if enabled);
* the triangle takes the bass, because that is what it is good at;
* pulses take melody and harmony, with the extension chips (VRC6 / MMC5 / FDS /
  Namco 163 / PSG) absorbing everything that is left;
* a note that has nowhere to go is first pushed onto *any* free channel whose
  waveform can plausibly play it ("split into the other channels if there is free
  space"), and only when the console is genuinely full does the arranger fall back
  to channel sharing: the clashing notes take turns as a fast arpeggio, exactly
  how NES soundtracks fake chords.
"""

from bisect import bisect_left
from dataclasses import dataclass, field
from typing import Dict, List

from .chips import DRUM_MAP, MELODIC_KINDS, ChannelSpec
from .model import Note, Song

# Preferred channel kinds per musical role, best first.
ROLE_PREFERENCE = {
    "melody": ["pulse", "saw", "fds", "wavetable", "psg", "triangle"],
    "harmony": ["pulse", "saw", "wavetable", "psg", "fds", "triangle"],
    "bass": ["triangle", "saw", "fds", "psg", "wavetable", "pulse"],
    "drum": ["noise", "dmc"],
}

# How loud each kind sits in the mix, so parts balance the way a real track does.
KIND_GAIN = {
    "pulse": 0.55,
    "triangle": 0.65,
    "noise": 0.35,
    "saw": 0.42,
    "fds": 0.5,
    "wavetable": 0.4,
    "psg": 0.45,
    "dmc": 0.4,
}


@dataclass
class Options:
    fps: float = 60.0988          # NTSC NES frame rate
    arp_frames: int = 2           # frames each pitch of a shared channel gets
    allow_sharing: bool = True
    transpose: int = 0
    max_notes_per_channel: int = 0    # 0 = unlimited
    quantize: bool = True
    min_duration: float = 0.03
    quietest: int = 6             # drop notes quieter than this velocity


@dataclass
class Stats:
    direct: int = 0               # landed on a channel of the preferred kind
    overflow: int = 0             # landed on another kind because it was free
    shared: int = 0               # had to share a channel as an arpeggio
    dropped: int = 0              # too short / too quiet / unplaceable
    channels_used: Dict[str, int] = field(default_factory=dict)
    per_channel_notes: Dict[str, int] = field(default_factory=dict)
    clusters: int = 0

    def as_lines(self) -> List[str]:
        lines = [
            "  notes placed directly on a suited channel : %d" % self.direct,
            "  notes re-homed onto a free spare channel   : %d" % self.overflow,
            "  notes merged into arpeggio clusters        : %d" % self.shared,
            "  notes dropped (too short/quiet)            : %d" % self.dropped,
            "  channel-sharing clusters                   : %d" % self.clusters,
            "  voices used                                : %d" % len(self.per_channel_notes),
        ]
        for channel in sorted(self.per_channel_notes):
            lines.append("    %-14s %5d notes" % (channel, self.per_channel_notes[channel]))
        return lines


@dataclass
class _Cluster:
    channel: str
    start: float
    end: float
    notes: List[Note] = field(default_factory=list)

    def add(self, note: Note) -> None:
        self.notes.append(note)
        self.end = max(self.end, note.end())


def _role_for_part(notes: List[Note]) -> str:
    """Guess a part's job from its register and chord role."""
    if not notes:
        return "harmony"
    if notes[0].role == "drum":
        return "drum"
    pitches = sorted(n.pitch for n in notes)
    median = pitches[len(pitches) // 2]
    average = sum(pitches) / len(pitches)
    # A part that lives low and moves slowly is the bass.
    if average < 52:
        return "bass"
    if average > 72:
        return "melody"
    if median < 60:
        return "harmony"
    return "harmony"


def classify(song: Song) -> Dict[int, str]:
    """Assign a role to every source part; drum tracks are detected upstream."""
    roles: Dict[int, str] = {}
    parts = song.parts()

    # Mono tracks that sit highest are usually the lead, so pick the top one as melody.
    melodic_parts = [(pid, notes) for pid, notes in parts.items()
                     if notes and notes[0].role != "drum"]
    melodic_parts.sort(key=lambda item: -max(n.pitch for n in item[1]))

    for index, (pid, notes) in enumerate(melodic_parts):
        if notes[0].role == "drum":
            roles[pid] = "drum"
            continue
        guess = _role_for_part(notes)
        if index == 0 and guess != "bass":
            guess = "melody"
        roles[pid] = guess

    for pid, notes in parts.items():
        if notes and notes[0].role == "drum":
            roles[pid] = "drum"

    for note in song.notes:
        note.role = roles.get(note.part, "harmony")
    return roles


def _velocity_to_level(velocity: int, role: str) -> int:
    """Velocity -> the NES's 0..15 volume register, with a musical curve."""
    if velocity <= 0:
        return 0
    shaped = (velocity / 127.0) ** 0.75
    base = 4 + shaped * 11.0
    # harmony sits under the lead: a chord is three voices doing the work of one
    if role == "harmony":
        base *= 0.85
    elif role == "drum":
        base *= 1.05
    return max(0, min(15, int(round(base))))


def _duty_for(note: Note) -> float:
    """Pick a pulse duty that suits the part (25% is the classic lead sound)."""
    if note.role == "bass":
        return 0.5
    if note.role == "harmony":
        return 0.25 if (note.pitch % 3) else 0.5
    # melody: brighter as the program number suggests a lead instrument
    if note.program in (80, 81, 82, 84, 85, 86, 87):
        return 0.25          # synth leads and leads
    return 0.5 if note.pitch < 72 else 0.25


class _ChannelState:
    """Notes currently sounding on one channel, used for overlap checks."""

    def __init__(self, spec: ChannelSpec):
        self.spec = spec
        self.active: List[dict] = []      # {"note": Note, "cluster": _Cluster|None}
        self.used = False

    def prune(self, now: float) -> None:
        self.active = [entry for entry in self.active
                       if entry["note"].end() > now - 0.001]

    def conflicts(self, start: float, end: float) -> List[dict]:
        return [entry for entry in self.active
                if entry["note"].start < end - 0.001
                and entry["note"].end() > start + 0.001]

    def free_at(self, start: float, end: float) -> bool:
        return not self.conflicts(start, end)


def arrange(song: Song, channels: List[ChannelSpec], options: Options):
    """Place every note on a channel; returns (notes, stats)."""
    classify(song)
    stats = Stats()

    by_kind: Dict[str, List[_ChannelState]] = {}
    states: Dict[str, _ChannelState] = {}
    for spec in channels:
        state = _ChannelState(spec)
        states[spec.id] = state
        by_kind.setdefault(spec.kind, []).append(state)

    for kind in by_kind:
        by_kind[kind].sort(key=lambda s: s.spec.priority)

    clusters: List[_Cluster] = []
    placed: List[Note] = []

    for note in sorted(song.notes, key=lambda n: (n.start, -n.pitch)):
        if note.dur < options.min_duration or note.velocity < options.quietest:
            stats.dropped += 1
            continue
        if options.transpose:
            note.pitch = max(0, min(127, note.pitch + options.transpose))

        for state in states.values():
            state.prune(note.start)

        role = note.role if note.role in ROLE_PREFERENCE else "harmony"
        wanted_kinds = ROLE_PREFERENCE[role]

        drum = note.role == "drum"
        if drum:
            note.drum = _drum_kind(note.pitch)
            period, short = DRUM_MAP.get(note.pitch, (9, False))
            note.noise_period = period
            note.noise_short = short

        # 1) a free channel of a kind the part actually wants
        chosen = None
        for kind in wanted_kinds:
            for state in by_kind.get(kind, []):
                if state.free_at(note.start, note.end()):
                    chosen = state
                    stats.direct += 1
                    break
            if chosen:
                break

        # 2) any free melodic channel, whatever chip it belongs to
        if chosen is None and (not drum):
            for kind in sorted(by_kind, key=lambda k: by_kind[k][0].spec.priority):
                if kind in ("noise", "dmc"):
                    continue
                if kind not in MELODIC_KINDS:
                    continue
                for state in by_kind[kind]:
                    if state.free_at(note.start, note.end()):
                        chosen = state
                        stats.overflow += 1
                        break
                if chosen:
                    break

        # 3) still nothing: borrow a channel and arpeggiate
        if chosen is None and options.allow_sharing:
            candidates = []
            for kind in wanted_kinds + sorted(MELODIC_KINDS):
                for state in by_kind.get(kind, []):
                    conflicts = state.conflicts(note.start, note.end())
                    if conflicts:
                        candidates.append((len(conflicts), state.spec.priority, state,
                                           conflicts))
            if candidates:
                candidates.sort(key=lambda item: (item[0], item[1]))
                _, _, state, conflicts = candidates[0]
                chosen = state
                existing = next((entry for entry in conflicts if entry["cluster"]), None)
                if existing is not None:
                    cluster = existing["cluster"]
                else:
                    victim = conflicts[0]["note"]
                    cluster = _Cluster(state.spec.id, victim.start, victim.end())
                    cluster.add(victim)
                    for entry in conflicts:
                        if entry["note"] is victim:
                            entry["cluster"] = cluster
                    clusters.append(cluster)
                cluster.add(note)
                state.active.append({"note": note, "cluster": cluster})
                stats.shared += 1
                continue

        if chosen is None:
            stats.dropped += 1
            continue

        note.channel = chosen.spec.id
        note.volume = _velocity_to_level(note.velocity, note.role)
        note.duty = _duty_for(note)
        if drum:
            note.volume = max(6, note.volume)
        _apply_envelope(note, chosen.spec)
        chosen.active.append({"note": note, "cluster": None})
        chosen.used = True
        placed.append(note)

    # Turn every cluster into a fast arpeggio: the pitches take turns.
    arpeggiated = _expand_clusters(clusters, states, options, stats)

    notes_out = [n for n in placed if not _in_cluster(n, clusters)] + arpeggiated

    if options.quantize and options.fps > 0:
        notes_out = _quantize(notes_out, options.fps)

    notes_out.sort(key=lambda n: (n.start, n.pitch))
    stats.clusters = len(clusters)
    stats.per_channel_notes = {}
    for note in notes_out:
        stats.per_channel_notes[note.channel] = \
            stats.per_channel_notes.get(note.channel, 0) + 1
    return notes_out, stats


def _drum_kind(pitch: int) -> str:
    if pitch <= 37:
        return "kick"
    if pitch <= 40:
        return "snare"
    if pitch <= 46:
        return "hat"
    if pitch <= 50:
        return "tom"
    return "crash"


def _apply_envelope(note: Note, spec: ChannelSpec) -> None:
    """Triangle has no volume; everything else decays from its velocity level."""
    if spec.kind == "triangle":
        note.volume = 15          # the triangle is either on or off
        return
    if spec.kind == "dmc":
        note.volume = min(15, note.volume)


def _in_cluster(note: Note, clusters: List[_Cluster]) -> bool:
    for cluster in clusters:
        if note in cluster.notes:
            return True
    return False


def _expand_clusters(clusters: List[_Cluster], states: Dict[str, _ChannelState],
                     options: Options, stats: Stats) -> List[Note]:
    """Rewrite each cluster as a repeating run of its pitches."""
    frame = 1.0 / options.fps
    step = max(1, options.arp_frames) * frame
    out: List[Note] = []
    for cluster in clusters:
        pitches = []
        for note in cluster.notes:
            if note.pitch not in pitches:
                pitches.append(note.pitch)
        if len(pitches) < 2:
            # Not actually a chord: keep the strongest note.
            best = max(cluster.notes, key=lambda n: n.velocity)
            out.append(best)
            continue
        loudest = max(cluster.notes, key=lambda n: n.velocity)
        spec = states[cluster.channel].spec
        cursor = cluster.start
        index = 0
        while cursor < cluster.end - 1e-6:
            sub = Note(
                start=cursor,
                dur=min(step, cluster.end - cursor),
                pitch=pitches[index % len(pitches)],
                velocity=loudest.velocity,
                part=loudest.part,
                role=loudest.role,
                program=loudest.program,
                channel=cluster.channel,
                volume=max(5, _velocity_to_level(loudest.velocity,
                                                 "harmony" if loudest.role != "drum"
                                                 else "drum") - 1),
                duty=loudest.duty,
                shared=True,
            )
            _apply_envelope(sub, spec)
            out.append(sub)
            cursor += step
            index += 1
    return out


def _quantize(notes: List[Note], fps: float) -> List[Note]:
    frame = 1.0 / fps
    for note in notes:
        note.start = round(note.start / frame) * frame
        note.dur = max(frame, round(note.dur / frame) * frame)
    return notes
