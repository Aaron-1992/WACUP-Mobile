# WACUP on Android — is there a port, and could one be built?

_Research notes, 2026-10-28._

## TL;DR

- **There is no WACUP for Android**, and there is no announced one. WACUP is a
  Windows-only (Win32, x86 + x64) application.
- **A literal port is not realistic.** Not "hard" — structurally a rewrite, not a port.
- **Alternatives do exist** if what you want is the Winamp experience in your pocket:
  a classic-skin player (Xenamp / WinampSkin), the official reborn Winamp app, or
  running the real `wacup.exe` under Wine via Winlator.
- **What this repo can realistically become:** a *new* Android player that is
  skin-compatible and WACUP-friendly (same files, same playlists, same look) —
  not a compiled WACUP. See "Options" below.

## State of WACUP upstream

- WACUP (Winamp Community Update Project) is maintained by "dro". Current builds
  are 1.99.56.x (x86 and x64), released every few weeks — the project is actively
  alive and Windows-only.
- On running it on other platforms, dro's own words (Raspberry Pi thread):

  > "WACUP is a Windows only solution for now & will be for quite some time to
  > come (a native linux version is a possible long-term goal once the windows
  > version is completely sorted)"

  A native Linux build is a *maybe, someday*. Android has never been on the roadmap.
- Source availability: WACUP is **not** open source as a whole. Only some plugins
  are published (github.com/WACUP). The core is a mix of the Winamp 5.666 binary
  (downloaded at install time for the x86 build), live code patches, and dro's own
  code. The official Winamp source release (github.com/WinampDesktop/winamp) is
  under a restrictive license, and WACUP does not build on it.

## Why a port is not a port

| WACUP piece | Reality | Android impact |
|---|---|---|
| Core player | Win32 C/C++, x86/x64, MSVC, win32 message loop | Everything below the UI has to be rewritten |
| Classic skins | Pixel-perfect fixed-size BMP/PNG windows with per-region hit maps, drawn with GDI | Reimplementable — this is the *easy* part (a 2D renderer) |
| Modern skins | Freeform skin engine: XML + maki scripts + WASABI objects | A second, script-interpreting engine. Years of work by itself |
| Plugin ABI | 32-bit Windows DLLs loaded in-process (in_/out_/dsp_/gen_/ml_) | No concept of a DLL ABI on Android; each plugin needs a native replacement |
| Input/Output | DirectShow/BASS/WASAPI, device enumeration | Has to become Media3/ExoPlayer + AudioTrack |
| Visualizations | DirectX/Milkdrop, AVS | Needs GLES/Vulkan ports; Milkdrop has an existing open-source GL reimplementation |
| Media Library | Local SQLite-ish DB, Win32 paths, watch folders | Needs a MediaStore/SAF-based library instead |

Net: roughly "reimplement a 25-year-old Windows desktop app". It is a fun project
but it is not a port, and it never tracks upstream automatically.

## What already exists on Android

1. **Official Winamp (Llama Group)** — the rebooted app (2022, still updated).
   Completely different codebase, streaming/cloud oriented. No Winamp skins, no
   classic visualizations. PR-speak "Winamp" but not the Winamp people remember.
2. **Xenamp / WinampSkin** — open source, written from scratch in Java/Kotlin.
   Renders **classic (2.x) `.wsz` skins pixel-perfectly**, can browse and load skins
   from the Winamp Skin Museum, plays local music. Closest thing to "Winamp on
   Android" that exists today. Also the best reference implementation to study.
   - github.com/djshaji/WinampSkin (older), github.com/djshaji/eva (rewrite)
3. **Poweramp / AIMP / Musicolet / foobar2000 mobile** — good players with
   Winamp-ish skins/themes. Practical daily drivers, not Winamp.
4. **Winlator** (Wine + Box86/Box64) — actually runs `wacup.exe` on ARM Android.
   Real WACUP, real plugins, real skins. But: desktop UX on a phone screen,
   heavy battery use, needs a container + manual install, no Android media
   notification/lockscreen/Bluetooth controls, and the x86 build wants the
   Winamp 5.666 payload at install time (the x64 build does not). This is the
   answer if the goal is "the genuine article, however awkward".

## Options for this repository

**A. "Winamp-compatible Android player" (recommended, genuinely shippable)**
Kotlin + Jetpack Compose app on Media3. Ships a classic-skin engine that parses
`.wsz` (main/EQ/playlist windows, region.txt, viscolor.txt, cbuttons, numbers),
reads WACUP/Winamp `.m3u`/`.pls` playlists, `.wsz` skin loading from the Skin
Museum, proper Android media session (lockscreen, Bluetooth, Android Auto-ish).
Not WACUP, but *interoperable* with a WACUP library and instantly familiar.
MVP scope: main window + playlist + EQ rendering, local playback, playlist import.

**B. "WACUP companion"**
Android app that talks to WACUP on the desktop: browse the media library, control
playback, push files. Requires a small desktop-side bridge (WACUP has no public
remote API), so it is two codebases and an upstream dependency. Good as a side
project, not as "WACUP Mobile".

**C. "Winlator provisioning kit"**
Not an app: scripts/config + a guide that produces a working WACUP container on
Android with sane touch settings. Fastest way to actually run WACUP on a phone,
zero reimplementation, but it is packaging, not software.

**D. Spec + prototype only**
Document the classic-skin file format and build a renderer test harness (skin
loader + window compositor, no audio) so a future app has a solid foundation.
