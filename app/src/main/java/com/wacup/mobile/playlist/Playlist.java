package com.wacup.mobile.playlist;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.io.Writer;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;

/**
 * A Winamp/WACUP playlist: reads and writes .m3u (plain and #EXTINF), .m3u8 and
 * .pls, tolerates Windows backslash paths and CRLF, and resolves relative entries
 * against the playlist's own folder so a library copied from the PC still works.
 */
public final class Playlist {

    public static final String[] AUDIO_EXTENSIONS = {
            "mp3", "flac", "ogg", "oga", "opus", "m4a", "mp4", "aac", "wav", "aiff",
            "aif", "wma", "ape", "wv", "mid", "midi", "mod", "xm", "it", "s3m", "m3u", "m3u8", "pls"
    };

    public final List<Track> tracks = new ArrayList<>();

    public int size() {
        return tracks.size();
    }

    public Track get(int index) {
        if (index < 0 || index >= tracks.size()) return null;
        return tracks.get(index);
    }

    public void clear() {
        tracks.clear();
    }

    public void add(Track track) {
        tracks.add(track);
    }

    public void addAll(List<Track> other) {
        tracks.addAll(other);
    }

    public void removeAt(int index) {
        if (index >= 0 && index < tracks.size()) tracks.remove(index);
    }

    public void move(int from, int to) {
        if (from < 0 || from >= tracks.size()) return;
        if (to < 0 || to >= tracks.size()) return;
        Track t = tracks.remove(from);
        tracks.add(to, t);
    }

    public long totalDurationMs() {
        long total = 0;
        for (Track t : tracks) {
            if (t.durationMs > 0) total += t.durationMs;
        }
        return total;
    }

    // ---------------------------------------------------------------- reading

    public static Playlist read(File file) throws IOException {
        String name = file.getName().toLowerCase(Locale.US);
        if (name.endsWith(".pls")) return readPls(file);
        return readM3u(file);
    }

    private static Playlist readM3u(File file) throws IOException {
        Playlist playlist = new Playlist();
        File parent = file.getParentFile();

        BufferedReader reader = new BufferedReader(
                new InputStreamReader(new FileInputStream(file), "UTF-8"));
        try {
            String pendingTitle = null;
            long pendingDuration = -1L;
            String line;
            while ((line = reader.readLine()) != null) {
                String trimmed = line.trim();
                if (trimmed.isEmpty()) continue;

                if (trimmed.startsWith("#")) {
                    if (trimmed.regionMatches(true, 0, "#EXTINF:", 0, 8)) {
                        String meta = trimmed.substring(8);
                        int comma = meta.indexOf(',');
                        if (comma > 0) {
                            String dur = meta.substring(0, comma).trim();
                            try {
                                pendingDuration = (long) (Double.parseDouble(dur) * 1000);
                            } catch (NumberFormatException ignored) {
                                pendingDuration = -1L;
                            }
                            pendingTitle = meta.substring(comma + 1).trim();
                        }
                    }
                    continue;   // comments / #EXTM3U
                }

                File resolved = resolve(parent, trimmed);
                String title = (pendingTitle != null && !pendingTitle.isEmpty())
                        ? pendingTitle
                        : Track.of(resolved).title;
                playlist.add(new Track(resolved, title, pendingDuration));
                pendingTitle = null;
                pendingDuration = -1L;
            }
        } finally {
            reader.close();
        }
        return playlist;
    }

    private static Playlist readPls(File file) throws IOException {
        Playlist playlist = new Playlist();
        File parent = file.getParentFile();

        List<String> files = new ArrayList<>();
        List<String> titles = new ArrayList<>();
        List<String> durations = new ArrayList<>();

        BufferedReader reader = new BufferedReader(
                new InputStreamReader(new FileInputStream(file), "UTF-8"));
        try {
            String line;
            while ((line = reader.readLine()) != null) {
                String trimmed = line.trim();
                int eq = trimmed.indexOf('=');
                if (eq <= 0) continue;
                String key = trimmed.substring(0, eq).trim().toLowerCase(Locale.US);
                String value = trimmed.substring(eq + 1).trim();
                if (key.startsWith("file") && key.length() > 4 && isDigits(key.substring(4))) {
                    put(files, indexOf(key, 4), value);
                } else if (key.startsWith("title") && key.length() > 5 && isDigits(key.substring(5))) {
                    put(titles, indexOf(key, 5), value);
                } else if (key.startsWith("length") && key.length() > 6 && isDigits(key.substring(6))) {
                    put(durations, indexOf(key, 6), value);
                }
            }
        } finally {
            reader.close();
        }

        for (int i = 0; i < files.size(); i++) {
            String raw = files.get(i);
            if (raw == null) continue;
            File resolved = resolve(parent, raw);
            String title = (i < titles.size() && titles.get(i) != null && !titles.get(i).isEmpty())
                    ? titles.get(i)
                    : Track.of(resolved).title;
            long duration = -1L;
            if (i < durations.size() && durations.get(i) != null) {
                try {
                    duration = (long) (Double.parseDouble(durations.get(i)) * 1000);
                } catch (NumberFormatException ignored) {
                    duration = -1L;
                }
            }
            playlist.add(new Track(resolved, title, duration));
        }
        return playlist;
    }

    private static boolean isDigits(String s) {
        if (s.isEmpty()) return false;
        for (int i = 0; i < s.length(); i++) {
            if (!Character.isDigit(s.charAt(i))) return false;
        }
        return true;
    }

    private static int indexOf(String key, int from) {
        try {
            return Integer.parseInt(key.substring(from)) - 1;
        } catch (NumberFormatException e) {
            return -1;
        }
    }

    private static void put(List<String> list, int index, String value) {
        if (index < 0) return;
        while (list.size() <= index) list.add(null);
        list.set(index, value);
    }

    /** Handles absolute, relative, Windows-style and file:// entries. */
    static File resolve(File parent, String entry) {
        String path = entry;
        if (path.regionMatches(true, 0, "file://", 0, 7)) {
            path = path.substring(7);
            try {
                path = java.net.URLDecoder.decode(path, "UTF-8");
            } catch (Exception ignored) {
                // keep raw
            }
        }
        path = path.replace('\\', '/');
        File f = new File(path);
        if (!f.isAbsolute()) {
            // Windows drive letters such as C:/music stay non-absolute on Android.
            if (path.length() >= 2 && path.charAt(1) == ':') {
                return new File(parent, path.substring(path.lastIndexOf('/') + 1));
            }
            f = new File(parent, path);
        }
        return f;
    }

    // ---------------------------------------------------------------- writing

    public void write(File file) throws IOException {
        Writer out = new OutputStreamWriter(new FileOutputStream(file), "UTF-8");
        try {
            out.write("#EXTM3U\n");
            for (Track t : tracks) {
                long seconds = t.durationMs > 0 ? t.durationMs / 1000L : -1L;
                out.write("#EXTINF:" + seconds + "," + t.title + "\n");
                out.write(t.file.getAbsolutePath() + "\n");
            }
        } finally {
            out.close();
        }
    }

    // ------------------------------------------------------------- collecting

    public static List<Track> scanFolder(File dir, boolean recursive) {
        List<Track> found = new ArrayList<>();
        File[] children = dir.listFiles();
        if (children == null) return found;
        Arrays.sort(children, new Comparator<File>() {
            @Override
            public int compare(File a, File b) {
                return a.getName().compareToIgnoreCase(b.getName());
            }
        });
        for (File child : children) {
            if (child.isDirectory()) {
                if (recursive) found.addAll(scanFolder(child, true));
            } else if (isAudio(child)) {
                found.add(Track.of(child));
            }
        }
        return found;
    }

    public static boolean isAudio(File file) {
        String name = file.getName().toLowerCase(Locale.US);
        int dot = name.lastIndexOf('.');
        if (dot < 0) return false;
        String ext = name.substring(dot + 1);
        for (String known : AUDIO_EXTENSIONS) {
            if (known.equals(ext)) return true;
        }
        return false;
    }

    public static boolean isPlaylist(File file) {
        String name = file.getName().toLowerCase(Locale.US);
        return name.endsWith(".m3u") || name.endsWith(".m3u8") || name.endsWith(".pls");
    }
}
