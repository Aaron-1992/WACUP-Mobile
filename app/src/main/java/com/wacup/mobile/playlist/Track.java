package com.wacup.mobile.playlist;

import java.io.File;
import java.util.Locale;

/** One playlist entry. Duration is -1 until a media file has been probed. */
public final class Track {

    public final File file;
    public final String title;
    public final long durationMs;

    public Track(File file, String title, long durationMs) {
        this.file = file;
        this.title = title;
        this.durationMs = durationMs;
    }

    public static Track of(File file) {
        return new Track(file, prettyName(file), -1L);
    }

    public static Track of(File file, String title, long durationMs) {
        return new Track(file, title, durationMs);
    }

    private static String prettyName(File file) {
        String name = file.getName();
        int dot = name.lastIndexOf('.');
        if (dot > 0) name = name.substring(0, dot);
        return name;
    }

    /** "3:07" style label, or "--:--" when unknown. */
    public String durationLabel() {
        if (durationMs <= 0) return "--:--";
        long totalSeconds = durationMs / 1000L;
        long h = totalSeconds / 3600L;
        long m = (totalSeconds % 3600L) / 60L;
        long s = totalSeconds % 60L;
        if (h > 0) {
            return String.format(Locale.US, "%d:%02d:%02d", h, m, s);
        }
        return String.format(Locale.US, "%d:%02d", m, s);
    }

    public boolean exists() {
        return file.exists() && file.isFile();
    }
}
