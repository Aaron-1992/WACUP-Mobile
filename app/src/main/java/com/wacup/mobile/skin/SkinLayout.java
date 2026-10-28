package com.wacup.mobile.skin;

/**
 * Coordinates of the classic Winamp 2.x window layout, in skin pixels.
 *
 * These are fixed by the skin format: every classic skin paints on the same
 * 275x116 grid, so one table serves all skins. Entries marked "approx" are the
 * ones whose artwork offsets differ slightly between skin packs and may need a
 * nudge after seeing a screenshot.
 */
public final class SkinLayout {

    private SkinLayout() { }

    public static final int MAIN_W = 275;
    public static final int MAIN_H = 116;

    public static final int PL_W = 275;
    public static final int EQ_W = 275;
    public static final int EQ_H = 116;
    public static final int PLEDIT_H = 116;

    // ---- main window ----
    public static final int TITLE_HEIGHT = 14;

    /** Transport buttons: 23x18 each (eject is 22x18), drawn from cbuttons.bmp. */
    public static final int CBUTTONS_Y = 88;
    public static final int[] CBUTTONS_X = {16, 39, 62, 85, 108, 136};
    public static final int[] CBUTTONS_W = {23, 23, 23, 23, 23, 22};
    public static final int CBUTTONS_H = 18;

    /** Position (seek) bar: 248x10 background, 29x10 thumb. */
    public static final int POSBAR_X = 16;
    public static final int POSBAR_Y = 72;
    public static final int POSBAR_W = 248;
    public static final int POSBAR_H = 10;
    public static final int POSBAR_THUMB_W = 29;

    /** Volume slider: 68x13. */
    public static final int VOLUME_X = 107;
    public static final int VOLUME_Y = 57;
    public static final int VOLUME_W = 68;
    public static final int VOLUME_H = 13;

    /** Balance slider: 38x13. */
    public static final int BALANCE_X = 177;
    public static final int BALANCE_Y = 57;
    public static final int BALANCE_W = 38;
    public static final int BALANCE_H = 13;

    /** Shuffle (47x15) and repeat (47x15) from shufrep.bmp. */
    public static final int SHUFFLE_X = 164;
    public static final int SHUFFLE_Y = 89;
    public static final int REPEAT_X = 210;
    public static final int REPEAT_Y = 89;
    public static final int SHUFREP_W = 47;
    public static final int SHUFREP_H = 15;

    /** Time display: "88:88" using 9x13 digits from numbers.bmp. */
    public static final int TIME_X = 48;
    public static final int TIME_Y = 26;
    public static final int DIGIT_W = 9;
    public static final int DIGIT_H = 13;

    /** Scrolling track title, 5x6 glyphs from text.bmp. */
    public static final int TITLE_TEXT_X = 113;
    public static final int TITLE_TEXT_Y = 27;
    public static final int TITLE_TEXT_W = 152;
    public static final int GLYPH_W = 5;
    public static final int GLYPH_H = 6;

    /** Play/pause/stop indicator (playpaus.bmp), 9x9 states. */
    public static final int PLAYPAUS_X = 26;
    public static final int PLAYPAUS_Y = 27;

    /** Mono/stereo indicators (monoster.bmp), 28x12 each. */
    public static final int STEREO_X = 212;
    public static final int STEREO_Y = 41;
    public static final int MONO_X = 239;
    public static final int MONO_Y = 41;

    /** EQ and PL toggles from shufrep.bmp at y=61 (off) / y=73 (on). */
    public static final int EQ_BUTTON_X = 5;
    public static final int EQ_BUTTON_Y = 57;
    public static final int PL_BUTTON_X = 5;
    public static final int PL_BUTTON_Y = 72;
    public static final int TOGGLE_W = 23;
    public static final int TOGGLE_H = 12;

    // ---- playlist window ----
    public static final int PL_TITLEBAR_H = 20;
    public static final int PL_LEFT_W = 12;
    public static final int PL_RIGHT_W = 20;
    public static final int PL_BOTTOM_H = 38;
    public static final int PL_ROW_H = 12;          // one playlist line
    public static final int PL_TEXT_X = 12;         // text inset from window edge
    public static final int PL_SCROLL_W = 8;

    // ---- equaliser window ----
    public static final int EQ_SLIDER_TOP = 38;
    public static final int EQ_SLIDER_H = 63;
    public static final int EQ_BAND_W = 14;
    public static final int EQ_BAND_X = 78;         // left edge of first band column
    public static final int EQ_BAND_GAP = 18;
    public static final int EQ_PREAMP_X = 21;
    public static final int EQ_SLIDER_THUMB_H = 11;
    public static final int EQ_SLIDER_THUMB_W = 11;
}
