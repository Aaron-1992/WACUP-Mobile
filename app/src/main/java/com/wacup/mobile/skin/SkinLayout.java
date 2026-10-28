package com.wacup.mobile.skin;

/**
 * Canonical classic-skin geometry, in skin pixels.
 *
 * These are the fixed coordinates every Winamp 2.x skin is painted against, taken
 * from the format's sprite tables (the same ones Webamp and other clones use).
 * Drawing and hit-testing both use this class so they can never disagree.
 */
public final class SkinLayout {

    private SkinLayout() { }

    // ================================================================ main window
    public static final int MAIN_W = 275;
    public static final int MAIN_H = 116;
    public static final int TITLE_H = 14;
    public static final int SHADE_H = 14;

    /** Title bar buttons, 9x9, all at y = 3. */
    public static final int OPTIONS_X = 6;
    public static final int MINIMIZE_X = 244;
    public static final int SHADE_X = 254;
    public static final int CLOSE_X = 264;
    public static final int TITLE_BUTTON_Y = 3;
    public static final int TITLE_BUTTON = 9;

    /** Clutterbar (the O A I D V strip). */
    public static final int CLUTTER_X = 10;
    public static final int CLUTTER_Y = 22;
    public static final int CLUTTER_W = 8;
    public static final int CLUTTER_H = 43;

    /** Scrolling song title, 5x6 glyphs from text.bmp. */
    public static final int MARQUEE_X = 111;
    public static final int MARQUEE_Y = 24;
    public static final int MARQUEE_W = 154;
    public static final int MARQUEE_H = 6;

    /** Time display: four 9x13 digits, a colon slot and a minus sign slot. */
    public static final int TIME_X = 48;
    public static final int TIME_Y = 26;
    public static final int DIGIT_W = 9;
    public static final int DIGIT_H = 13;
    public static final int[] TIME_DIGIT_X = {48, 60, 78, 90};
    public static final int TIME_COLON_X = 69;

    /** Play/pause/stop indicator and the little "working" tick beside it. */
    public static final int PLAYPAUS_X = 26;
    public static final int PLAYPAUS_Y = 28;
    public static final int WORK_X = 24;
    public static final int WORK_Y = 28;
    public static final int WORK_W = 3;
    public static final int WORK_H = 9;

    /** Mono / stereo lights. */
    public static final int STEREO_X = 212;
    public static final int STEREO_Y = 41;
    public static final int STEREO_W = 29;
    public static final int STEREO_H = 12;
    public static final int MONO_X = 239;
    public static final int MONO_W = 27;

    /** Bitrate / sample rate readouts (5x6 font). */
    public static final int KBPS_X = 111;
    public static final int KBPS_Y = 43;
    public static final int KHZ_X = 156;

    /** Spectrum analyser / oscilloscope area. */
    public static final int VIS_X = 24;
    public static final int VIS_Y = 43;
    public static final int VIS_W = 76;
    public static final int VIS_H = 16;

    /** Seek bar: 248x10 background, 29x10 thumb. */
    public static final int POSBAR_X = 16;
    public static final int POSBAR_Y = 72;
    public static final int POSBAR_W = 248;
    public static final int POSBAR_H = 10;
    public static final int POSBAR_THUMB_W = 29;

    /** Volume and balance sliders: 14x11 thumbs riding a 13px trough. */
    public static final int VOLUME_X = 107;
    public static final int VOLUME_Y = 57;
    public static final int VOLUME_W = 68;
    public static final int BALANCE_X = 177;
    public static final int BALANCE_W = 38;
    public static final int SLIDER_H = 13;
    public static final int SLIDER_THUMB_W = 14;
    public static final int SLIDER_THUMB_H = 11;

    /** EQ and PL toggle buttons (from shufrep.bmp, 23x12). */
    public static final int EQ_BUTTON_X = 219;
    public static final int PL_BUTTON_X = 242;
    public static final int WINDOW_BUTTON_Y = 58;
    public static final int WINDOW_BUTTON_W = 23;
    public static final int WINDOW_BUTTON_H = 12;

    /** Transport: five 23x18 buttons (next is 22 wide) plus a 22x16 eject. */
    public static final int CBUTTONS_Y = 88;
    public static final int[] CBUTTONS_X = {16, 39, 62, 85, 108};
    public static final int[] CBUTTONS_W = {23, 23, 23, 23, 22};
    public static final int CBUTTONS_H = 18;
    public static final int EJECT_X = 136;
    public static final int EJECT_Y = 89;
    public static final int EJECT_W = 22;
    public static final int EJECT_H = 16;

    public static final int PREV = 0;
    public static final int PLAY = 1;
    public static final int PAUSE = 2;
    public static final int STOP = 3;
    public static final int NEXT = 4;
    public static final int EJECT = 5;

    /** Shuffle (47x15) and repeat (28x15) side by side. */
    public static final int SHUFFLE_X = 164;
    public static final int SHUFFLE_Y = 89;
    public static final int SHUFFLE_W = 47;
    public static final int REPEAT_X = 210;
    public static final int REPEAT_W = 28;
    public static final int SHUFREP_H = 15;

    // ---- windowshade mode ----
    public static final int[] SHADE_BUTTON_X = {169, 176, 186, 195, 204, 215};
    public static final int[] SHADE_BUTTON_W = {7, 10, 9, 9, 10, 10};
    public static final int SHADE_BUTTON_Y = 2;
    public static final int SHADE_BUTTON_H = 10;
    public static final int SHADE_TIME_X = 127;
    public static final int SHADE_TIME_Y = 4;
    public static final int SHADE_POSBAR_X = 226;
    public static final int SHADE_POSBAR_Y = 4;
    public static final int SHADE_POSBAR_W = 17;
    public static final int SHADE_POSBAR_H = 7;

    // =========================================================== equaliser window
    public static final int EQ_W = 275;
    public static final int EQ_H = 116;
    public static final int EQ_CLOSE_X = 264;
    public static final int EQ_SHADE_X = 254;
    public static final int EQ_ON_X = 14;
    public static final int EQ_AUTO_X = 40;
    public static final int EQ_PRESETS_X = 217;
    public static final int EQ_BUTTON_Y = 18;
    public static final int EQ_ON_W = 26;
    public static final int EQ_AUTO_W = 32;
    public static final int EQ_PRESETS_W = 44;
    public static final int EQ_BUTTON_H = 12;
    public static final int EQ_GRAPH_X = 86;
    public static final int EQ_GRAPH_Y = 17;
    public static final int EQ_GRAPH_W = 113;
    public static final int EQ_GRAPH_H = 19;
    public static final int EQ_PREAMP_X = 21;
    public static final int EQ_BAND_X = 78;
    public static final int EQ_BAND_PITCH = 18;
    public static final int EQ_SLIDER_Y = 38;
    public static final int EQ_SLIDER_W = 14;
    public static final int EQ_SLIDER_H = 63;
    public static final int EQ_THUMB_W = 11;
    public static final int EQ_THUMB_H = 11;

    // ============================================================ playlist window
    public static final int PL_W = 275;
    public static final int PL_TITLE_H = 20;
    public static final int PL_LEFT_W = 12;
    public static final int PL_RIGHT_W = 20;
    public static final int PL_BOTTOM_H = 38;
    public static final int PL_ROW_H = 13;
    public static final int PL_TEXT_PAD_TOP = 3;
    public static final int PL_TEXT_X = 18;
    public static final int PL_SCROLL_W = 8;
    public static final int PL_MIN_ROWS = 3;

    // ---- aliases kept for the built-in skin ----
    public static final int TITLE_HEIGHT = TITLE_H;
    public static final int VOLUME_H = SLIDER_H;
    public static final int BALANCE_Y = VOLUME_Y;
    public static final int BALANCE_H = SLIDER_H;
    public static final int REPEAT_Y = SHUFFLE_Y;
    public static final int SHUFREP_W = SHUFFLE_W;
    public static final int TOGGLE_W = WINDOW_BUTTON_W;
    public static final int TOGGLE_H = WINDOW_BUTTON_H;

    /** Glyph cell size of the bitmap fonts. */
    public static final int GLYPH_W = 5;
    public static final int GLYPH_H = 6;
}
