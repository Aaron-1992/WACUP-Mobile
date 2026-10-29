# chip8bit — NES / 8-bit chiptune transcoder

Takes **MIDI files** (and **game music logs**: VGM, VGZ, GYM, or a `.zip` of them) and
re-composes them for the NES sound chip, then renders 8-bit audio.

* **its own window** — double-click and it opens; no browser, no server, no install;
* **sampled drums** — kick, snare, hats, toms and cymbals are real samples played
  through the console's delta channel, not noise bursts pretending to be drums;
* **no click-and-fizz** — every note has an attack and a release, and the mix is
  gently filtered, so it sounds like music rather than a test tone;
* **every hardware voice is used, and extension chips can be switched on** (4 → 22);
* **channel sharing is rationed**, see below — the tool would rather leave a note
  out than turn your song into a wasp in a jar.

## The window

Double-click **`chip8bit.exe`**. Its own window opens (pygame/SDL — a normal desktop
window, no browser anywhere):

1. **Add music** — drag files onto the window, or press *Add files…* (the real
   Windows file dialog). MIDI, VGM/VGZ, GYM, and `.zip` of any of those.
   *Demo tune* loads something to play with immediately.
2. **Pick chips** — click the extension chips. The header shows your voice count
   (4 → 22). Your choices are remembered between runs.
3. **Convert** — press *Convert*. Each result gets a card: play it (or *Stop*),
   *Save as…* anywhere you like, or *Open folder*. There is also a 16-bit and a
   `.vgm` toggle, and *sampled drums* on/off.

Files dropped **straight onto `chip8bit.exe`** open the window with them queued.
Everything happens on your machine; nothing is uploaded and no port is opened.

## Command line

`chip8bit-cli.exe` is the same engine without a window, for batches and scripts:

```
chip8bit-cli.exe --cli song.mid --extensions vrc6,mmc5,fds --stats
chip8bit-cli.exe --cli games\*.vgz --extensions all -o converted
chip8bit-cli.exe --cli --list-extensions
```

`--bits 8` gives you the crunch; the default is 16-bit. `--no-drums` falls back to
the noise channel, `--no-sharing` forbids arpeggios entirely.

## The chips you can switch on

| flag | adds | channels |
| --- | --- | --- |
| `nes` (always on) | 2A03 APU | `pulse1`, `pulse2`, `triangle`, `noise` |
| `vrc6` | Konami VRC6 | 2 extra pulses + a sawtooth (`vrc6_saw`) |
| `mmc5` | Nintendo MMC5 | 2 extra pulses |
| `fds` | Famicom Disk System | 1 wavetable channel |
| `n163` | Namco 163 | 8 wavetable channels |
| `psg` | SN76489 (Master System / Genesis) | 3 square channels |
| `dmc` | APU delta channel | sampled percussion |

That is 4 voices bare and 22 with everything enabled.

## How the placement rules work

A chip channel plays **one note at a time**. Anything else is a lie that sounds
like one, so:

1. each part is classified (melody / harmony / bass / drums);
2. melody leans on the pulses, bass takes the triangle, drums take the delta
   channel (and the noise channel when it is enabled), harmony fills what is free;
3. a note that finds nothing free is first put on **any other free voice** that
   can plausibly play it;
4. percussion may **take a channel from a hi-hat** — a missing backbeat is worse
   than a clipped hat, and that is what real NES drum code does;
5. only then, and only within a budget, may two or three notes **share** a channel
   as a fast arpeggio — and only if they overlap for long enough for a full cycle,
   so it reads as a chord;
6. parts that duplicate each other note for note are folded into one;
7. anything left over is reported, not smuggled in. Inner harmony voices get
   thinned first, because that is what a composer would do.

`--stats` (and the result card) tells you the exact count of each outcome.

## How it sounds

| piece | what it does |
| --- | --- |
| drums | synthesised-from-scratch kit, quantised to the delta channel's 7-bit 33.1 kHz output — the grit is deliberate |
| notes | 4 ms attack, musical decay, 12 ms release: no digital snaps |
| pulses | 12.5/25/50/75 % duty, 4-bit volume, vibrato follows the MIDI CC1 |
| triangle | the real 32-step staircase, no volume control (that is the point) |
| VRC6 / MMC5 / FDS / N163 / PSG | sawtooth, extra pulses, and wavetables, each rendered the way its chip does it |
| output | gentle low-pass, DC blocker, then the APU's non-linear mixer curve |

## Honest limits

* VGM can only address the NES APU and the SN76489, so `--export-vgm` leaves the
  VRC6/MMC5/FDS/N163 notes out of the log. The WAV always has all of them.
* The delta channel here plays the built-in kit; it is not a sample player for
  arbitrary user samples yet.
* Supported input: MIDI (`.mid .midi .rmi .kar`), VGM/VGZ, GYM, `.zip`. NSF, SPC and
  PSF are different formats — the tool says so instead of guessing.
* A dense orchestral MIDI will still lose inner voices: 22 monophonic voices is a
  hard ceiling, and the tool reports exactly what it dropped.

## Development

```
python -m pip install -r requirements.txt      # pygame, for the window only
python tests/run_tests.py                      # pipeline self test
python chip8bit.py --selftest                   # opens the window headlessly, clicks it
python chip8bit.py                              # the app
python chip8bit.py --cli song.mid --extensions all --stats
```

The converter is standard library only; pygame is needed for the window and for
nothing else.
