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
    public Bitmap numbers;     // numbers.bmp    99x13  (digits + blank)
    public Bitmap numsEx;      // nums_ex.bmp    108x13 (digits + ':' + '-')
    public Bitmap text;        // text.bmp       155x18
    public Bitmap volume;      // volume.bmp     68x13 (+pressed row at y=15)
    public Bitmap balance;     // balance.bmp    38x13 (+pressed row at y=15)
    public Bitmap posbar;      // posbar.bmp     248x10 (+pressed row at y=10)
    public Bitmap playpaus;    // playpaus.bmp   42x9
    public Bitmap monoster;    // monoster.bmp   56x24
    public Bitmap shufrep;     // shufrep.bmp    92x85
    public Bitmap eqmain;      // eqmain.bmp     275x315
    public Bitmap eq_ex;       // eq_ex.bmp      275x315 (equaliser windowshade)
    public Bitmap playlist;    // playlist.bmp   275x116
    public Bitmap pledit;      // pledit.bmp     280x186
    public Bitmap video;       // video.bmp

    public int[] visColors = DEFAULT_VIS;

    /**
     * Alpha masks of text.bmp / numbers.bmp. Winamp colour-keys these sheets (the
     * classic key is magenta, but skins also ship black-on-white or white-on-black),
     * so the glyph pixels are extracted once and later tinted with whatever colour
     * the skin asks for.
     */
    public Bitmap textMask;
    public Bitmap numberMask;

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

    /**
     * Winamp's bitmap font is not in ASCII order: text.bmp row 0 holds a-z, then
     * the quote and the @, row 1 holds the digits and punctuation and row 2 a few
     * accented letters. This table maps ASCII 32..126 to a glyph index
     * (row * 31 + column); -1 means "no glyph, draw a space".
     */
    private static final byte[] GLYPH = {
            30, 48, 26, 61, 60, 57, 56, 47, 44, 45, 66, 50, 58, 46, 42, 52,
            31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 43, 43, 53, 59, 54, 65,
            27, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14,
            15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 53, 51, 54, 55, 49,
            -1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14,
            15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 53, 51, 54, 46,
    };

    /** Glyph index for a character, or the space glyph when the font lacks it. */
    public static int glyphIndex(char ch) {
        char c = ch;
        if (c >= 'A' && c <= 'Z') c = Character.toLowerCase(c);   // the font is lowercase-only
        int index = (c < 127 && c >= 32) ? GLYPH[c - 32] : -1;
        return index < 0 ? GLYPH[' ' - 32] : index;
    }

    public static Skin base() {
        return BaseSkin.create();
    }

    /** Loads a skin that ships inside the APK (the included sample). */
    public static Skin fromAssets(android.content.Context context, String assetName)
            throws IOException {
        java.io.File temp = new java.io.File(context.getCacheDir(), "sample-skin.wsz");
        java.io.InputStream in = null;
        java.io.OutputStream out = null;
        try {
            in = context.getAssets().open(assetName);
            out = new java.io.FileOutputStream(temp);
            byte[] buffer = new byte[8192];
            int read;
            while ((read = in.read(buffer)) > 0) out.write(buffer, 0, read);
        } finally {
            if (in != null) try { in.close(); } catch (IOException ignored) { }
            if (out != null) try { out.close(); } catch (IOException ignored) { }
        }
        return load(temp);
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
            s.numsEx = decode(zip, entries, "nums_ex.bmp");
            // numbers.bmp carries the colon in cell 10; nums_ex.bmp does not, so it is
            // only a fallback for the digits themselves.
            if (s.numbers == null) s.numbers = s.numsEx;
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

            s.textMask = toMask(s.text);
            s.numberMask = toMask(s.numbers);

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

    /**
     * Converts a colour-keyed font sheet into an alpha-only bitmap: every pixel that
     * differs from the sheet's top-left colour becomes opaque, the key colour
     * becomes transparent.
     */
    private static Bitmap toMask(Bitmap source) {
        if (source == null || source.getWidth() == 0 || source.getHeight() == 0) return null;
        int key = source.getPixel(0, 0);
        int width = source.getWidth();
        int height = source.getHeight();
        int[] pixels = new int[width * height];
        source.getPixels(pixels, 0, width, 0, 0, width, height);

        int[] out = new int[pixels.length];
        for (int i = 0; i < pixels.length; i++) {
            int pixel = pixels[i];
            if (pixel == key) {
                out[i] = 0;                        // the colour key -> transparent
                continue;
            }
            // A magenta key often survives compression with slightly different values.
            int r = (pixel >> 16) & 0xFF;
            int g = (pixel >> 8) & 0xFF;
            int b = pixel & 0xFF;
            if (r > 200 && g < 80 && b > 200) {
                out[i] = 0;
                continue;
            }
            out[i] = 0xFFFFFFFF;                   // opaque; the tint supplies the colour
        }
        Bitmap mask = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
        mask.setPixels(out, 0, width, 0, 0, width, height);
        return mask;
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
