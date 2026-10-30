"""The conversion pipeline itself, shared by the window and the command line.

Keeping it in one place means the GUI and the CLI can never drift apart, and the
self tests cover the same code the user actually runs.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import analyze, chips, importers
from .arrange import Options, Stats, arrange
from .render import RenderOptions, render, wav_bytes
from .vgmout import write_vgm


@dataclass
class Settings:
    """Everything the window lets you change, in one small object."""

    extensions: List[str] = field(default_factory=list)
    bits: int = 16
    rate: int = 44100
    arp_frames: int = 2
    sharing: bool = False          # arpeggio cramming is off: it sounds like mud
    dedupe: bool = True
    sampled_drums: bool = True
    stereo: bool = False
    export_vgm: bool = False
    gain: float = 0.9
    equalise: bool = True          # balance the voices against each other
    echo: bool = False             # the NES "second pulse" delay, opt-in
    limit: bool = True             # peak limiting instead of turning everything down
    compress: bool = True          # gentle master compression
    sequence: str = ""              # which song inside a bank archive (DS ROMs)
    bank: str = ""                  # which instrument bank to take with it

    def channels(self):
        return chips.build_channel_set(
            [name for name in self.extensions if name in chips.EXTENSION_CHANNELS])

    def tag(self) -> str:
        names = [name for name in self.extensions if name in chips.EXTENSION_CHANNELS]
        return "nes" if not names else "nes+" + "+".join(names)

    def arrange_options(self) -> Options:
        return Options(
            allow_sharing=self.sharing,
            dedupe=self.dedupe,
            arp_frames=max(1, int(self.arp_frames)),
        )

    def render_options(self) -> RenderOptions:
        return RenderOptions(
            rate=int(self.rate),
            bits=16 if int(self.bits) > 8 else 8,
            stereo=self.stereo,
            gain=float(self.gain),
            sampled_drums=self.sampled_drums,
            equalise=self.equalise,
            echo=self.echo,
            limit=self.limit,
            compress=self.compress,
        )


@dataclass
class Result:
    ok: bool = True
    error: str = ""
    wav_path: str = ""
    wav_bytes: bytes = b""
    vgm_path: str = ""
    name: str = ""
    seconds: float = 0.0
    voices: int = 0
    channels: Dict[str, int] = field(default_factory=dict)
    stats: Optional[Stats] = None
    analysis: Optional[object] = None
    analysis_lines: List[str] = field(default_factory=list)
    notes: List = field(default_factory=list)      # arranged notes, for the pattern view
    tempo: float = 120.0
    kept: int = 0
    left_out: int = 0              # no free channel: report, never cram in
    thinned: int = 0               # extra duplicate lines dropped on purpose
    dropped: int = 0               # too short / too quiet to keep
    warnings: List[str] = field(default_factory=list)
    source_format: str = ""
    source_notes: int = 0
    render_seconds: float = 0.0
    stems: Dict[str, list] = field(default_factory=dict)   # per-channel audio, for checks
    assets: List[str] = field(default_factory=list)        # MIDI/SoundFont written next to it


def output_name(source: str, settings: Settings) -> str:
    stem = os.path.splitext(os.path.basename(source))[0]
    return "%s [%s].wav" % (stem, settings.tag())


def convert_file(source: str, settings: Settings,
                 output_path: Optional[str] = None,
                 keep_in_memory: bool = False,
                 progress=None) -> Result:
    """Import, arrange, render, and write the result. Never raises for bad input.

    ``progress`` is called as progress(stage, fraction) so a window can show what
    is happening during a long song.
    """
    import time

    def report(stage: str, fraction: float) -> None:
        if progress is not None:
            try:
                progress(stage, fraction)
            except Exception:
                pass

    started = time.time()
    result = Result(name=os.path.basename(source))
    report("Reading", 0.05)

    target = output_path or os.path.join(os.path.dirname(os.path.abspath(source)),
                                         output_name(source, settings))
    directory = os.path.dirname(target)
    stem = os.path.splitext(os.path.basename(source))[0]

    try:
        song = importers.read_source(source, settings)
    except Exception as error:
        result.ok = False
        result.error = "%s: %s" % (type(error).__name__, error)
        return result

    result.warnings = list(song.warnings)

    # A source that carries its own instruments (a DS ROM) also hands over the
    # MIDI and SoundFont it was described by, so the same music can be played
    # anywhere. Nothing is bundled: these come from the file that was opened.
    try:
        result.assets = importers.extract_assets(source, directory, stem)
    except Exception as error:
        result.warnings.append("could not write the source MIDI/SoundFont: %s" % error)
    result.source_format = song.source_format
    result.source_notes = len(song.notes)
    if not song.notes:
        result.ok = False
        result.error = "; ".join(song.warnings) or "no notes found in this file"
        return result

    report("Reading the music", 0.15)
    analysis = analyze.analyse(song)
    result.analysis = analysis
    result.analysis_lines = analysis.summary_lines()

    report("Arranging for the chip", 0.3)
    channels = settings.channels()
    notes, stats = arrange(song, channels, settings.arrange_options(),
                           analysis=analysis)
    if not notes:
        result.ok = False
        result.error = "nothing survived arrangement (is the file empty?)"
        return result

    grouped: Dict[str, List] = {}
    for note in notes:
        grouped.setdefault(note.channel, []).append(note)

    report("Rendering %d notes" % len(notes), 0.45)
    render_options = settings.render_options()
    pcm, stems, duration = render(notes, channels, render_options, grouped)
    result.stems = stems
    report("Writing the WAV", 0.9)
    audio = wav_bytes(pcm, render_options)

    if directory:
        os.makedirs(directory, exist_ok=True)

    if keep_in_memory:
        result.wav_bytes = audio
    else:
        try:
            with open(target, "wb") as handle:
                handle.write(audio)
        except OSError as error:
            result.ok = False
            result.error = "could not write %s (%s)" % (target, error)
            return result
    result.wav_path = target

    if settings.export_vgm:
        vgm_target = os.path.splitext(target)[0] + ".vgm"
        try:
            messages = write_vgm(vgm_target, notes, channels, duration,
                                 settings.extensions)
            result.vgm_path = vgm_target
            result.warnings.extend(messages)
        except Exception as error:
            result.warnings.append("VGM export failed: %s" % error)

    result.notes = notes
    result.tempo = float(getattr(analysis, "tempo", 0.0) or 120.0)
    result.kept = len(notes)
    result.left_out = stats.simplified
    result.dropped = stats.dropped
    result.thinned = stats.voices_thinned
    result.seconds = duration
    result.voices = len(stats.per_channel_notes)
    result.channels = dict(sorted(stats.per_channel_notes.items()))
    result.stats = stats
    result.render_seconds = time.time() - started
    report("Done", 1.0)
    return result
