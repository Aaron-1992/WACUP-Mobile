package com.wacup.mobile.skin;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.PorterDuff;
import android.graphics.PorterDuffColorFilter;
import android.graphics.Rect;
import android.graphics.Typeface;

/**
 * Text and number rendering for classic skins.
 *
 * text.bmp is 155x18: 31 columns x 3 rows of 5x6 glyphs covering ASCII 32..126.
 * numbers.bmp / nums_ex.bmp are 9x13 cells: 0-9 then the colon and minus sign.
 *
 * The sheets are colour-keyed, so they are drawn through alpha masks and tinted
 * with whatever colour the skin asks for (this is what makes the marquee follow
 * pledit.txt instead of inheriting the skinner's magenta).
 */
public final class SkinPaint {

    private static final int TEXT_COLS = 31;
    private static final int TEXT_ROWS = 3;
    private static final int FIRST_CHAR = 32;

    private final Skin skin;
    private final Paint tint = new Paint();
    private final Paint fallback = new Paint(Paint.ANTI_ALIAS_FLAG);

    public SkinPaint(Skin skin) {
        this.skin = skin;
        tint.setFilterBitmap(false);
        fallback.setTypeface(Typeface.create(Typeface.MONOSPACE, Typeface.BOLD));
    }

    private Paint tinted(int color, int alpha) {
        tint.setColor(color);
        tint.setAlpha(alpha);
        tint.setColorFilter(new PorterDuffColorFilter(color, PorterDuff.Mode.SRC_IN));
        return tint;
    }

    /** True when the skin ships a usable 5x6 font. */
    public boolean hasFont() {
        return skin.textMask != null;
    }

    /**
     * Draws text with the skin's 5x6 font. {@code color} is the ink colour;
     * {@code maxWidth} clips the run (Winamp clips rather than wraps).
     */
    public float drawText(Canvas c, String s, float x, float y, int color, float maxWidth) {
        if (s == null || s.isEmpty()) return 0f;

        if (skin.textMask != null) {
            Paint paint = tinted(color, 255);
            float cursor = x;
            for (int i = 0; i < s.length(); i++) {
                if (cursor - x >= maxWidth) break;
                int idx = Skin.glyphIndex(s.charAt(i));
                int sx = (idx % TEXT_COLS) * SkinLayout.GLYPH_W;
                int sy = (idx / TEXT_COLS) * SkinLayout.GLYPH_H;
                if (sx + SkinLayout.GLYPH_W > skin.textMask.getWidth()) continue;
                Rect src = new Rect(sx, sy, sx + SkinLayout.GLYPH_W, sy + SkinLayout.GLYPH_H);
                Rect dst = new Rect((int) cursor, (int) y,
                        (int) cursor + SkinLayout.GLYPH_W, (int) y + SkinLayout.GLYPH_H);
                c.drawBitmap(skin.textMask, src, dst, paint);
                cursor += SkinLayout.GLYPH_W;
            }
            return cursor - x;
        }

        fallback.setTextSize(SkinLayout.GLYPH_H + 2);
        fallback.setColor(color);
        c.drawText(s, x, y + SkinLayout.GLYPH_H, fallback);
        return Math.min(maxWidth, fallback.measureText(s));
    }

    /** Width in pixels a string will occupy with the 5x6 font. */
    public float textWidth(String s) {
        if (s == null) return 0f;
        if (skin.textMask != null) return s.length() * (float) SkinLayout.GLYPH_W;
        fallback.setTextSize(SkinLayout.GLYPH_H + 2);
        return fallback.measureText(s);
    }

    /**
     * Draws the mm:ss display in Winamp's four fixed digit slots, with the colon
     * between the second and third slot. Digit colours come from the skin's
     * viscolor.txt entry 23 when available.
     */
    public void drawTime(Canvas c, String time, int color) {
        String digits = time == null ? "0000" : time.replace(":", "");
        for (int slot = 0; slot < 4; slot++) {
            char ch = slot < digits.length() ? digits.charAt(slot) : '0';
            int x = SkinLayout.TIME_DIGIT_X[slot];
            if (ch < '0' || ch > '9') {
                drawColonOrMinus(c, ch, x, SkinLayout.TIME_Y, color);
                continue;
            }
            drawDigit(c, ch - '0', x, SkinLayout.TIME_Y, color);
        }
        drawColonOrMinus(c, ':', SkinLayout.TIME_COLON_X, SkinLayout.TIME_Y, color);
    }

    private void drawDigit(Canvas c, int digit, int x, int y, int color) {
        if (skin.numberMask != null
                && (digit + 1) * SkinLayout.DIGIT_W <= skin.numberMask.getWidth()) {
            Rect src = new Rect(digit * SkinLayout.DIGIT_W, 0,
                    digit * SkinLayout.DIGIT_W + SkinLayout.DIGIT_W, SkinLayout.DIGIT_H);
            Rect dst = new Rect(x, y, x + SkinLayout.DIGIT_W, y + SkinLayout.DIGIT_H);
            c.drawBitmap(skin.numberMask, src, dst, tinted(color, 255));
            return;
        }
        fallback.setTextSize(18);
        fallback.setColor(color);
        fallback.setTypeface(Typeface.create(Typeface.MONOSPACE, Typeface.BOLD));
        c.drawText(String.valueOf((char) ('0' + digit)), x, y + SkinLayout.DIGIT_H, fallback);
    }

    /**
     * nums_ex.bmp keeps ':' in cell 10 and '-' in cell 11. Without that sheet the
     * glyphs are drawn as simple pixels.
     */
    private void drawColonOrMinus(Canvas c, char ch, int x, int y, int color) {
        int cell = (ch == ':' || ch == '-') ? 10 : -1;
        boolean colonSheet = skin.numbers != null
                && skin.numbers.getWidth() >= 11 * SkinLayout.DIGIT_W
                && skin.numbers != skin.numsEx;
        if (cell >= 0 && colonSheet && skin.numberMask != null
                && (cell + 1) * SkinLayout.DIGIT_W <= skin.numberMask.getWidth()) {
            Rect src = new Rect(cell * SkinLayout.DIGIT_W, 0,
                    cell * SkinLayout.DIGIT_W + SkinLayout.DIGIT_W, SkinLayout.DIGIT_H);
            Rect dst = new Rect(x, y, x + SkinLayout.DIGIT_W, y + SkinLayout.DIGIT_H);
            c.drawBitmap(skin.numberMask, src, dst, tinted(color, 255));
            return;
        }
        Paint dots = tinted(color, 255);
        dots.setColorFilter(null);
        if (ch == ':') {
            c.drawRect(x + 4, y + 3, x + 6, y + 5, dots);
            c.drawRect(x + 4, y + 8, x + 6, y + 10, dots);
        } else if (ch == '-') {
            c.drawRect(x + 2, y + 6, x + 7, y + 8, dots);
        }
    }

    /** Draws a cropped sprite, or nothing when the skin lacks it. */
    public static void sprite(Canvas c, Bitmap src, int sx, int sy, int w, int h,
                              int dx, int dy, Paint paint) {
        if (src == null) return;
        int cw = Math.min(w, src.getWidth() - sx);
        int ch = Math.min(h, src.getHeight() - sy);
        if (cw <= 0 || ch <= 0) return;
        c.drawBitmap(src, new Rect(sx, sy, sx + cw, sy + ch),
                new Rect(dx, dy, dx + cw, dy + ch), paint);
    }
}
