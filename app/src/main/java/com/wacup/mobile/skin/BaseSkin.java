package com.wacup.mobile.skin;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.Typeface;

/**
 * The built-in skin, painted at runtime so the app is usable before the user has
 * loaded a .wsz. Deliberately drawn in the shape of the classic base skin: dark
 * grey chrome, sunken LCD, green-on-black text.
 *
 * Only the pieces the renderer really needs are generated; anything else falls
 * back to drawn equivalents inside the views.
 */
final class BaseSkin {

    private static final int BG = 0xFF2A2A2A;
    private static final int CHROME_LIGHT = 0xFF565656;
    private static final int CHROME_MID = 0xFF3C3C3C;
    private static final int CHROME_DARK = 0xFF131313;
    private static final int LCD_BG = 0xFF0B100B;

    private BaseSkin() { }

    static Skin create() {
        Skin s = new Skin();
        s.isBase = true;
        s.name = "Base skin (built in)";
        s.main = drawMain();
        s.cbuttons = drawCButtons();
        s.plNormal = 0xFF00F800;
        s.plCurrent = 0xFFFFFFFF;
        s.plNormalBg = 0xFF000000;
        s.plSelectedBg = 0xFF0000A0;
        return s;
    }

    private static Bitmap drawMain() {
        Bitmap bmp = Bitmap.createBitmap(SkinLayout.MAIN_W, SkinLayout.MAIN_H,
                Bitmap.Config.ARGB_8888);
        Canvas c = new Canvas(bmp);
        Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);

        c.drawColor(BG);

        // Window chrome bevel
        p.setStyle(Paint.Style.FILL);
        p.setColor(0xFF1A1A1A);
        c.drawRect(0, 0, SkinLayout.MAIN_W, SkinLayout.MAIN_H, p);
        p.setColor(BG);
        c.drawRect(1, 1, SkinLayout.MAIN_W - 1, SkinLayout.MAIN_H - 1, p);

        // Title bar
        p.setColor(CHROME_MID);
        c.drawRect(1, 1, SkinLayout.MAIN_W - 1, SkinLayout.TITLE_HEIGHT, p);
        p.setColor(CHROME_LIGHT);
        c.drawRect(1, 1, SkinLayout.MAIN_W - 1, 2, p);
        p.setColor(CHROME_DARK);
        c.drawRect(1, SkinLayout.TITLE_HEIGHT - 1, SkinLayout.MAIN_W - 1,
                SkinLayout.TITLE_HEIGHT, p);

        // Sunken LCD panel behind the time digits
        inset(c, 44, 21, 62, 23);

        // Seek track
        inset(c, SkinLayout.POSBAR_X, SkinLayout.POSBAR_Y,
                SkinLayout.POSBAR_W, SkinLayout.POSBAR_H);

        // Volume / balance troughs
        inset(c, SkinLayout.VOLUME_X, SkinLayout.VOLUME_Y,
                SkinLayout.VOLUME_W, SkinLayout.VOLUME_H);
        inset(c, SkinLayout.BALANCE_X, SkinLayout.BALANCE_Y,
                SkinLayout.BALANCE_W, SkinLayout.BALANCE_H);

        // Transport button wells
        for (int i = 0; i < SkinLayout.CBUTTONS_X.length; i++) {
            int x = SkinLayout.CBUTTONS_X[i];
            int w = SkinLayout.CBUTTONS_W[i];
            inset(c, x - 1, SkinLayout.CBUTTONS_Y - 1, w + 2, SkinLayout.CBUTTONS_H + 2);
        }

        // Shuffle / repeat wells
        inset(c, SkinLayout.SHUFFLE_X - 1, SkinLayout.SHUFFLE_Y - 1,
                SkinLayout.SHUFREP_W + 2, SkinLayout.SHUFREP_H + 2);
        inset(c, SkinLayout.REPEAT_X - 1, SkinLayout.REPEAT_Y - 1,
                SkinLayout.SHUFREP_W + 2, SkinLayout.SHUFREP_H + 2);

        return bmp;
    }

    /** Draws a sunken (inward bevel) rectangle — the LCD/trough look. */
    private static void inset(Canvas c, int x, int y, int w, int h) {
        Paint p = new Paint();
        p.setStyle(Paint.Style.FILL);
        p.setColor(CHROME_DARK);
        c.drawRect(x, y, x + w, y + h, p);
        p.setColor(LCD_BG);
        c.drawRect(x + 1, y + 1, x + w - 1, y + h - 1, p);
        p.setColor(0xFF090C09);
        c.drawRect(x + 1, y + 1, x + w - 1, y + 2, p);
    }

    private static Bitmap drawCButtons() {
        Bitmap bmp = Bitmap.createBitmap(136, 36, Bitmap.Config.ARGB_8888);
        Canvas c = new Canvas(bmp);
        String[] glyphs = {"\u23EE", "\u25B6", "\u23F8", "\u23F9", "\u23ED", "\u23CF"};
        int x = 0;
        for (int i = 0; i < glyphs.length; i++) {
            int w = SkinLayout.CBUTTONS_W[i];
            drawButton(c, x, 0, w, SkinLayout.CBUTTONS_H, glyphs[i], false);
            drawButton(c, x, SkinLayout.CBUTTONS_H, w, SkinLayout.CBUTTONS_H, glyphs[i], true);
            x += w;
        }
        return bmp;
    }

    private static void drawButton(Canvas c, int x, int y, int w, int h,
                                   String glyph, boolean pressed) {
        Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
        p.setStyle(Paint.Style.FILL);
        p.setColor(pressed ? 0xFF333333 : 0xFF454545);
        c.drawRect(x + 1, y + 1, x + w - 1, y + h - 1, p);

        p.setColor(pressed ? 0xFF151515 : CHROME_LIGHT);
        c.drawRect(x + 1, y + 1, x + w - 1, y + 2, p);
        c.drawRect(x + 1, y + 1, x + 2, y + h - 1, p);

        p.setColor(CHROME_DARK);
        c.drawRect(x + 1, y + h - 2, x + w - 1, y + h - 1, p);
        c.drawRect(x + w - 2, y + 1, x + w - 1, y + h - 1, p);

        p.setColor(pressed ? 0xFFD0D0D0 : 0xFFE8E8E8);
        p.setTypeface(Typeface.create(Typeface.MONOSPACE, Typeface.BOLD));
        p.setTextSize(h * 0.62f);
        p.setTextAlign(Paint.Align.CENTER);
        Rect bounds = new Rect();
        p.getTextBounds(glyph, 0, glyph.length(), bounds);
        float cy = y + h / 2f - bounds.exactCenterY();
        c.drawText(glyph, x + w / 2f, cy, p);
    }
}
