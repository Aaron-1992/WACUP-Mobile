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

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import analyze, gm, waves
from .chips import DRUM_MAP, MELODIC_KINDS, ChannelSpec
from .model import Note, Song

# Preferred channel kinds per musical role, best first.
# Who gets a good channel first when the console is tight.
_ROLE_PRIORITY = {"drum": 5.0, "melody": 4.0, "bass": 3.5, "counter": 2.5,
                  "harmony": 1.5, "rhythm": 1.0}


def _priority(role: str) -> float:
    return _ROLE_PRIORITY.get(role, 1.0)


ROLE_PREFERENCE = {
    "melody": ["pulse", "huc", "saw", "fds", "wavetable", "psg", "triangle"],
    "counter": ["pulse", "huc", "saw", "wavetable", "fds", "psg", "triangle"],
    "harmony": ["pulse", "huc", "saw", "wavetable", "psg", "fds", "triangle"],
    "bass": ["triangle", "huc", "saw", "fds", "psg", "wavetable", "pulse"],
    "rhythm": ["pulse", "huc", "psg", "wavetable", "saw", "triangle", "fds"],
    # a drum needs a channel that can make noise: the delta channel, a noise
    # channel, or the PC Engine's channel 2, which is its noise channel
    "drum": ["dmc", "noise", "huc"],
}

# Instruments that are *timbre*, not just pitch: a flute, a string section, an
# organ and a brass stab are different waveforms, and only the PC Engine holds a
# waveform in RAM. When one of these lines plays and a PC Engine channel is free,
# the line belongs there — that is the difference between "the right notes on a
# square wave" and "a flute".
RICH_FAMILIES = {"piano", "chromatic", "organ", "guitar", "strings", "ensemble",
                 "brass", "reed", "pipe", "ethnic", "pad"}


def _wanted_kinds(note: Note, role: str, has_huc: bool) -> List[str]:
    """Which channel kinds suit this note, best first.

    With no PC Engine in the console this is the fixed table it always was, so a
    plain NES render is unchanged. With one, a line whose instrument has a real
    timbre (flute, strings, organ, brass…) is offered the wave-RAM channels
    first; a square-wave lead, a bass and the drums keep the order they had.
    """
    order = ROLE_PREFERENCE.get(role) or ROLE_PREFERENCE["harmony"]
    if not has_huc or "huc" not in order:
        return order
    if role == "bass":
        return order                       # the NES triangle is the better bass
    family = gm.family(note.program)
    if family in RICH_FAMILIES:
        return ["huc"] + [kind for kind in order if kind != "huc"]
    return order


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
    "huc": 0.5,
}


@dataclass
class Options:
    fps: float = 60.0988          # NTSC NES frame rate
    arp_frames: int = 2           # frames each pitch of a shared channel gets
    allow_sharing: bool = False
    transpose: int = 0
    max_notes_per_channel: int = 0    # 0 = unlimited
    quantize: bool = True
    min_duration: float = 0.03
    quietest: int = 7             # drop notes quieter than this velocity

    # A chip channel is monophonic: pretending otherwise is what makes converted
    # music sound like a wasp in a jar. Sharing is therefore strictly rationed.
    dedupe: bool = True
    # How many separate lines of each kind the arrangement is allowed to use.
    # 0 = decide from the number of channels (see _voice_budget). A console tune
    # is a handful of lines, not every part of an orchestral MIDI at once.
    voice_budget: Optional[Dict[str, int]] = None               # drop notes that double another part exactly
    max_cluster_notes: int = 3        # never arpeggiate more than a triad
    min_cluster_seconds: float = 0.12  # short blips are not worth splitting
    share_budget: float = 0.10        # at most this share of the notes may share
    keep_second_voice: bool = True    # keep a real second note rather than arp


@dataclass
class Stats:
    direct: int = 0               # landed on a channel of the preferred kind
    overflow: int = 0             # landed on another kind because it was free
    shared: int = 0               # had to share a channel as an arpeggio
    dropped: int = 0              # too short / too quiet / unplaceable
    simplified: int = 0           # left out on purpose so the mix stays clean
    left_out: Dict[str, int] = field(default_factory=dict)
    voices_thinned: int = 0       # extra lines dropped so the mix stays readable
    thinned: Dict[str, int] = field(default_factory=dict)
    deduped: int = 0              # doubled another part note for note
    channels_used: Dict[str, int] = field(default_factory=dict)
    per_channel_notes: Dict[str, int] = field(default_factory=dict)
    waves: Dict[str, int] = field(default_factory=dict)    # PC Engine wave RAM
    folded: int = 0               # octave-folded to fit the channel's range
    clusters: int = 0

    def as_lines(self) -> List[str]:
        lines = [
            "  notes placed directly on a suited channel : %d" % self.direct,
            "  notes re-homed onto a free spare channel   : %d" % self.overflow,
            "  left out (no free channel)                 : %d" % self.simplified,
        ]
        if self.left_out:
            for role in ("harmony", "drum", "counter", "bass", "melody"):
                if self.left_out.get(role):
                    lines.append("    of which %-31s: %d" % (role, self.left_out[role]))
        lines += [
            "  extra lines thinned out (too many at once): %d" % self.voices_thinned,
        ]
        if self.thinned:
            for role in ("harmony", "drum", "counter", "rhythm", "bass", "melody"):
                if self.thinned.get(role):
                    lines.append("    dropped %-27s: %d notes"
                                 % (role, self.thinned[role]))
        lines += [
            "  octave-folded into the chip's range        : %d" % self.folded,
            "  doubled notes folded into one              : %d" % self.deduped,
            "  notes dropped (too short/quiet)            : %d" % self.dropped,
            "  channel-sharing clusters                   : %d" % self.clusters,
            "  voices used                                : %d" % len(self.per_channel_notes),
        ]
        for channel in sorted(self.per_channel_notes):
            lines.append("    %-14s %5d notes" % (channel, self.per_channel_notes[channel]))
        if self.waves:
            shown = sorted(self.waves.items(), key=lambda item: -item[1])
            lines.append("  PC Engine wave RAM                       : %s" % ", ".join(
                "%s x%d" % (waves.describe(name), count)
                for name, count in shown[:6]))
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


def classify(song: Song, analysis=None) -> Dict[int, str]:
    """Ask the analyser what every line is doing, then stamp roles onto notes.

    This replaces the old "guess from the median pitch" rule: the analyser splits
    polyphonic tracks into monophonic voices first, so a chord and a tune are no
    longer the same thing.
    """
    analysis = analysis or analyze.analyse(song)
    roles: Dict[int, str] = {}
    for voice in analysis.voices:
        roles.setdefault(voice.part, voice.role)
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
    """Pulse width from the instrument *and* the register.

    The duty cycle is the only tone control a pulse channel has, and every composer
    of the era used it as one: a narrow pulse for a thin lead an octave up, a wide
    one for body down low. Ignoring the register is what makes transcriptions sound
    shrill on top and hollow underneath.
    """
    _kind, duty = gm.timbre(note.program)
    if note.role == "bass":
        duty = 0.5
    elif note.role == "harmony" and note.program in (0, 48, 49, 88, 89, 90, 91):
        duty = 0.125          # pads and string beds sit better thin
    elif note.role == "melody":
        duty = duty if duty in (0.125, 0.25, 0.5) else 0.5
    if duty not in (0.125, 0.25, 0.5):
        duty = 0.5
    # register: a 50 % pulse three octaves up is a siren, not a flute
    if note.pitch >= 91 and duty > 0.125:
        duty = 0.125
    elif note.pitch >= 84 and duty > 0.25:
        duty = 0.25
    if note.pitch <= 40 and duty < 0.5:
        duty = 0.5
    return duty


# What each kind of voice can actually play, in MIDI note numbers. A chip has no
# idea what "C1" means: it has a timer, and above the top of its range it either
# aliases into a whistle or the renderer has to drop the note. Real chip composers
# move a part an octave rather than lose it, so that is what happens here.
_PLAYABLE = {
    "pulse": (33, 96),        # A1 .. C7: above that a pulse is a dog whistle
    "triangle": (24, 96),
    "saw": (28, 100),
    "fds": (24, 100),
    "wavetable": (28, 96),
    "psg": (28, 96),
    "huc": (24, 100),         # the PC Engine goes an octave lower than the APU
    "dmc": (24, 96),
}
_CENTRE = 60


def _fit_pitch(pitch: int, kind: str) -> tuple:
    """Move a pitch by whole octaves until the channel can play it.

    Returns (pitch, moved). Whole octaves only: the tune keeps its intervals and
    its key, it just sits where the hardware lives.
    """
    low, high = _PLAYABLE.get(kind, (24, 100))
    if low <= pitch <= high:
        return pitch, False
    candidate = pitch
    # climb or fall by octaves towards the middle of the range, then stop; a note
    # that is still out of reach even at the edge is left where it is
    while candidate > high and candidate - 12 >= low:
        candidate -= 12
    while candidate < low and candidate + 12 <= high:
        candidate += 12
    if candidate > high:
        candidate = high
    if candidate < low:
        candidate = low
    return candidate, candidate != pitch


def _pan_for(note: Note, spec: ChannelSpec) -> float:
    """Where a voice sits in the stereo field, on a chip that can pan.

    A PC Engine composer spreads the inner parts either side of the lead and keeps
    the tune and the bass down the middle, so that is what happens here: only the
    harmony, counter and rhythm lines move, and only by a step or two of the
    chip's 4-bit pan register. A mono render ignores it entirely.
    """
    if not spec.pannable or note.role in ("melody", "bass", "drum"):
        return 0.0
    reach = {"harmony": 0.42, "counter": 0.28, "rhythm": 0.22}.get(note.role, 0.0)
    if not reach:
        return 0.0
    side = 1.0 if (sum(ord(character) for character in spec.id) & 1) else -1.0
    # quantise to the hardware's 16 pan steps, so it is a register value and not
    # a floating-point idea of one
    return round(side * reach * 7.0) / 7.0


def _voice_budget(channel_count: int) -> Optional[Dict[str, int]]:
    """How many separate lines of each kind an arrangement may use.

    A bare NES has four voices and the channel contention already picks the best
    line for every note, so nothing is thrown away there. Once extension chips are
    switched on there are up to 22 voices, and a full-band MIDI export will happily
    occupy every one of them at once: five guitar parts and eleven harmony lines is
    not an arrangement, it is mud. In that case keep the strongest few lines of
    each kind — which is what the composer of a chip tune would have done anyway.
    """
    if channel_count < 8:
        return None
    return {
        "melody": 1,                       # one lead, always
        "bass": 2,
        "drum": 2,
        "counter": max(2, channel_count // 5),
        "rhythm": 1,
        "harmony": max(3, channel_count // 4),
    }


def _thin_voices(notes: List[Note], budget: Dict[str, int],
                 stats: Stats) -> List[Note]:
    """Keep the strongest few lines of each kind, drop the rest.

    A MIDI export of a full band has five guitar parts and eleven harmony lines;
    a console has four to twenty-two voices and a listener with two ears. Rank the
    lines by how much music they actually play and how loud they are, keep the
    best ones, and say in the stats what went — this is the "choose wisely" half
    of not cramming everything into the channels.
    """
    lines: Dict[tuple, List[Note]] = {}
    for note in notes:
        lines.setdefault((note.role, note.voice, note.part), []).append(note)

    by_role: Dict[str, List[tuple]] = {}
    for key, line_notes in lines.items():
        sounding = sum(n.dur for n in line_notes)
        mean_velocity = sum(n.velocity for n in line_notes) / len(line_notes)
        by_role.setdefault(key[0], []).append(
            ((mean_velocity, sounding), key, line_notes))

    keep: List[Note] = []
    for role, entries in by_role.items():
        allowance = budget.get(role, 1)
        entries.sort(key=lambda item: item[0], reverse=True)
        for index, (score, key, line_notes) in enumerate(entries):
            if index < allowance:
                keep.extend(line_notes)
                continue
            stats.voices_thinned += 1
            stats.thinned[role] = stats.thinned.get(role, 0) + len(line_notes)
    return keep


# Below this a note is shorter than the attack the renderer gives it, so it can
# only ever be a click: that is a parsing artefact, not music.
_UNPLAYABLE = 0.006


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


def arrange(song: Song, channels: List[ChannelSpec], options: Options,
            analysis=None):
    """Place every note on a channel; returns (notes, stats)."""
    classify(song, analysis)
    stats = Stats()

    by_kind: Dict[str, List[_ChannelState]] = {}
    states: Dict[str, _ChannelState] = {}
    for spec in channels:
        state = _ChannelState(spec)
        states[spec.id] = state
        by_kind.setdefault(spec.kind, []).append(state)

    for kind in by_kind:
        by_kind[kind].sort(key=lambda s: s.spec.priority)

    has_huc = any(spec.kind == "huc" for spec in channels)
    clusters: List[_Cluster] = []
    placed: List[Note] = []
    voice_channel: Dict[tuple, str] = {}     # (part, voice) -> channel it lives on
    claims: Dict[str, tuple] = {}            # channel -> the line that owns it

    # Work on copies: one song object can be arranged several ways in a session
    # (bare NES, then every extension), and the caller's notes must stay untouched.
    source_notes = [note.copy() for note in song.notes]
    _articulate(source_notes)
    if options.dedupe:
        source_notes = _dedupe(source_notes, stats)
    budget = options.voice_budget
    if budget is None:
        budget = _voice_budget(len(channels))
    if budget:
        source_notes = _thin_voices(source_notes, budget, stats)
    share_budget = int(len(source_notes) * max(0.0, options.share_budget))

    # Three passes, most important music first. A harmony note can only take what
    # is still free after the melody, the bass and the drums have been placed, so
    # the song never loses its tune to a chord.
    ordered: List[Note] = []
    for roles, key in (
            (("drum", "melody", "bass"), lambda n: (n.start, -n.velocity, n.pitch)),
            (("counter", "rhythm"), lambda n: (n.start, -n.velocity, n.pitch)),
            (("harmony", "melodic"), lambda n: (n.start, n.pitch, -n.velocity))):
        group = [n for n in source_notes if n.role in roles]
        ordered.extend(sorted(group, key=key))
    seen = set(id(n) for n in ordered)
    ordered.extend(sorted([n for n in source_notes if id(n) not in seen],
                          key=lambda n: (n.start, n.pitch)))

    for note in ordered:
        if note.velocity < options.quietest or note.dur < _UNPLAYABLE:
            stats.dropped += 1
            continue
        if note.dur < options.min_duration:
            # A note this short is still music, not noise: give it the shortest
            # length the console can actually articulate instead of throwing it
            # away. Dropping 33 ms melody notes is how a fast tune loses its tune.
            if note.role == "drum":
                note.dur = max(note.dur, 1.0 / max(1.0, options.fps))
            else:
                note.dur = options.min_duration
        if options.transpose:
            note.pitch = max(0, min(127, note.pitch + options.transpose))

        for state in states.values():
            state.prune(note.start)

        role = note.role if note.role in ROLE_PREFERENCE else "harmony"
        wanted_kinds = _wanted_kinds(note, role, has_huc)

        drum = note.role == "drum"
        if drum:
            kind, sample = gm.percussion(note.pitch)
            note.drum = sample if sample else _drum_kind(note.pitch)
            period, short = DRUM_MAP.get(note.pitch, (9, False))
            note.noise_period = period
            note.noise_short = short

        # 1) the channel this line already lives on, if it is still free.
        #    A console arrangement gives each musical line its own channel; that
        #    is what makes a chord sound like a chord instead of a fast run of
        #    single notes on whichever channel happens to be idle.
        key = (note.part, note.voice)
        chosen = None
        home = voice_channel.get(key)
        if home is not None:
            state = states.get(home)
            if state is not None and state.free_at(note.start, note.end()):
                chosen = state
                stats.direct += 1

        # 2) otherwise give the line a channel of its own. A channel no other
        #    line has claimed wins, so the parts spread out over every chip that
        #    is switched on instead of piling onto the first pulse wave.
        if chosen is None:
            candidates = []
            for rank, kind in enumerate(wanted_kinds):
                for state in by_kind.get(kind, []):
                    if drum and kind == "huc" and not state.spec.noise_capable:
                        continue        # five of the six are tone-only
                    if not state.free_at(note.start, note.end()):
                        continue
                    owner = claims.get(state.spec.id)
                    score = (0 if owner is None or owner == key else 1,
                             rank, state.spec.priority)
                    candidates.append((score, state))
            if candidates:
                candidates.sort(key=lambda item: item[0])
                chosen = candidates[0][1]
                stats.direct += 1

        # 3) any free melodic channel, whatever chip it belongs to
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

        # 2b) drums get first call: a snare may cut a hi-hat short, because a
        #     missing backbeat is far more noticeable than a clipped hat.
        if chosen is None and drum:
            chosen = _steal_for_drum(note, by_kind)

        # 3) nothing free: share a channel only when the result will actually
        #    sound like a chord and the console is not already chattering on it.
        if chosen is None and options.allow_sharing and \
                stats.shared < share_budget:
            cluster = _try_share(note, by_kind, wanted_kinds, options,
                                 clusters)
            if cluster is not None:
                stats.shared += 1
                continue

        if chosen is None:
            # Leaving a note out is usually better than mangling the part. A
            # percussion hit that lost its channel to a kick or a snare counts as
            # deliberate thinning, not as a failure.
            if note.role in ("harmony", "drum", "counter", "rhythm"):
                stats.simplified += 1
                stats.left_out[note.role] = stats.left_out.get(note.role, 0) + 1
            else:
                stats.dropped += 1
            continue

        if not drum:
            if key not in voice_channel:
                if claims.get(chosen.spec.id) in (None, key):
                    voice_channel[key] = chosen.spec.id
                    claims[chosen.spec.id] = key
            elif claims.get(chosen.spec.id) == key:
                voice_channel[key] = chosen.spec.id

        note.channel = chosen.spec.id
        if not drum:
            folded, moved = _fit_pitch(note.pitch, chosen.spec.kind)
            if moved:
                note.pitch = folded
                stats.folded += 1
        note.volume = _velocity_to_level(note.velocity, note.role)
        if note.expression < 0.999:
            # CC7/CC11 in the file: quiet passages stay quiet
            note.volume = max(1, min(15, int(round(note.volume * (0.45 + 0.55 * note.expression)))))
        note.duty = _duty_for(note)
        if chosen.spec.kind == "huc":
            note.wave = waves.for_instrument(note.program, note.role, note.pitch)
        note.pan = _pan_for(note, chosen.spec)
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
    stats.waves = {}
    for note in notes_out:
        stats.per_channel_notes[note.channel] = \
            stats.per_channel_notes.get(note.channel, 0) + 1
        if note.channel.startswith("pce") and note.role != "drum":
            stats.waves[note.wave] = stats.waves.get(note.wave, 0) + 1
    return notes_out, stats


# Songs where every part plays the same pitch in unison are common (a doubled
# lead, or a MIDI export of a stereo patch). A console cannot chorus, and the
# duplicate only makes the mix louder and muddier, so one copy goes.
_ROLE_RANK = {"melody": 3, "bass": 3, "drum": 3, "harmony": 1}


def _rank(note: Note) -> int:
    return _ROLE_RANK.get(note.role, 1)


def _articulate(notes: List[Note]) -> None:
    """Shape note lengths from how the lines actually play.

    A legato line (notes touching each other) must not be re-attacked on every
    note, or the tune stutters; a staccato line should stay detached. This is the
    difference between "the MIDI was read" and "the MIDI was understood".
    """
    by_voice: Dict[int, List[Note]] = {}
    for note in notes:
        by_voice.setdefault((note.voice, note.part), []).append(note)

    for _key, line in by_voice.items():
        line.sort(key=lambda n: n.start)
        if len(line) < 3:
            continue
        gaps = []
        for previous, current in zip(line, line[1:]):
            if current.start >= previous.start:
                gaps.append(current.start - previous.end())
        if not gaps:
            continue
        mean_gap = sum(gaps) / len(gaps)
        legato = sum(1 for gap in gaps if gap < 0.02) / len(gaps)
        for index, note in enumerate(line):
            if index + 1 >= len(line):
                break
            following = line[index + 1]
            gap = following.start - note.end()
            if note.pitch == following.pitch:
                # a repeated note has to be re-attacked: that is a rhythm
                note.dur = min(note.dur, max(0.05, following.start - note.start - 0.01))
            elif legato > 0.5 and gap < 0.06:
                # hold through the join, so the chip does not click back in —
                # but stop a hair before the next note, otherwise the line
                # overlaps itself and can never stay on one channel
                note.dur = max(note.dur, max(0.01, following.start - note.start - 0.002))
            elif mean_gap > 0.12 and note.dur > 0.08:
                # detached playing: keep the gap, it is part of the phrasing.
                # Short notes are already detached — shaving them further would
                # push them under the "too short to bother" floor and delete the
                # tune (a fast 16th is only 33 ms).
                note.dur = note.dur * 0.85


def _dedupe(notes: List[Note], stats: Stats) -> List[Note]:
    """Fold unison doublings, keeping the line that matters.

    Two parts on the same pitch at the same moment sound as one voice on a chip,
    so one copy goes — and it is never the melody or the bass that goes, no matter
    which one started a millisecond earlier.

    The test is a real overlap, not "these two are close": at 226 BPM a hi-hat
    every 33 ms would otherwise fold into the next one and half the groove would
    silently disappear.
    """
    buckets: Dict[tuple, List[Note]] = {}
    for note in notes:
        key = (note.pitch, int(round(note.start / 0.01)))
        buckets.setdefault(key, []).append(note)

    kept: List[Note] = []
    for group in buckets.values():
        group.sort(key=lambda n: (-_rank(n), -n.velocity))
        winners: List[Note] = []
        for note in group:
            host = None
            for candidate in winners:
                overlap = min(note.end(), candidate.end()) - \
                    max(note.start, candidate.start)
                if overlap > 0.002 and abs(note.start - candidate.start) < 0.03:
                    host = candidate
                    break
            if host is None:
                winners.append(note)
                continue
            stats.deduped += 1
            host.velocity = max(host.velocity, note.velocity)
        kept.extend(winners)
    return kept


_DRUM_RANK = {"kick": 5, "clap": 4, "snare": 4, "tom": 3, "crash": 2, "hat": 1}


def _steal_for_drum(note: Note, by_kind):
    """Take a percussion channel from a less important hit.

    On real NES soundtracks the drummer does exactly this: the kick and the snare
    land, and the hi-hats get out of the way.
    """
    rank = _DRUM_RANK.get(note.drum, 3)
    best = None
    for kind in ("noise", "dmc"):
        for state in by_kind.get(kind, []):
            active = [entry for entry in state.active
                      if entry["cluster"] is None and entry["note"].end() > note.start]
            if not active:
                continue
            weakest = min(active, key=lambda entry: _DRUM_RANK.get(entry["note"].drum, 3))
            weakest_rank = _DRUM_RANK.get(weakest["note"].drum, 3)
            if weakest_rank >= rank:
                continue
            score = (weakest_rank, len(active))
            if best is None or score < best[0]:
                best = (score, state, active)
    if best is None and rank >= 4:
        # The PC Engine's channel 2 can be switched to noise. A kick or a snare
        # may take it from a chord line — never from the tune or the bass — and
        # only when no drum channel is free at all.
        options = []
        for state in by_kind.get("huc", []):
            if not state.spec.noise_capable:
                continue
            active = [entry for entry in state.active
                      if entry["cluster"] is None
                      and entry["note"].end() > note.start
                      and entry["note"].role in ("harmony", "counter", "rhythm")]
            if active:
                options.append((len(active), state, active))
        if options:
            options.sort(key=lambda item: item[0])
            best = (options[0][0], options[0][1], options[0][2])
    if best is None:
        return None
    _, state, active = best
    for entry in active:
        other = entry["note"]
        if other.end() > note.start:
            other.dur = max(0.02, note.start - other.start)
    state.prune(note.start)
    return state


def _try_share(note: Note, by_kind, wanted_kinds, options: Options,
               clusters):
    """Fold a note into a channel that is already playing, as an arpeggio.

    Returns the cluster when it is worth doing, or None when it is not. The rules
    are the ones that separate "sounds like a chord" from "sounds broken":

    * only two or three different pitches may share a channel;
    * every note involved has to last long enough for a full cycle;
    * the notes must overlap for a real stretch of time, not for one frame;
    * the tune must not be all sharing.
    """
    step = max(1, options.arp_frames) / options.fps
    best = None
    for kind in wanted_kinds + sorted(MELODIC_KINDS):
        for state in by_kind.get(kind, []):
            conflicts = state.conflicts(note.start, note.end())
            if not conflicts:
                continue
            if best is None or len(conflicts) < len(best[1]):
                best = (state, conflicts)
    if best is None:
        return None

    state, conflicts = best
    existing = next((entry for entry in conflicts if entry["cluster"]), None)
    cluster = existing["cluster"] if existing is not None else None

    pitches = {n.pitch for n in (cluster.notes if cluster else [])}
    pitches.add(note.pitch)
    for entry in conflicts:
        if cluster is None or entry["note"] not in cluster.notes:
            pitches.add(entry["note"].pitch)
    if len(pitches) < 2 or len(pitches) > options.max_cluster_notes:
        return None            # nothing gained, or a chord that would smear

    span_start = min([note.start] + [c["note"].start for c in conflicts])
    span_end = max([note.end()] + [c["note"].end() for c in conflicts])
    if span_end - span_start < options.min_cluster_seconds:
        return None
    if span_end - span_start < 3 * step:
        return None

    if cluster is None:
        victim = conflicts[0]["note"]
        cluster = _Cluster(state.spec.id, victim.start, victim.end())
        cluster.add(victim)
        for entry in conflicts:
            if entry["note"] is victim:
                entry["cluster"] = cluster
        clusters.append(cluster)

    cluster.add(note)
    state.active.append({"note": note, "cluster": cluster})
    return cluster


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
            # Not actually a chord: keep the strongest note on the channel.
            best = max(cluster.notes, key=lambda n: n.velocity)
            if not best.channel:
                best.channel = cluster.channel
                best.volume = _velocity_to_level(best.velocity, best.role)
                best.duty = _duty_for(best)
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
