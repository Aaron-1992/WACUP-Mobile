package com.wacup.wake;

import android.content.Context;
import android.content.SharedPreferences;
import android.provider.Settings;

/** Tiny settings holder — no AndroidX, no DataStore, survives reboots in prefs. */
final class Prefs {

    private static final String FILE = "wacup_wake";
    private static final String KEY_PACKAGE = "target_package";
    private static final String KEY_LABEL = "target_label";
    private static final String KEY_ENABLED = "enabled";

    private Prefs() { }

    private static SharedPreferences file(Context c) {
        return c.getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    static String targetPackage(Context c) {
        return file(c).getString(KEY_PACKAGE, "");
    }

    static String targetLabel(Context c) {
        return file(c).getString(KEY_LABEL, "");
    }

    static void setTarget(Context c, String pkg, String label) {
        file(c).edit().putString(KEY_PACKAGE, pkg).putString(KEY_LABEL, label).apply();
    }

    static boolean enabled(Context c) {
        return file(c).getBoolean(KEY_ENABLED, false);
    }

    static void setEnabled(Context c, boolean on) {
        file(c).edit().putBoolean(KEY_ENABLED, on).apply();
    }

    /** Also acts as the "may start an activity from the background" exemption. */
    static boolean canDrawOverlays(Context c) {
        return Settings.canDrawOverlays(c);
    }
}
