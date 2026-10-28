package com.wacup.mobile.skin;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.Typeface;

/**
 * Drawing helpers for skin sprites: the 5x6 bitmap text font (text.bmp) and the
 * 9x13 number font (numbers.bmp), with Text-rendered fallbacks when a skin does
 * not ship them.
 *
 * text.bmp is 155x18: 31 glyphs per row, 3 rows, 5x6 each, covering ASCII 32..126.
 */
public final class SkinPaint {

    private static final int TEXT_COLS = 31;
    private static final int TEXT_ROWS = 3;
    private static final int FIRST_CHAR = 32;

    private final Skin skin;
    private final Paint fallback = new Paint(Paint.ANTI_ALIAS_FLAG);

    public SkinPaint(Skin skin) {
        this.skin = skin;
        fallback.setTypeface(Typeface.create(Typeface.MONOSPACE, Typeface.BOLD));
        fallback.setColor(0xFF00F800);
    }

    /** Draws a string with the skin's 5x6 font, using a colour filter paint. */
    public float drawText(Canvas c, String s, float x, float y, Paint paint, int maxWidth) {
        if (s == null) s = "";
        if (skin.hasTextFont()) {
            float cursor = x;
            for (int i = 0; i < s.length(); i++) {
                char ch = s.charAt(i);
                int code = ch;
                if (code < FIRST_CHAR) code = ' ';
                int idx = code - FIRST_CHAR;
                if (idx >= TEXT_COLS * TEXT_ROWS) idx = '?';
                int col = idx % TEXT_COLS;
                int row = idx / TEXT_COLS;
                int sx = col * SkinLayout.GLYPH_W;
                int sy = row * SkinLayout.GLYPH_H;
                if (sx + SkinLayout.GLYPH_W > skin.text.getWidth()
                        || sy + SkinLayout.GLYPH_H > skin.text.getHeight()) {
                    continue;
                }
                int w = Math.min(SkinLayout.GLYPH_W, (int) (maxWidth - (cursor - x)));
                if (w <= 0) break;
                Rect src = new Rect(sx, sy, sx + w, sy + SkinLayout.GLYPH_H);
                Rect dst = new Rect((int) cursor, (int) y, (int) cursor + w,
                        (int) y + SkinLayout.GLYPH_H);
                c.drawBitmap(skin.text, src, dst, paint);
                cursor += w;
            }
            return cursor - x;
        }

        // Fallback: plain text, scaled down to roughly the same metrics.
        fallback.setTextSize(SkinLayout.GLYPH_H + 3);
        fallback.setColor(paint.getColor());
        fallback.setAlpha(paint.getAlpha());
        c.drawText(s, x, y + SkinLayout.GLYPH_H, fallback);
        return fallback.measureText(s);
    }

    /** Width in pixels that a string will occupy with the 5x6 font. */
    public float textWidth(String s) {
        if (s == null) return 0;
        if (skin.hasTextFont()) return s.length() * (float) SkinLayout.GLYPH_W;
        fallback.setTextSize(SkinLayout.GLYPH_H + 3);
        return fallback.measureText(s);
    }

    /**
     * Draws the mm:ss display. ':' is glyph 11 and '-' is glyph 12 in numbers.bmp;
     * digits 0..9 occupy glyphs 0..9.
     */
    public void drawTime(Canvas c, String time, float x, float y, Paint paint) {
        if (!skin.hasNumberFont()) {
            fallback.setColor(paint.getColor());
            fallback.setTextSize(18);
            fallback.setTypeface(Typeface.create(Typeface.MONOSPACE, Typeface.BOLD));
            c.drawText(time, x, y + SkinLayout.DIGIT_H, fallback);
            return;
        }
        float cursor = x;
        for (int i = 0; i < time.length(); i++) {
            char ch = time.charAt(i);
            int index;
            if (ch >= '0' && ch <= '9') {
                index = ch - '0';
            } else if (ch == ':') {
                index = 11;
            } else if (ch == '-') {
                index = 12;
            } else {
                cursor += SkinLayout.DIGIT_W;
                continue;
            }
            int sx = index * SkinLayout.DIGIT_W;
            if (sx + SkinLayout.DIGIT_W > skin.numbers.getWidth()) {
                cursor += SkinLayout.DIGIT_W;
                continue;
            }
            Rect src = new Rect(sx, 0, sx + SkinLayout.DIGIT_W,
                    Math.min(SkinLayout.DIGIT_H, skin.numbers.getHeight()));
            Rect dst = new Rect((int) cursor, (int) y,
                    (int) cursor + SkinLayout.DIGIT_W, (int) y + SkinLayout.DIGIT_H);
            c.drawBitmap(skin.numbers, src, dst, paint);
            cursor += SkinLayout.DIGIT_W;
        }
    }

    /** Draws a cropped sprite, or nothing when the skin lacks it. */
    public static void sprite(Canvas c, Bitmap src, int sx, int sy, int w, int h,
                              int dx, int dy, Paint paint) {
        if (src == null) return;
        int cw = Math.min(w, src.getWidth() - sx);
        int chh = Math.min(h, src.getHeight() - sy);
        if (cw <= 0 || chh <= 0) return;
        Rect s = new Rect(sx, sy, sx + cw, sy + chh);
        Rect d = new Rect(dx, dy, dx + cw, dy + chh);
        c.drawBitmap(src, s, d, paint);
    }
}
