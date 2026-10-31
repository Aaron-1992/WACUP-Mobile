"""Command line front end: MIDI/game file in, 8-bit audio out.

    chip8bit song.mid
    chip8bit song.vgm --extensions vrc6,mmc5,fds
    chip8bit *.mid --extensions all -o out_folder
    chip8bit --list-extensions

Nothing outside the Python standard library is used, so the Windows build is a
single .exe with no install step.
"""

import argparse
import glob
import math
import os
import sys
import time
from typing import Dict

from . import analyze, chips, convert, importers, mix, sampled
from .arrange import Options, arrange
from .render import RenderOptions, render, write_stems, write_wav
from .vgmout import write_vgm

VERSION = "1.0"


def _extension_help() -> str:
    formats = ["  %s : %s" % (name, label) for name, label in importers.available()]
    lines = ["Input formats:", *formats, "  zip : first MIDI/VGM/GYM inside", "",
             "The NES APU is on by default; --no-nes leaves it out, so one of the",
             "whole consoles below becomes the machine:",
             "  nes    +4 channels : pulse1, pulse2, triangle, noise (2A03)",
             "  dual   +4 channels : a second NES APU, wired in parallel",
             "  pce    +6 channels : PC Engine / HuC6280 — wave RAM, 5-bit volume,",
             "                       stereo pan; channels 5 and 6 can go to noise",
             "",
             "Cartridge chips (they need a console under them):"]
    for name in chips.ordered_extensions():
        if name in chips.CONSOLES:
            continue
        specs = chips.EXTENSION_CHANNELS[name]
        kinds = ", ".join("%s (%s)" % (spec.id, spec.kind) for spec in specs)
        lines.append("  %-6s +%d channel%s : %s" %
                     (name, len(specs), "" if len(specs) == 1 else "s", kinds))
    lines += ["", "e.g.  --extensions pce --no-nes      a PC Engine on its own",
              "      --extensions dual,pce          a second NES and a PC Engine",
              "      --extensions all              everything, 32 voices"]
    return "\n".join(lines)


def _parse_extensions(value):
    if not value:
        return []
    names = [part.strip().lower() for part in value.replace("+", ",").split(",") if part.strip()]
    if "all" in names or "every" in names:
        return chips.ordered_extensions()
    chosen = []
    for name in names:
        if name in ("nes", "none", "base"):
            continue
        if name not in chips.EXTENSION_CHANNELS:
            raise SystemExit("unknown extension '%s'\n\n%s" % (name, _extension_help()))
        if name not in chosen:
            chosen.append(name)
    return chosen


def _tag(extensions, base: bool = True) -> str:
    """What the file name says: the console(s) and chips, in a stable order."""
    names = (["nes"] if base else []) + \
            [name for name in chips.ordered_extensions() if name in extensions]
    return "+".join(names) or "silent"


def _output_path(source: str, out_argument: str, extensions, suffix: str,
                 multiple: bool, label: str = "", base: bool = True,
                 tag: str = "") -> str:
    stem = os.path.splitext(os.path.basename(source))[0]
    if label:
        stem = "%s %s" % (stem, convert._plain_name(label))
    named = "%s [%s]%s" % (stem, tag or _tag(extensions, base), suffix)

    if not out_argument:
        return os.path.join(os.path.dirname(source), named)

    if os.path.isdir(out_argument) or out_argument.endswith(("/", "\\")):
        os.makedirs(out_argument, exist_ok=True)
        return os.path.join(out_argument, named)

    # A path with no file extension is a folder we make for the user.
    if not os.path.splitext(out_argument)[1]:
        os.makedirs(out_argument, exist_ok=True)
        return os.path.join(out_argument, named)

    if multiple:                      # several inputs cannot share one file name
        folder = os.path.dirname(out_argument) or "."
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, named)

    folder = os.path.dirname(out_argument)
    if folder:
        os.makedirs(folder, exist_ok=True)
    return out_argument


class _SourceChoice:
    """The couple of things a DS ROM needs to know: which song, which bank."""

    def __init__(self, sequence: str = "", bank: str = ""):
        self.sequence = sequence or ""
        self.bank = bank or ""


def _song_list(importer, item: str):
    """The songs of a DS file; anything else is simply not a song container."""
    module = importers.module_of(importer)
    lister = getattr(module, "songs", None) if module else None
    if lister is None:
        raise ValueError("only DS ROMs hold several songs")
    return lister(item)


def _list_songs(inputs) -> int:
    """Print the songs a DS ROM holds, with the bank each one uses.

    A bare list of names is not much help when the names are the game's own
    internal ones: "BGM_ATHLETIC" and "BGM_AMB_WATER" look equally promising
    until you know that one is a four-minute tune and the other is an ambience
    loop with no notes in it at all. So each song also gets its length, its note
    count, and a word for what it is — a tune, a jingle, or nothing to convert.
    """
    found = False
    for item in inputs:
        try:
            importer = importers.find_for(item)
            module = importers.module_of(importer)
            songs = _song_list(importer, item)
            lengths = {}
            read_lengths = getattr(module, "song_lengths", None) if module else None
            if read_lengths is not None:
                try:
                    lengths = read_lengths(item)
                except Exception:
                    lengths = {}
        except Exception as error:
            print("%s: %s" % (item, error))
            continue
        found = True
        print("%s - %d song%s" % (os.path.basename(item), len(songs),
                                  "" if len(songs) == 1 else "s"))
        for index, bank, name in songs:
            seconds, notes, why = lengths.get(index, (None, 0, ""))
            if seconds is None:
                detail = "   nothing to convert" if why else ""
            else:
                detail = "%6.1f s %5d notes%s" % (
                    seconds, notes, "  jingle" if seconds < 10.0 else "")
            print("  %3d  bank %2d  %-24s %s" % (index, bank, name, detail))
        print("  (pick one with --sequence NAME, or --sequence with the number "
              "above)")
        if lengths:
            jingles = sum(1 for index, _bank, _name in songs
                          if (lengths.get(index) or (None,))[0] is not None
                          and (lengths.get(index) or (99,))[0] < 10.0)
            empty = len(songs) - sum(1 for index, _b, _n in songs
                                     if (lengths.get(index) or (None,))[0] is not None)
            if jingles or empty:
                print("  (%d jingle%s under ten seconds, %d with no notes to "
                      "convert)" % (jingles, "" if jingles == 1 else "s", empty))
    if not found:
        print("no DS ROM, SDAT or SSEQ found")
        return 1
    return 0


def _short_reason(text: str) -> str:
    """A reader's complaint, cut down to something that fits in a column."""
    lowered = (text or "").strip()
    if "no notes" in lowered:
        return "an ambience loop or an empty slot"
    if "no tracks" in lowered:
        return "an ambience loop or an empty slot"
    return lowered[:48] or "unreadable"


def _diagnosis(song, analysis, notes, stats, grouped, stems, duration):
    """What the converter did, and where a listener might stop hearing the tune.

    "It sounds weird" is not something a WAV can explain by itself, so this prints
    the things that actually decide whether a conversion is recognisable: which
    song was picked, how many notes of each role survived, whether the melody sits
    above the rest of the mix, and whether anything was moved by an octave or
    thrown away because the console ran out of voices.
    """
    lines = []
    title = getattr(song, "ds_song", "") or getattr(song, "title", "") \
        or os.path.basename(getattr(song, "source_path", "") or "this file")
    count = int(getattr(song, "ds_song_count", 0) or 0)
    index = int(getattr(song, "ds_song_index", 0) or 0)
    if count > 1:
        title = "%s  (song %d of %d)" % (title, index, count)
    lines.append("  song: %s" % title)
    lines.append("  %.1f s, %.0f BPM, %s, %d notes read, %d placed" % (
        duration, analysis.tempo or 120.0, analysis.meter or "meter unknown",
        len(song.notes), len(notes)))

    warnings = []
    roles: Dict[str, int] = {}
    for note in notes:
        roles[note.role] = roles.get(note.role, 0) + 1
    if "melody" not in roles:
        warnings.append("no note was identified as the melody — the tune has "
                        "nothing to lead with")
    if stats.simplified:
        lost = ", ".join("%s %d" % (role, count)
                         for role, count in sorted(stats.left_out.items(),
                                                   key=lambda item: -item[1]))
        warnings.append("%d note(s) were left out because every voice was busy (%s)"
                        % (stats.simplified, lost or "no role recorded"))
    if stats.left_out.get("melody"):
        warnings.append("%d melody note(s) were left out — the tune itself lost "
                        "notes" % stats.left_out["melody"])
    if stats.folded:
        warnings.append("%d note(s) were moved by whole octaves to fit the chip "
                        "(the tune keeps its shape, but it sits elsewhere)"
                        % stats.folded)
    if stats.dropped:
        warnings.append("%d note(s) were too short or too quiet to place"
                        % stats.dropped)
    if duration < 3.0:
        warnings.append("this is only %.1f s long — it may be a jingle or a sound "
                        "effect rather than a song" % duration)

    levels = {}
    if stems:
        gains = mix.balance(stems, mix.channel_roles(grouped))
        levels = mix.role_levels(stems, mix.channel_roles(grouped), gains)
        melody = levels.get("melody")
        if melody is not None:
            rest = [value for role, value in levels.items() if role != "melody"]
            if rest:
                # add the other roles up the way an ear does: energy, not dB
                total = sum(10 ** (value / 10.0) for value in rest)
                together = 10 * math.log10(total) if total > 0 else -120.0
                gap = melody - together
                if gap < -6.0:
                    warnings.append("the melody sits %.0f dB under the rest of the "
                                    "mix — the tune will be hard to follow" % -gap)
                elif gap < -2.0:
                    warnings.append("the melody sits %.0f dB under the rest of the "
                                    "mix" % -gap)
                lines.append("  melody %.1f dB against the rest %.1f dB "
                             "(%.1f dB apart)" % (melody, together, gap))
    if levels:
        shown = sorted(levels.items(), key=lambda item: -item[1])
        lines.append("  voice levels: " + ", ".join(
            "%s %.1f dB" % (role, value) for role, value in shown))
    if roles:
        lines.append("  roles placed: " + ", ".join(
            "%s %d" % (role, count) for role, count in sorted(roles.items())))
    for warning in warnings:
        lines.append("  ! " + warning)
    if not warnings:
        lines.append("  nothing looks wrong: the melody leads, every note found a "
                     "voice")
    return lines


def _convert_samples(source: str, song, analysis, args, multiple: bool) -> int:
    """Render the song on the archive's own instruments, straight to a WAV."""
    carrying = importers.bank_of(source)
    if carrying is None:
        print("  x the game's own samples only exist in a Nintendo DS file "
              "(.nds / .sdat); drop --samples to convert to a chip")
        return 1
    archive, bank_index = carrying
    options = sampled.SampleOptions(
        rate=min(sampled.NATIVE_RATE, max(8000, int(args.rate))),
        gain=args.gain,
        stereo=bool(args.stereo),
        echo=bool(args.echo),
        limit=not args.no_limit,
        compress=not args.no_compress,
        max_seconds=args.max_seconds,
    )
    started = time.time()
    rendered = sampled.render_song(song, archive, bank_index, options)
    if not rendered.notes_played:
        print("  x none of this song's instruments could be found in the bank")
        return 1

    label = getattr(song, "ds_song", "") if getattr(
        song, "ds_song_count", 0) > 1 else ""
    target = _output_path(source, args.output, (), ".wav", multiple, label,
                          base=False, tag="ds")
    wav_options = RenderOptions(rate=rendered.rate,
                                bits=16 if args.bits == 16 else 8,
                                stereo=bool(args.stereo), gain=1.0,
                                equalise=False, echo=False, limit=False,
                                compress=False)
    write_wav(target, rendered.pcm, wav_options)
    elapsed = time.time() - started
    print("  > %s" % target)
    if getattr(args, "diagnose", False):
        print("  song: %s" % (getattr(song, "ds_song", "") or song.title
                              or os.path.basename(source)))
        print("  %.1f s, %.0f BPM, %d note%s played on the game's own instruments"
              % (rendered.seconds, analysis.tempo or 120.0,
                 rendered.notes_played, "" if rendered.notes_played == 1 else "s"))
        print("  %d instrument(s), %d drum kit(s) in this bank; %d track(s)"
              % (rendered.instruments, rendered.drums, rendered.voices))
        if rendered.synthetic:
            print("  ! %d note(s) are the bank's square-wave instruments, which "
                  "have no sample to play" % rendered.synthetic)
        if rendered.notes_skipped:
            print("  ! %d note(s) had no instrument in the bank"
                  % rendered.notes_skipped)
        print("  this is the soundtrack, not a conversion: no chip is involved")
    if args.stats or args.verbose:
        for line in analysis.summary_lines():
            print("    " + line)
        print("  rendered %.1fs of audio in %.2fs (%dx realtime)"
              % (rendered.seconds, elapsed, rendered.seconds / max(0.001, elapsed)))
    return 0


def _convert(source: str, args, extensions, channels, multiple: bool = False,
             sequence: str = "", bank: str = "", base: bool = True) -> int:
    started = time.time()
    choice = _SourceChoice(sequence or getattr(args, "sequence", ""),
                           bank or getattr(args, "bank", ""))
    song = importers.read_source(source, choice)

    for warning in song.warnings:
        print("  ! %s" % warning)

    if not song.notes:
        print("  x nothing to convert in %s" % os.path.basename(source))
        return 1

    if args.transpose:
        for note in song.notes:
            note.pitch = max(0, min(127, note.pitch + args.transpose))

    analysis = analyze.analyse(song)

    if getattr(args, "samples", False):
        return _convert_samples(source, song, analysis, args, multiple)

    options = Options(
        allow_sharing=bool(args.sharing),
        dedupe=not args.no_dedupe,
        arp_frames=args.arp_frames,
        quantize=not args.no_quantize,
        min_duration=args.min_note,
        quietest=args.quietest,
    )
    notes, stats = arrange(song, channels, options, analysis=analysis)

    render_options = RenderOptions(
        rate=args.rate,
        bits=16 if args.bits == 16 else 8,
        stereo=args.stereo,
        gain=args.gain,
        nonlinear=not args.linear,
        max_seconds=args.max_seconds,
        equalise=not args.no_balance,
        echo=bool(args.echo),
        limit=not args.no_limit,
        compress=not args.no_compress,
    )

    grouped = {}
    for note in notes:
        grouped.setdefault(note.channel, []).append(note)

    diagnose = bool(getattr(args, "diagnose", False))
    if args.stems_dir or diagnose:
        pcm, stems, duration = render(notes, channels, render_options, grouped)
    else:
        pcm, stems, duration = render(notes, channels, render_options, grouped)
    if args.stems_dir:
        written = write_stems(args.stems_dir, stems, render_options)
        print("  + %d per-channel stems in %s" % (len(written), args.stems_dir))

    # a ROM holds many songs: the one that was converted belongs in the name
    song_label = getattr(song, "ds_song", "") if getattr(
        song, "ds_song_count", 0) > 1 else ""
    target = _output_path(source, args.output, extensions, ".wav", multiple,
                          song_label, base)
    write_wav(target, pcm, render_options)

    # A DS ROM gives up its own MIDI and SoundFont as well, so the same music can
    # be played (or edited) outside this tool. They sit next to the .wav.
    stem_of_source = os.path.splitext(os.path.basename(target))[0]
    if " [" in stem_of_source:                 # drop the chip tag from the name
        stem_of_source = stem_of_source.rsplit(" [", 1)[0]
    if not args.wav_only:                      # a soundtrack wants just the WAVs
        for extra in importers.extract_assets(
                source, os.path.dirname(target) or ".", stem_of_source):
            print("  + %s" % extra)

    if args.export_vgm:
        vgm_target = os.path.splitext(target)[0] + ".vgm"
        for message in write_vgm(vgm_target, notes, channels, duration, extensions,
                                 base):
            print("  ! %s" % message)
        print("  > %s" % vgm_target)

    elapsed = time.time() - started
    print("  > %s" % target)
    if diagnose:
        for line in _diagnosis(song, analysis, notes, stats, grouped, stems,
                               duration):
            print(line)
    if args.stats or args.verbose:
        print("  what the file contains:")
        for line in analysis.summary_lines():
            print("    " + line)
        on = (("nes" if base else "") + " " + " ".join(extensions)).split()
        print("  chips: %s" % (", ".join(on) or "nothing"))
        for line in stats.as_lines():
            print(line)
        print("  rendered %.1fs of audio in %.2fs (%dx realtime)"
              % (duration, elapsed, duration / max(0.001, elapsed)))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="chip8bit",
        description="Convert MIDI files or game music (VGM/VGZ/GYM) into 8-bit "
                    "NES audio, with optional extension chips.",
        epilog=_extension_help(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("inputs", nargs="*",
                        help="MIDI / VGM / VGZ / GYM / NDS files or folders")
    parser.add_argument("-o", "--output", help="output file or folder")
    parser.add_argument("-e", "--extensions", default="",
                        help="chips to enable, comma separated: dual (a second "
                             "NES APU), pce (PC Engine), vrc6, mmc5, fds, n163, "
                             "dmc, psg, or 'all'")
    parser.add_argument("--no-nes", action="store_true",
                        help="leave the first NES APU out: with --extensions pce "
                             "that is a PC Engine on its own (6 voices), with "
                             "--extensions dual a single second APU")
    parser.add_argument("--list-extensions", action="store_true",
                        help="show the chips and the channels they add, then exit")
    parser.add_argument("--samples", action="store_true",
                        help="do not convert at all: play the song on the game's "
                             "own instruments, out of its own bank (DS only), and "
                             "write that. The file name says [ds], not [nes]")
    parser.add_argument("--stats", action="store_true", help="report what went where")
    parser.add_argument("--diagnose", action="store_true",
                        help="say whether the tune is actually audible: which song "
                             "was picked, what was left out, and where the melody "
                             "sits against the rest of the mix")
    parser.add_argument("-v", "--verbose", action="store_true", help="same as --stats, plus source info")
    parser.add_argument("--export-vgm", action="store_true",
                        help="also write a .vgm log (plays in VGM-aware players)")
    parser.add_argument("--stems", dest="stems_dir", default="",
                        help="write one WAV per console channel into this folder")
    parser.add_argument("--rate", type=int, default=44100, help="sample rate (default 44100)")
    parser.add_argument("--bits", type=int, choices=(8, 16), default=16,
                        help="bit depth of the WAV (default 16; 8 for the crunch)")
    parser.add_argument("--stereo", action="store_true", help="duplicate to two channels")
    parser.add_argument("--gain", type=float, default=0.9, help="headroom, 0.1-1.0")
    parser.add_argument("--linear", action="store_true", help="skip the NES mixer curve")
    parser.add_argument("--no-balance", action="store_true",
                        help="do not level the voices against each other")
    parser.add_argument("--echo", action="store_true",
                        help="add a quiet tempo-aware echo (off by default)")
    parser.add_argument("--no-limit", action="store_true",
                        help="no peak limiting on the master")
    parser.add_argument("--no-compress", action="store_true",
                        help="no bus compression on the master")
    parser.add_argument("--no-sharing", action="store_true",
                        help="default: notes that find no free voice are left out")
    parser.add_argument("--sharing", action="store_true",
                        help="allow arpeggio channel sharing (off by default: it "
                             "sounds like a wasp in a jar)")
    parser.add_argument("--no-drums", action="store_true",
                        help="use the noise channel instead of sampled drum hits")
    parser.add_argument("--no-dedupe", action="store_true",
                        help="keep pairs of parts that double each other exactly")
    parser.add_argument("--no-quantize", action="store_true",
                        help="keep original timing instead of snapping to NES frames")
    parser.add_argument("--arp-frames", type=int, default=2,
                        help="video frames each arpeggio note lasts (default 2)")
    parser.add_argument("--min-note", type=float, default=0.03,
                        help="shortest note worth keeping, in seconds (default 0.03)")
    parser.add_argument("--quietest", type=int, default=6,
                        help="drop notes quieter than this MIDI velocity (default 6)")
    parser.add_argument("--transpose", type=int, default=0, help="semitones")
    parser.add_argument("--max-seconds", type=float, default=0.0,
                        help="stop after N seconds (0 = whole song)")
    parser.add_argument("--sequence", default="",
                        help="which song to take from a DS ROM (name or number)")
    parser.add_argument("--bank", default="",
                        help="which instrument bank of a DS ROM to use (default: "
                             "the one the song asks for)")
    parser.add_argument("--list-songs", action="store_true",
                        help="list the songs inside a DS ROM and stop")
    parser.add_argument("--wav-only", action="store_true",
                        help="do not write the .mid and .sf2 that a DS ROM can "
                             "also give up — the audio is all you get")
    parser.add_argument("--all-songs", action="store_true",
                        help="convert every song of a DS ROM, each into its own "
                             "files")
    parser.add_argument("--version", action="version", version="chip8bit %s" % VERSION)

    args = parser.parse_args(argv)

    if args.list_extensions:
        print(_extension_help())
        return 0

    if args.list_songs:
        return _list_songs(args.inputs)

    if not args.inputs:
        parser.print_help()
        print("\nDrag a .mid, .vgm, .vgz, .gym or .nds file onto chip8bit.exe with")
        print("--extensions all to convert it with every extension chip enabled.")
        _pause()
        return 0

    extensions = _parse_extensions(args.extensions)
    base = not args.no_nes
    if not chips.has_console(extensions, base):
        raise SystemExit(
            "there is no console to play on: --no-nes switches the NES off, so "
            "one of the whole consoles has to be on as well, e.g.\n"
            "  --no-nes --extensions pce      (a PC Engine on its own)\n"
            "  --no-nes --extensions dual     (one NES APU on its own)")
    channels = chips.build_channel_set(extensions, base=base)

    sources = []
    for item in args.inputs:
        if os.path.isdir(item):
            for pattern in ("*.mid", "*.midi", "*.vgm", "*.vgz", "*.gym",
                            "*.nds", "*.sdat", "*.sseq", "*.zip"):
                sources.extend(sorted(glob.glob(os.path.join(item, pattern))))
        else:
            sources.append(item)

    if not sources:
        print("no input files found")
        return 1

    print("chip8bit %s - %d voice%s%s"
          % (VERSION, len(channels), "" if len(channels) == 1 else "s",
             "" if not extensions else " (%s + %s)" % ("nes", "+".join(extensions))))

    if args.all_songs:
        sources = _every_song(sources)

    failures = 0
    for index, (source, sequence, bank, song_name) in enumerate(
            [(item, "", "", "") if isinstance(item, str) else item
             for item in sources], 1):
        title = os.path.basename(source)
        if song_name:
            title += " — " + song_name
        print("\n[%d/%d] %s" % (index, len(sources), title))
        try:
            failures += _convert(source, args, extensions, channels,
                                 len(sources) > 1, sequence, bank, base)
        except SystemExit:
            raise
        except Exception as error:            # keep batch conversion going
            print("  x %s: %s" % (type(error).__name__, error))
            failures += 1

    print("\ndone: %d ok, %d failed" % (len(sources) - failures, failures))
    _pause()
    return 0 if failures == 0 else 1


def _every_song(sources):
    """--all-songs: one entry per song of every DS file, files as they came.

    The song is asked for by its index, which the archive matches exactly, and
    its name is only used for the line that says what is being converted.
    """
    expanded = []
    for source in sources:
        try:
            songs = _song_list(importers.find_for(source), source)
        except Exception:
            expanded.append((source, "", "", ""))
            continue
        if len(songs) <= 1:
            expanded.append((source, "", "", ""))
            continue
        for index, _bank, name in songs:
            expanded.append((source, str(index), "", name))
    return expanded


def _pause() -> None:
    """Keep the window open when the exe was double-clicked or given a dropped file."""
    if getattr(sys, "frozen", False) and sys.stdin and sys.stdin.isatty():
        try:
            input("\nPress Enter to close this window...")
        except (EOFError, KeyboardInterrupt):
            pass


if __name__ == "__main__":
    sys.exit(main())
