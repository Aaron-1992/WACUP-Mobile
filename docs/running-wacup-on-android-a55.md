# Running WACUP on a Galaxy A55 5G

Goal: the real, unmodified `wacup.exe` — Winamp 5.666/WACUP behaviour, real skins,
real plugins — running on your phone, and having it come up when you wake the phone.

Your phone: Exynos 1480, **Xclipse 530** (RDNA2) GPU, 8 GB RAM, Android 14/One UI 6.1.
That matters twice: no Turnip (Adreno-only), and 8 GB is comfortable for Wine.

---

## Part 1 — Get WACUP running (Winlator)

Do this first and *use it for a day* before investing in Part 2. Wine-on-ARM is a
nerd project, not an app store download, and no one has published a WACUP-on-Android
walkthrough — so treat the exact steps below as the best-known starting point.

**1. Pick the emulator build**

| Build | Why / why not |
| --- | --- |
| **Winlator (official, brunodev85) 11.2+** | Recommended start. Ships **Vortek** (Vulkan pass-through) and **Gladio**, which is what non-Adreno GPUs like yours need. |
| Winlator Mali Bionic | MediaTek/Exynos-tuned fork; keep as a fallback if the official build renders black. |
| Winlator Cmod/other forks | Only if you want to tinker. |

Install the APK (side-load; allow "install unknown apps" for your file manager).

**2. Create a container**

- Screen size **1280x720** (or 1024x768 if the WACUP window feels cramped), DPI ~96
- Graphics driver: **Vortek** first → **Gladio** if the window stays black
- DX wrapper: **WineD3D** (WACUP's UI is GDI; you don't need DXVK)
- Audio: **ALSA** (switch to Pulse only if you get no sound)
- Box64 preset: **Compatibility / Stability**, not "Performance"
- Windows version: **Windows 7** (WACUP/Winamp era code is happiest there)

**3. Install WACUP**

- Download the **x64** WACUP build from getwacup.com (1.99.56.x preview).
  Take x64, not x86: the x86 installer pulls the Winamp 5.666 payload down during
  install, and 32-bit needs box86/WOW64, which is slower and fussier.
- Put the `.exe` in the container's `Download` folder (Winlator exposes it under
  `C:\users\...\Download`), run it from the container's File Explorer (Winlator ships
  one, plus WinMerge-free basics — if you're missing an explorer, install a tiny one
  or run the installer from Winlator's "Shortcuts" launcher).
- Install to `C:\WACUP`, then launch `C:\WACUP\wacup.exe`.

**4. Make it usable on a touchscreen**

- Winlator's input mode: **Touchpad** (relative mouse) for clicking WACUP's fake
  buttons, or **Direct touch** if you're using a classic skin fullscreen.
- Add a shortcut for `wacup.exe` to the container's home so it's one tap.
- Classic (2.x) skins are the best experience: they're fixed-size, GDI-drawn, and
  behave. Freeform (modern) skins rely on layered/alpha drawing and often glitch.
- Visualisations (Milkdrop/AVS) go through WineD3D → expect poor frame rates or
  crashes. Not the point on a phone anyway.

**5. Reality check**

- No lockscreen/Bluetooth/Android Auto media controls — WACUP is just a window, so
  Android sees "Winlator playing audio", not a music player.
- Background playback: Winlator may pause the container when it's not in the
  foreground, so "screen off, music keeps playing" is not guaranteed. Test it. If
  it fails, that's the one thing a native player does better.
- Don't bother with the x86 build unless a specific plugin forces you there.

---

## Part 2 — Wake the phone straight into it

**What Android will not do:** an app cannot silently unlock a locked phone, and a
foreign app cannot draw over the keyguard. (Google Maps can, because Maps itself
declares `showWhenLocked` while navigating. Winlator doesn't, and we can't change
that without modifying Winlator.) Samsung's Modes & Routines also can't unlock —
its own docs say the phone "can't unlock itself", and "open app" only works once
unlocked.

So the best achievable sequence is:

```
press power / fingerprint
      → keyguard dismissed
      → Winlator opens straight away (home screen never appears)
      → one tap on the WACUP shortcut
```

...and with **no secure lock** or **Smart Lock** (trusted place/device), the
pin/fingerprint step disappears and it is genuinely "screen on → WACUP".

**The app:** `android/wacup-wake/` in this repo. It's a ~400-line, no-dependency
Android project that does exactly one thing: on `ACTION_SCREEN_ON` it starts an
invisible activity that dismisses the keyguard and launches the app you picked.

Build it (you need a machine with Android Studio, since this sandbox has no SDK):

```
1. Open android/wacup-wake in Android Studio (it adds the Gradle wrapper itself).
2. Let it sync (AGP 8.7.3, compileSdk 35), then Build → Build APK(s).
3. Copy app/build/outputs/apk/debug/app-debug.apk to the phone, install it.
```

Set it up:

1. Open **WACUP Wake** → **Choose app…** → **Winlator**.
2. **Allow display over other apps** → grant (Android requires this for any app to
   start another app from the background).
3. **Ignore battery optimisation** → allow (otherwise Samsung kills the listener).
4. Phone settings → **Battery → Background usage limits** → add both Winlator and
   WACUP Wake to **Never sleeping apps**.
5. **Arm / disarm** → ARMED. It also survives reboots and is available as a Quick
   Settings tile, so you can switch it off when you don't want it.

Then **Test the wake-up now**: it should behave exactly like a screen-on.

If you'd rather not build anything, **Tasker** can approximate it (Profile →
Event → Display → Display Unlocked → Task → Launch App → Winlator), with
`AutoInput`/`Secure Settings` if you want to fight the keyguard. The catch is the
same: it can't unlock, and Tasker + AutoInput is a paid, battery-hungry stack.

---

## What this does *not* get you

- True "app shows instead of the home screen" while the phone is **locked** — that
  is an OS-level capability reserved for the lock screen itself (and for apps that
  declare it, like navigation/phone apps). Only a launcher replacement or a custom
  ROM changes that.
- A real Android music player: no media notification, no Bluetooth controls, no
  audio focus handling. If that bothers you, the fallback plan is the native
  skin-compatible player discussed in `docs/wacup-on-android.md` (option A) — it
  can do all of the above, because Android sees it as a music app.

## If WACUP won't start under Wine

In rough order of likelihood:

1. **Black/nothing**: switch graphics driver Vortek → Gladio → Zink, and retry.
2. **Installer crashes**: run it with Windows version 7, and make sure the container
   has at least 4 GB of "container RAM" if the setting exists.
3. **Silent / no audio**: ALSA → Pulse, and check Winlator's audio sample rate.
4. **UI drawn but unclickable**: switch input mode to Touchpad.
5. **Works but unusably slow**: lower container resolution to 960x540; this is a
   mid-range phone, WACUP itself is light but Wine + Box64 is not free.

Sound and playback are the parts most likely to work; modern skins and
visualisations are the parts most likely not to.
