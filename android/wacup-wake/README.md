# WACUP Wake

Tiny Android app (Java, no dependencies) that opens an app of your choice — e.g.
**Winlator**, running WACUP — as soon as the screen turns on, so waking the phone
skips the home screen.

It does **not** unlock a secured phone (Android forbids that); it dismisses the
keyguard for you, so the flow is: screen on → PIN/fingerprint → app. With no secure
lock or Smart Lock it is a single step.

## Build

```
Open this folder in Android Studio → sync → Build → Build APK(s)
```

Requires AGP 8.7.3 / Gradle 8.9 / JDK 17, compileSdk 35, minSdk 29. Android Studio
generates the Gradle wrapper on first open. Nothing else to install.

## How it works

| File | Role |
| --- | --- |
| `WakeService` | Foreground service (type `specialUse`) that registers `ACTION_SCREEN_ON` at runtime — the broadcast is protected and cannot be declared in the manifest. |
| `LaunchActivity` | Transparent, `showWhenLocked` + `turnScreenOn`, calls `requestDismissKeyguard()` then starts the target app. |
| `BootReceiver` | Re-arms after reboot / app update. |
| `WakeTileService` | Quick Settings tile to arm/disarm. |
| `MainActivity` | App picker + permission checklist. |

Requires the "display over other apps" permission (background activity start
exemption) and is best with battery optimisation disabled.
