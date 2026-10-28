package com.wacup.mobile.skin;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;

import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.util.Enumeration;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/**
 * A classic (Winamp 2.x) skin, loaded from a .wsz / .zip file.
 *
 * Every drawing element is a bitmap inside the archive. Anything a skin does not
 * provide stays null and the renderer falls back to a drawn equivalent, so broken
 * or partial skin archives still work.
 */
public final class Skin {

    /** viscolor.txt fallback: the classic green analyser ramp. */
    public static final int[] DEFAULT_VIS = {
            0xFF000000, 0xFF0E4600, 0xFF0E4600, 0xFF0E6E00, 0xFF0E6E00, 0xFF0E8E00,
            0xFF0E8E00, 0xFF0EA600, 0xFF0EA600, 0xFF0EC200, 0xFF0EC200, 0xFF0EE200,
            0xFF0EE200, 0xFF00F800, 0xFF00F800, 0xFF00F800, 0xFF00F800, 0xFF00F800,
            0xFF00F800, 0xFF00F800, 0xFF00F800, 0xFF00F800, 0xFF00F800, 0xFF00F800
    };

    public Bitmap main;        // main.bmp       275x116
    public Bitmap cbuttons;    // cbuttons.bmp   136x36
    public Bitmap titlebar;    // titlebar.bmp   275x87
    public Bitmap numbers;     // numbers.bmp    108x13
    public Bitmap text;        // text.bmp       155x18
    public Bitmap volume;      // volume.bmp     68x13 (+pressed row at y=15)
    public Bitmap balance;     // balance.bmp    38x13 (+pressed row at y=15)
    public Bitmap posbar;      // posbar.bmp     248x10 (+pressed row at y=10)
    public Bitmap playpaus;    // playpaus.bmp   42x9
    public Bitmap monoster;    // monoster.bmp   56x24
    public Bitmap shufrep;     // shufrep.bmp    92x85
    public Bitmap eqmain;      // eqmain.bmp     275x315
    public Bitmap eq_ex;       // eq_ex.bmp      275x315
    public Bitmap playlist;    // playlist.bmp   275x116
    public Bitmap pledit;      // pledit.bmp     280x186
    public Bitmap video;       // video.bmp

    public int[] visColors = DEFAULT_VIS;

    // pledit.txt: playlist colours + font name
    public int plNormal = 0xFF00FF00;
    public int plCurrent = 0xFFFFFFFF;
    public int plNormalBg = 0xFF000000;
    public int plSelectedBg = 0xFF0000C0;
    public String plFont = "Arial";

    public boolean isBase;
    public String name = "Winamp base skin";

    /** Package-private: the built-in skin is built by BaseSkin. */
    Skin() { }

    public static Skin base() {
        return BaseSkin.create();
    }

    /** True when the skin supplies a usable 5x6 bitmap font. */
    public boolean hasTextFont() {
        return text != null && text.getWidth() >= 155;
    }

    public boolean hasNumberFont() {
        return numbers != null && numbers.getWidth() >= 99;
    }

    /**
     * Loads a .wsz/.zip skin. Throws IOException if the archive is unreadable or
     * contains no recognisable skin bitmaps.
     */
    public static Skin load(File file) throws IOException {
        ZipFile zip = new ZipFile(file);
        try {
            Map<String, ZipEntry> entries = new HashMap<>();
            Enumeration<? extends ZipEntry> en = zip.entries();
            while (en.hasMoreElements()) {
                ZipEntry e = en.nextElement();
                if (e.isDirectory()) continue;
                String base = new File(e.getName()).getName().toLowerCase(Locale.US);
                entries.put(base, e);
            }

            Skin s = new Skin();
            s.name = file.getName();
            s.main = decode(zip, entries, "main.bmp");
            s.cbuttons = decode(zip, entries, "cbuttons.bmp");
            s.titlebar = decode(zip, entries, "titlebar.bmp");
            s.numbers = decode(zip, entries, "numbers.bmp");
            s.text = decode(zip, entries, "text.bmp");
            s.volume = decode(zip, entries, "volume.bmp");
            s.balance = decode(zip, entries, "balance.bmp");
            s.posbar = decode(zip, entries, "posbar.bmp");
            s.playpaus = decode(zip, entries, "playpaus.bmp");
            s.monoster = decode(zip, entries, "monoster.bmp");
            s.shufrep = decode(zip, entries, "shufrep.bmp");
            s.eqmain = decode(zip, entries, "eqmain.bmp");
            s.eq_ex = decode(zip, entries, "eq_ex.bmp");
            s.playlist = decode(zip, entries, "playlist.bmp");
            s.pledit = decode(zip, entries, "pledit.bmp");
            s.video = decode(zip, entries, "video.bmp");

            if (s.main == null && s.playlist == null && s.eqmain == null) {
                throw new IOException("No Winamp skin bitmaps found in this archive");
            }

            String pleditTxt = readText(zip, entries, "pledit.txt");
            if (pleditTxt != null) s.parsePledit(pleditTxt);

            String visTxt = readText(zip, entries, "viscolor.txt");
            if (visTxt != null) s.parseViscolor(visTxt);

            return s;
        } finally {
            try {
                zip.close();
            } catch (IOException ignored) {
                // nothing useful to do
            }
        }
    }

    private void parsePledit(String txt) {
        for (String raw : txt.split("\r?\n")) {
            String line = raw.trim();
            int eq = line.indexOf('=');
            if (eq <= 0) continue;
            String key = line.substring(0, eq).trim().toLowerCase(Locale.US);
            String value = line.substring(eq + 1).trim();
            try {
                switch (key) {
                    case "normal": plNormal = parseColor(value); break;
                    case "current": plCurrent = parseColor(value); break;
                    case "normalbg": plNormalBg = parseColor(value); break;
                    case "selectedbg": plSelectedBg = parseColor(value); break;
                    case "font": plFont = value; break;
                    default: break;
                }
            } catch (RuntimeException ignored) {
                // a malformed colour line should not break the whole skin
            }
        }
    }

    private void parseViscolor(String txt) {
        int[] colors = new int[24];
        int count = 0;
        for (String raw : txt.split("\r?\n")) {
            String line = raw.trim();
            if (line.isEmpty()) continue;
            String[] parts = line.split(",");
            if (parts.length < 3) continue;
            try {
                int r = clamp255(Integer.parseInt(parts[0].trim()));
                int g = clamp255(Integer.parseInt(parts[1].trim()));
                int b = clamp255(Integer.parseInt(parts[2].trim()));
                if (count < colors.length) {
                    colors[count++] = 0xFF000000 | (r << 16) | (g << 8) | b;
                }
            } catch (NumberFormatException ignored) {
                // skip junk lines
            }
        }
        if (count >= 16) {
            if (count < colors.length) {
                colors[count] = colors[count - 1];
            }
            visColors = colors;
        }
    }

    private static int clamp255(int v) {
        return v < 0 ? 0 : (v > 255 ? 255 : v);
    }

    /** #RRGGBB or #RRGGBBAA as used by pledit.txt. */
    static int parseColor(String value) {
        String v = value.trim();
        if (v.startsWith("#")) v = v.substring(1);
        if (v.length() == 6) {
            return 0xFF000000 | Integer.parseInt(v, 16);
        } else if (v.length() == 8) {
            // pledit.txt stores #RRGGBBAA
            long rgb = Long.parseLong(v.substring(0, 6), 16);
            long alpha = Long.parseLong(v.substring(6, 8), 16);
            return (int) ((alpha << 24) | rgb);
        }
        throw new NumberFormatException("bad colour " + value);
    }

    private static Bitmap decode(ZipFile zip, Map<String, ZipEntry> entries, String name) {
        ZipEntry entry = entries.get(name);
        if (entry == null) return null;
        InputStream in = null;
        try {
            in = zip.getInputStream(entry);
            BitmapFactory.Options opts = new BitmapFactory.Options();
            opts.inPreferredConfig = Bitmap.Config.ARGB_8888;
            return BitmapFactory.decodeStream(in, null, opts);
        } catch (Exception e) {
            return null;
        } finally {
            closeQuietly(in);
        }
    }

    private static String readText(ZipFile zip, Map<String, ZipEntry> entries, String name) {
        ZipEntry entry = entries.get(name);
        if (entry == null) return null;
        InputStream in = null;
        try {
            in = zip.getInputStream(entry);
            java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
            byte[] buf = new byte[4096];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            return new String(out.toByteArray(), "ISO-8859-1");
        } catch (Exception e) {
            return null;
        } finally {
            closeQuietly(in);
        }
    }

    private static void closeQuietly(InputStream in) {
        if (in != null) {
            try {
                in.close();
            } catch (IOException ignored) {
                // ignore
            }
        }
    }
}
