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
import os
import sys
import time

from . import analyze, chips, importers
from .arrange import Options, arrange
from .render import RenderOptions, render, write_stems, write_wav
from .vgmout import write_vgm

VERSION = "1.0"


def _extension_help() -> str:
    formats = ["  %s : %s" % (name, label) for name, label in importers.available()]
    lines = ["Input formats:", *formats, "  zip : first MIDI/VGM/GYM inside", "",
             "NES base console: pulse1, pulse2, triangle, noise", "", "Extension chips:"]
    for name, specs in chips.EXTENSION_CHANNELS.items():
        kinds = ", ".join("%s (%s)" % (s.id, s.kind) for s in specs)
        lines.append("  %-6s +%d channel%s : %s" %
                     (name, len(specs), "" if len(specs) == 1 else "s", kinds))
    return "\n".join(lines)


def _parse_extensions(value):
    if not value:
        return []
    names = [part.strip().lower() for part in value.replace("+", ",").split(",") if part.strip()]
    if "all" in names or "every" in names:
        return list(chips.EXTENSION_CHANNELS.keys())
    chosen = []
    for name in names:
        if name in ("nes", "none", "base"):
            continue
        if name not in chips.EXTENSION_CHANNELS:
            raise SystemExit("unknown extension '%s'\n\n%s" % (name, _extension_help()))
        if name not in chosen:
            chosen.append(name)
    return chosen


def _tag(extensions) -> str:
    return "nes" if not extensions else "nes+" + "+".join(extensions)


def _output_path(source: str, out_argument: str, extensions, suffix: str,
                 multiple: bool) -> str:
    stem = os.path.splitext(os.path.basename(source))[0]
    named = "%s [%s]%s" % (stem, _tag(extensions), suffix)

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


def _convert(source: str, args, extensions, channels, multiple: bool = False) -> int:
    started = time.time()
    importer = importers.find_for(source)
    song = importer(source)

    for warning in song.warnings:
        print("  ! %s" % warning)

    if not song.notes:
        print("  x nothing to convert in %s" % os.path.basename(source))
        return 1

    if args.transpose:
        for note in song.notes:
            note.pitch = max(0, min(127, note.pitch + args.transpose))

    analysis = analyze.analyse(song)
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
        echo=not args.no_echo,
        limit=not args.no_limit,
        compress=bool(args.compress),
    )

    grouped = {}
    for note in notes:
        grouped.setdefault(note.channel, []).append(note)

    if args.stems_dir:
        pcm, stems, duration = render(notes, channels, render_options, grouped)
        written = write_stems(args.stems_dir, stems, render_options)
        print("  + %d per-channel stems in %s" % (len(written), args.stems_dir))
    else:
        pcm, _stems, duration = render(notes, channels, render_options, grouped)

    target = _output_path(source, args.output, extensions, ".wav", multiple)
    write_wav(target, pcm, render_options)

    if args.export_vgm:
        vgm_target = os.path.splitext(target)[0] + ".vgm"
        for message in write_vgm(vgm_target, notes, channels, duration, extensions):
            print("  ! %s" % message)
        print("  > %s" % vgm_target)

    elapsed = time.time() - started
    print("  > %s" % target)
    if args.stats or args.verbose:
        print("  what the file contains:")
        for line in analysis.summary_lines():
            print("    " + line)
        print("  chips: %s" % (", ".join(extensions) or "plain NES"))
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
    parser.add_argument("inputs", nargs="*", help="MIDI / VGM / VGZ / GYM files or folders")
    parser.add_argument("-o", "--output", help="output file or folder")
    parser.add_argument("-e", "--extensions", default="",
                        help="extension chips to enable, comma separated: "
                             "vrc6, mmc5, fds, n163, dmc, psg, or 'all'")
    parser.add_argument("--list-extensions", action="store_true",
                        help="show the chips and the channels they add, then exit")
    parser.add_argument("--stats", action="store_true", help="report what went where")
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
    parser.add_argument("--no-echo", action="store_true",
                        help="no NES-style echo on the mix")
    parser.add_argument("--no-limit", action="store_true",
                        help="no peak limiting on the master")
    parser.add_argument("--compress", action="store_true",
                        help="extra bus compression on the master")
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
    parser.add_argument("--version", action="version", version="chip8bit %s" % VERSION)

    args = parser.parse_args(argv)

    if args.list_extensions:
        print(_extension_help())
        return 0

    if not args.inputs:
        parser.print_help()
        print("\nDrag a .mid, .vgm, .vgz or .gym file onto chip8bit.exe with")
        print("--extensions all to convert it with every extension chip enabled.")
        _pause()
        return 0

    extensions = _parse_extensions(args.extensions)
    channels = chips.build_channel_set(extensions)

    sources = []
    for item in args.inputs:
        if os.path.isdir(item):
            for pattern in ("*.mid", "*.midi", "*.vgm", "*.vgz", "*.gym", "*.zip"):
                sources.extend(sorted(glob.glob(os.path.join(item, pattern))))
        else:
            sources.append(item)

    if not sources:
        print("no input files found")
        return 1

    print("chip8bit %s - %d voice%s%s"
          % (VERSION, len(channels), "" if len(channels) == 1 else "s",
             "" if not extensions else " (%s + %s)" % ("nes", "+".join(extensions))))

    failures = 0
    for index, source in enumerate(sources, 1):
        print("\n[%d/%d] %s" % (index, len(sources), os.path.basename(source)))
        try:
            failures += _convert(source, args, extensions, channels, len(sources) > 1)
        except SystemExit:
            raise
        except Exception as error:            # keep batch conversion going
            print("  x %s: %s" % (type(error).__name__, error))
            failures += 1

    print("\ndone: %d ok, %d failed" % (len(sources) - failures, failures))
    _pause()
    return 0 if failures == 0 else 1


def _pause() -> None:
    """Keep the window open when the exe was double-clicked or given a dropped file."""
    if getattr(sys, "frozen", False) and sys.stdin and sys.stdin.isatty():
        try:
            input("\nPress Enter to close this window...")
        except (EOFError, KeyboardInterrupt):
            pass


if __name__ == "__main__":
    sys.exit(main())
