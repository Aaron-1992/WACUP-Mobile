package com.wacup.mobile.ui;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.view.MotionEvent;

import com.wacup.mobile.MusicEngine;
import com.wacup.mobile.playlist.Track;
import com.wacup.mobile.skin.SkinLayout;
import com.wacup.mobile.skin.SkinPaint;

/**
 * The 275x116 main window.
 *
 * Every element is placed on the classic sprite grid (see SkinLayout), so any
 * Winamp 2.x skin lands where its author intended. Synth fallbacks only kick in
 * when a skin is missing a sheet.
 */
public class MainWindowView extends SkinSurface {

    public static final int TITLE_OPTIONS = 0;
    public static final int TITLE_MINIMIZE = 1;
    public static final int TITLE_SHADE = 2;
    public static final int TITLE_CLOSE = 3;

    public interface Callbacks {
        void onTransport(int button);
        void onSeek(float fraction);
        void onSlider(boolean volume, float fraction);
        void onToggleEqWindow();
        void onTogglePlaylistWindow();
        void onShuffle();
        void onRepeat();
        void onMenu();
        void onTitleButton(int which);
    }

    private final MusicEngine engine;
    private Callbacks callbacks;

    private int pressedButton = -1;          // transport 0..5, 10+shuffle/repeat/eq/pl
    private int pressedTitle = -1;
    private int draggedSlider = -1;          // 0 seek, 1 volume, 2 balance
    private boolean shaded;
    private boolean eqOpen;
    private boolean plOpen;
    private String marquee = "";
    private int marqueeOffset;
    private float balance = 0.5f;

    public MainWindowView(Context context, MusicEngine engine) {
        super(context);
        this.engine = engine;
    }

    public void setCallbacks(Callbacks callbacks) {
        this.callbacks = callbacks;
    }

    public void setShaded(boolean on) {
        this.shaded = on;
        requestLayout();
        invalidate();
    }

    public boolean isShaded() {
        return shaded;
    }

    public void setWindowState(boolean eqOpen, boolean plOpen) {
        this.eqOpen = eqOpen;
        this.plOpen = plOpen;
        invalidate();
    }

    public float balance() {
        return balance;
    }

    /** Called from the activity ticker so the title scrolls like Winamp's. */
    public void tick() {
        Track track = engine.currentTrack();
        String title = track == null ? "" : track.title;
        if (!title.equals(marquee)) {
            marquee = title;
            marqueeOffset = 0;
            invalidate();
            return;
        }
        if (!engine.isPlaying()) return;
        float width = skinPaint.textWidth(title);
        if (width <= SkinLayout.MARQUEE_W) return;
        marqueeOffset++;
        if (marqueeOffset > width + 30) marqueeOffset = 0;
        invalidate();
    }

    @Override
    protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
        int w = (int) Math.ceil(SkinLayout.MAIN_W * scale);
        int h = Math.ceil((shaded ? SkinLayout.SHADE_H : SkinLayout.MAIN_H) * scale);
        setMeasuredDimension(w, h);
    }

    // ------------------------------------------------------------------- draw

    @Override
    protected void onDraw(Canvas canvas) {
        canvas.save();
        canvas.scale(scale, scale);

        if (shaded) {
            drawShade(canvas);
            canvas.restore();
            return;
        }

        drawBackground(canvas, SkinLayout.MAIN_W, SkinLayout.MAIN_H, true);
        drawTitleBar(canvas);
        drawClutterBar(canvas);
        drawMarquee(canvas);
        drawTime(canvas);
        drawIndicators(canvas);
        drawVolumeBalance(canvas);
        drawWindowButtons(canvas);
        drawSeekBar(canvas);
        drawShuffleRepeat(canvas);
        drawTransport(canvas);

        canvas.restore();
    }

    private void drawTitleBar(Canvas c) {
        if (skin.titlebar != null) {
            SkinPaint.sprite(c, skin.titlebar, 27, 0, SkinLayout.MAIN_W,
                    SkinLayout.TITLE_H, 0, 0, plain);
            // options / minimise / shade / close glyphs
            int y = SkinLayout.TITLE_BUTTON_Y;
            SkinPaint.sprite(c, skin.titlebar, 0, 0, 9, 9, SkinLayout.OPTIONS_X, y, plain);
            SkinPaint.sprite(c, skin.titlebar, 9, 0, 9, 9, SkinLayout.MINIMIZE_X, y, plain);
            SkinPaint.sprite(c, skin.titlebar, 0, 18, 9, 9, SkinLayout.SHADE_X, y, plain);
            SkinPaint.sprite(c, skin.titlebar, 18, 0, 9, 9, SkinLayout.CLOSE_X, y, plain);
        } else {
            plain.setColor(0xFF2E2E2E);
            c.drawRect(0, 0, SkinLayout.MAIN_W, SkinLayout.TITLE_H, plain);
            plain.setColor(0xFF4A4A4A);
            c.drawRect(0, 0, SkinLayout.MAIN_W, 1, plain);
        }
    }

    private void drawClutterBar(Canvas c) {
        if (skin.titlebar == null) return;
        SkinPaint.sprite(c, skin.titlebar, 304, 0, SkinLayout.CLUTTER_W,
                SkinLayout.CLUTTER_H, SkinLayout.CLUTTER_X, SkinLayout.CLUTTER_Y, plain);
    }

    private void drawMarquee(Canvas c) {
        Track track = engine.currentTrack();
        String title = track == null ? "WACUP Mobile" : track.title;
        if (title.isEmpty()) return;
        float width = skinPaint.textWidth(title);
        float x = SkinLayout.MARQUEE_X;
        if (width > SkinLayout.MARQUEE_W) {
            x -= marqueeOffset;
        }
        c.save();
        c.clipRect(SkinLayout.MARQUEE_X, SkinLayout.MARQUEE_Y,
                SkinLayout.MARQUEE_X + SkinLayout.MARQUEE_W,
                SkinLayout.MARQUEE_Y + SkinLayout.MARQUEE_H);
        // Colour-keyed text.bmp: tint it with the playlist's "normal" colour, which
        // is what Winamp uses for the marquee.
        int color = skin.plNormal;
        skinPaint.drawText(c, title, x, SkinLayout.MARQUEE_Y, color,
                SkinLayout.MARQUEE_W + (width > SkinLayout.MARQUEE_W ? marqueeOffset : 0));
        c.restore();
    }

    private void drawTime(Canvas c) {
        int timeColor = skin.visColors[Math.min(23, skin.visColors.length - 1)];
        skinPaint.drawTime(c, engine.timeLabel(), timeColor);
    }

    private void drawIndicators(Canvas c) {
        if (skin.playpaus != null) {
            int state = engine.isPlaying() ? 0 : (engine.player().isLoading() ? 1 : 2);
            SkinPaint.sprite(c, skin.playpaus, state * 9, 0, 9, 9,
                    SkinLayout.PLAYPAUS_X, SkinLayout.PLAYPAUS_Y, plain);
        }
        if (skin.monoster != null) {
            // selected row (y=0) is the lit state
            SkinPaint.sprite(c, skin.monoster, 0, 0, SkinLayout.STEREO_W,
                    SkinLayout.STEREO_H, SkinLayout.STEREO_X, SkinLayout.STEREO_Y, plain);
            SkinPaint.sprite(c, skin.monoster, 29, 12, SkinLayout.MONO_W,
                    SkinLayout.STEREO_H, SkinLayout.MONO_X, SkinLayout.STEREO_Y, plain);
        }
        // bitrate / sample rate are only known for some formats; leave blanks
    }

    private void drawVolumeBalance(Canvas c) {
        int volume = engine.volumePercent();

        if (skin.volume != null) {
            SkinPaint.sprite(c, skin.volume, 0, 0, SkinLayout.VOLUME_W,
                    SkinLayout.SLIDER_H, SkinLayout.VOLUME_X, SkinLayout.VOLUME_Y, plain);
        } else {
            trough(c, SkinLayout.VOLUME_X, SkinLayout.VOLUME_Y, SkinLayout.VOLUME_W);
        }
        int volumeTravel = SkinLayout.VOLUME_W - SkinLayout.SLIDER_THUMB_W;
        drawThumb(c, skin.volume, SkinLayout.VOLUME_X + Math.round(volumeTravel * volume / 100f),
                SkinLayout.VOLUME_Y + 1, SLIDER_NORMAL);

        if (skin.balance != null) {
            SkinPaint.sprite(c, skin.balance, 0, 0, SkinLayout.BALANCE_W,
                    SkinLayout.SLIDER_H, SkinLayout.BALANCE_X, SkinLayout.BALANCE_Y, plain);
        } else if (skin.volume != null) {
            // Winamp crops the balance bar out of volume.bmp when balance.bmp is absent
            SkinPaint.sprite(c, skin.volume, 9, 0, SkinLayout.BALANCE_W,
                    SkinLayout.SLIDER_H, SkinLayout.BALANCE_X, SkinLayout.BALANCE_Y, plain);
        } else {
            trough(c, SkinLayout.BALANCE_X, SkinLayout.BALANCE_Y, SkinLayout.BALANCE_W);
        }
        int balanceTravel = SkinLayout.BALANCE_W - SkinLayout.SLIDER_THUMB_W;
        drawThumb(c, skin.balance, SkinLayout.BALANCE_X
                        + Math.round(balanceTravel * (balance - 0.5f) * 2f * 0.5f + balanceTravel * 0.5f),
                SkinLayout.BALANCE_Y + 1, SLIDER_NORMAL);
    }

    private static final int SLIDER_NORMAL = 0;
    private static final int SLIDER_ACTIVE = 1;

    /** 14x11 slider thumb: from the skin atlas when it exists, drawn otherwise. */
    private void drawThumb(Canvas c, android.graphics.Bitmap atlas, int x, int y, int state) {
        if (atlas != null) {
            int atlasX = state == SLIDER_ACTIVE ? 0 : 15;
            int atlasY = 422;
            if (atlasY + SkinLayout.SLIDER_THUMB_H <= atlas.getHeight()) {
                SkinPaint.sprite(c, atlas, atlasX, atlasY, SkinLayout.SLIDER_THUMB_W,
                        SkinLayout.SLIDER_THUMB_H, x, y, plain);
                return;
            }
        }
        plain.setColor(0xFFC8C8C8);
        c.drawRect(x, y, x + SkinLayout.SLIDER_THUMB_W, y + SkinLayout.SLIDER_THUMB_H, plain);
        plain.setColor(0xFF5C5C5C);
        c.drawRect(x, y, x + SkinLayout.SLIDER_THUMB_W, y + 1, plain);
        c.drawRect(x, y + SkinLayout.SLIDER_THUMB_H - 1, x + SkinLayout.SLIDER_THUMB_W,
                y + SkinLayout.SLIDER_THUMB_H, plain);
        plain.setColor(0xFF303030);
        c.drawRect(x + 6, y + 2, x + 8, y + SkinLayout.SLIDER_THUMB_H - 2, plain);
    }

    private void trough(Canvas c, int x, int y, int w) {
        plain.setColor(0xFF101010);
        c.drawRect(x, y, x + w, y + SkinLayout.SLIDER_H, plain);
        plain.setColor(0xFF2A2A2A);
        c.drawRect(x + 1, y + 1, x + w - 1, y + 2, plain);
    }

    private void drawWindowButtons(Canvas c) {
        if (skin.shufrep == null) return;
        SkinPaint.sprite(c, skin.shufrep, 0, eqOpen ? 73 : 61, SkinLayout.WINDOW_BUTTON_W,
                SkinLayout.WINDOW_BUTTON_H, SkinLayout.EQ_BUTTON_X, SkinLayout.WINDOW_BUTTON_Y, plain);
        SkinPaint.sprite(c, skin.shufrep, 23, plOpen ? 73 : 61, SkinLayout.WINDOW_BUTTON_W,
                SkinLayout.WINDOW_BUTTON_H, SkinLayout.PL_BUTTON_X, SkinLayout.WINDOW_BUTTON_Y, plain);
    }

    private void drawSeekBar(Canvas c) {
        if (skin.posbar != null) {
            SkinPaint.sprite(c, skin.posbar, 0, 0, SkinLayout.POSBAR_W,
                    SkinLayout.POSBAR_H, SkinLayout.POSBAR_X, SkinLayout.POSBAR_Y, plain);
        } else {
            trough(c, SkinLayout.POSBAR_X, SkinLayout.POSBAR_Y, SkinLayout.POSBAR_W);
        }
        float fraction = engine.positionFraction();
        int travel = SkinLayout.POSBAR_W - SkinLayout.POSBAR_THUMB_W;
        int x = SkinLayout.POSBAR_X + Math.round(travel * fraction);
        boolean pressed = draggedSlider == 0;
        if (skin.posbar != null && skin.posbar.getWidth() >= 307) {
            int srcX = pressed ? 278 : 248;
            SkinPaint.sprite(c, skin.posbar, srcX, 0, SkinLayout.POSBAR_THUMB_W,
                    SkinLayout.POSBAR_H, x, SkinLayout.POSBAR_Y, plain);
        } else {
            plain.setColor(0xFFD0D0D0);
            c.drawRect(x, SkinLayout.POSBAR_Y, x + SkinLayout.POSBAR_THUMB_W,
                    SkinLayout.POSBAR_Y + SkinLayout.POSBAR_H, plain);
        }
    }

    private void drawShuffleRepeat(Canvas c) {
        if (skin.shufrep == null) return;

        int shuffleRow = engine.shuffle() ? 30 : 0;
        if (pressedButton == 10) shuffleRow += 15;
        SkinPaint.sprite(c, skin.shufrep, 28, shuffleRow, SkinLayout.SHUFFLE_W,
                SkinLayout.SHUFREP_H, SkinLayout.SHUFFLE_X, SkinLayout.SHUFFLE_Y, plain);

        int repeatRow = engine.repeatMode() == 0 ? 0 : 30;
        if (pressedButton == 11) repeatRow += 15;
        SkinPaint.sprite(c, skin.shufrep, 0, repeatRow, SkinLayout.REPEAT_W,
                SkinLayout.SHUFREP_H, SkinLayout.REPEAT_X, SkinLayout.SHUFFLE_Y, plain);
    }

    private void drawTransport(Canvas c) {
        for (int i = 0; i < SkinLayout.CBUTTONS_X.length; i++) {
            int x = SkinLayout.CBUTTONS_X[i];
            int w = SkinLayout.CBUTTONS_W[i];
            int row = pressedButton == i ? 18 : 0;
            if (skin.cbuttons != null) {
                SkinPaint.sprite(c, skin.cbuttons, x, row, w, SkinLayout.CBUTTONS_H,
                        x, SkinLayout.CBUTTONS_Y, plain);
            } else {
                plain.setColor(pressedButton == i ? 0xFF303030 : 0xFF4C4C4C);
                c.drawRect(x + 1, SkinLayout.CBUTTONS_Y + 1, x + w - 1,
                        SkinLayout.CBUTTONS_Y + SkinLayout.CBUTTONS_H - 1, plain);
            }
        }
        int row = pressedButton == SkinLayout.EJECT ? SkinLayout.EJECT_H : 0;
        if (skin.cbuttons != null) {
            SkinPaint.sprite(c, skin.cbuttons, 114, row, SkinLayout.EJECT_W,
                    SkinLayout.EJECT_H, SkinLayout.EJECT_X, SkinLayout.EJECT_Y, plain);
        }
    }

    // ------------------------------------------------------------ windowshade

    private void drawShade(Canvas c) {
        plain.setColor(0xFF2E2E2E);
        c.drawRect(0, 0, SkinLayout.MAIN_W, SkinLayout.SHADE_H, plain);

        if (skin.titlebar != null) {
            int row = 29;   // active windowshade bar
            if (skin.titlebar.getHeight() < row + SkinLayout.SHADE_H) row = 0;
            SkinPaint.sprite(c, skin.titlebar, 27, row, SkinLayout.MAIN_W,
                    SkinLayout.SHADE_H, 0, 0, plain);
            SkinPaint.sprite(c, skin.titlebar, 0, 18, 9, 9, SkinLayout.SHADE_X,
                    SkinLayout.TITLE_BUTTON_Y, plain);
            SkinPaint.sprite(c, skin.titlebar, 18, 0, 9, 9, SkinLayout.CLOSE_X,
                    SkinLayout.TITLE_BUTTON_Y, plain);
        }

        // transport buttons, squeezed into the bar
        for (int i = 0; i < SkinLayout.SHADE_BUTTON_X.length; i++) {
            int x = SkinLayout.SHADE_BUTTON_X[i];
            int w = SkinLayout.SHADE_BUTTON_W[i];
            if (skin.cbuttons == null) continue;
            int srcX = i < 5 ? SkinLayout.CBUTTONS_X[i] : 114;
            int srcW = i < 5 ? SkinLayout.CBUTTONS_W[i] : SkinLayout.EJECT_W;
            int srcY = i < 5 ? (pressedButton == i ? 18 : 0)
                    : (pressedButton == SkinLayout.EJECT ? SkinLayout.EJECT_H : 0);
            int srcH = i < 5 ? SkinLayout.CBUTTONS_H : SkinLayout.EJECT_H;
            c.save();
            c.clipRect(x, SkinLayout.SHADE_BUTTON_Y, x + w,
                    SkinLayout.SHADE_BUTTON_Y + SkinLayout.SHADE_BUTTON_H);
            SkinPaint.sprite(c, skin.cbuttons, srcX, srcY, srcW, srcH, x,
                    SkinLayout.SHADE_BUTTON_Y - 1, plain);
            c.restore();
        }

        skinPaint.drawText(c, engine.timeLabel(), SkinLayout.SHADE_TIME_X,
                SkinLayout.SHADE_TIME_Y, skin.plNormal, 60);

        // compact seek bar
        if (skin.posbar != null) {
            SkinPaint.sprite(c, skin.posbar, 0, 0, SkinLayout.SHADE_POSBAR_W,
                    SkinLayout.SHADE_POSBAR_H, SkinLayout.SHADE_POSBAR_X,
                    SkinLayout.SHADE_POSBAR_Y, plain);
        }
        int travel = SkinLayout.SHADE_POSBAR_W - 3;
        int thumbX = SkinLayout.SHADE_POSBAR_X + Math.round(travel * engine.positionFraction());
        plain.setColor(0xFFE0E0E0);
        c.drawRect(thumbX, SkinLayout.SHADE_POSBAR_Y, thumbX + 3,
                SkinLayout.SHADE_POSBAR_Y + SkinLayout.SHADE_POSBAR_H, plain);
    }

    // ------------------------------------------------------------------ input

    /** True when a down event lands on one of the title bar buttons. */
    public boolean isTitleButton(float skinX, float skinY) {
        if (skinY > SkinLayout.TITLE_H) return false;
        return near(skinX, SkinLayout.OPTIONS_X) || near(skinX, SkinLayout.MINIMIZE_X)
                || near(skinX, SkinLayout.SHADE_X) || near(skinX, SkinLayout.CLOSE_X);
    }

    private boolean near(float x, int buttonX) {
        return x >= buttonX - 2 && x <= buttonX + SkinLayout.TITLE_BUTTON + 2;
    }

    @Override
    public boolean onTouchEvent(MotionEvent event) {
        float x = event.getX() / scale;
        float y = event.getY() / scale;
        float maxY = shaded ? SkinLayout.SHADE_H : SkinLayout.MAIN_H;
        if (y > maxY) y = maxY;

        switch (event.getActionMasked()) {
            case MotionEvent.ACTION_DOWN:
                pressedTitle = titleButtonAt(x, y);
                if (pressedTitle >= 0) {
                    invalidate();
                    return true;
                }
                if (shaded) {
                    pressedButton = shadeButtonAt(x, y);
                    if (pressedButton < 0 && inside(x, y, SkinLayout.SHADE_POSBAR_X,
                            SkinLayout.SHADE_POSBAR_Y, SkinLayout.SHADE_POSBAR_W,
                            SkinLayout.SHADE_POSBAR_H)) {
                        draggedSlider = 0;
                        seekFraction((x - SkinLayout.SHADE_POSBAR_X) / SkinLayout.SHADE_POSBAR_W);
                    }
                    invalidate();
                    return true;
                }

                pressedButton = transportAt(x, y);
                if (pressedButton >= 0) {
                    invalidate();
                    return true;
                }
                if (inside(x, y, SkinLayout.POSBAR_X, SkinLayout.POSBAR_Y,
                        SkinLayout.POSBAR_W, SkinLayout.POSBAR_H)) {
                    draggedSlider = 0;
                    seekFraction((x - SkinLayout.POSBAR_X) / SkinLayout.POSBAR_W);
                    return true;
                }
                if (inside(x, y, SkinLayout.VOLUME_X, SkinLayout.VOLUME_Y,
                        SkinLayout.VOLUME_W, SkinLayout.SLIDER_H)) {
                    draggedSlider = 1;
                    volumeFraction((x - SkinLayout.VOLUME_X) / SkinLayout.VOLUME_W);
                    return true;
                }
                if (inside(x, y, SkinLayout.BALANCE_X, SkinLayout.BALANCE_Y,
                        SkinLayout.BALANCE_W, SkinLayout.SLIDER_H)) {
                    draggedSlider = 2;
                    balanceFraction((x - SkinLayout.BALANCE_X) / SkinLayout.BALANCE_W);
                    return true;
                }
                return true;

            case MotionEvent.ACTION_MOVE:
                if (draggedSlider == 0) {
                    float fraction = shaded
                            ? (x - SkinLayout.SHADE_POSBAR_X) / SkinLayout.SHADE_POSBAR_W
                            : (x - SkinLayout.POSBAR_X) / SkinLayout.POSBAR_W;
                    seekFraction(fraction);
                    return true;
                }
                if (draggedSlider == 1) {
                    volumeFraction((x - SkinLayout.VOLUME_X) / SkinLayout.VOLUME_W);
                    return true;
                }
                if (draggedSlider == 2) {
                    balanceFraction((x - SkinLayout.BALANCE_X) / SkinLayout.BALANCE_W);
                    return true;
                }
                return true;

            case MotionEvent.ACTION_UP:
                if (pressedTitle >= 0) {
                    int which = pressedTitle;
                    pressedTitle = -1;
                    if (callbacks != null && titleButtonAt(x, y) == which) {
                        callbacks.onTitleButton(which);
                    }
                    invalidate();
                    return true;
                }
                if (draggedSlider >= 0) {
                    draggedSlider = -1;
                    invalidate();
                    return true;
                }
                if (pressedButton >= 0) {
                    int button = pressedButton;
                    pressedButton = -1;
                    invalidate();
                    if (shaded) {
                        dispatchTransport(button);
                        return true;
                    }
                    dispatchTransport(button);
                    return true;
                }
                if (tapButtons(x, y)) return true;
                return true;

            case MotionEvent.ACTION_CANCEL:
                pressedButton = -1;
                pressedTitle = -1;
                draggedSlider = -1;
                invalidate();
                return true;

            default:
                return super.onTouchEvent(event);
        }
    }

    /** Taps on shuffle / repeat / eq / playlist, resolved on release. */
    private boolean tapButtons(float x, float y) {
        if (callbacks == null) return false;
        if (inside(x, y, SkinLayout.SHUFFLE_X, SkinLayout.SHUFFLE_Y,
                SkinLayout.SHUFFLE_W, SkinLayout.SHUFREP_H)) {
            callbacks.onShuffle();
            return true;
        }
        if (inside(x, y, SkinLayout.REPEAT_X, SkinLayout.SHUFFLE_Y,
                SkinLayout.REPEAT_W, SkinLayout.SHUFREP_H)) {
            callbacks.onRepeat();
            return true;
        }
        if (inside(x, y, SkinLayout.EQ_BUTTON_X, SkinLayout.WINDOW_BUTTON_Y,
                SkinLayout.WINDOW_BUTTON_W, SkinLayout.WINDOW_BUTTON_H)) {
            callbacks.onToggleEqWindow();
            return true;
        }
        if (inside(x, y, SkinLayout.PL_BUTTON_X, SkinLayout.WINDOW_BUTTON_Y,
                SkinLayout.WINDOW_BUTTON_W, SkinLayout.WINDOW_BUTTON_H)) {
            callbacks.onTogglePlaylistWindow();
            return true;
        }
        return false;
    }

    private void dispatchTransport(int button) {
        if (callbacks == null) return;
        callbacks.onTransport(button);
    }

    private int titleButtonAt(float x, float y) {
        if (y > SkinLayout.TITLE_H) return -1;
        if (near(x, SkinLayout.OPTIONS_X)) return TITLE_OPTIONS;
        if (near(x, SkinLayout.MINIMIZE_X)) return TITLE_MINIMIZE;
        if (near(x, SkinLayout.SHADE_X)) return TITLE_SHADE;
        if (near(x, SkinLayout.CLOSE_X)) return TITLE_CLOSE;
        return -1;
    }

    private int transportAt(float x, float y) {
        int[] xs = shaded ? SkinLayout.SHADE_BUTTON_X : append(SkinLayout.CBUTTONS_X,
                SkinLayout.EJECT_X);
        int[] ws = shaded ? SkinLayout.SHADE_BUTTON_W : append(SkinLayout.CBUTTONS_W,
                SkinLayout.EJECT_W);
        float ty = shaded ? SkinLayout.SHADE_BUTTON_Y : SkinLayout.CBUTTONS_Y;
        float th = shaded ? SkinLayout.SHADE_BUTTON_H : SkinLayout.CBUTTONS_H;
        if (y < ty - 4 || y > ty + th + 4) return -1;
        for (int i = 0; i < xs.length; i++) {
            if (x >= xs[i] - 2 && x <= xs[i] + ws[i] + 2) {
                return i == 5 ? SkinLayout.EJECT : i;
            }
        }
        return -1;
    }

    private static int[] append(int[] values, int extra) {
        int[] out = new int[values.length + 1];
        System.arraycopy(values, 0, out, 0, values.length);
        out[values.length] = extra;
        return out;
    }

    private int shadeButtonAt(float x, float y) {
        for (int i = 0; i < SkinLayout.SHADE_BUTTON_X.length; i++) {
            if (inside(x, y, SkinLayout.SHADE_BUTTON_X[i] - 1, SkinLayout.SHADE_BUTTON_Y - 2,
                    SkinLayout.SHADE_BUTTON_W[i] + 2, SkinLayout.SHADE_BUTTON_H + 4)) {
                return i == 5 ? SkinLayout.EJECT : i;
            }
        }
        return -1;
    }

    private boolean inside(float x, float y, int rx, int ry, int rw, int rh) {
        return x >= rx && x <= rx + rw && y >= ry && y <= ry + rh;
    }

    private void seekFraction(float fraction) {
        if (callbacks != null) callbacks.onSeek(clamp(fraction));
    }

    private void volumeFraction(float fraction) {
        if (callbacks != null) callbacks.onSlider(true, clamp(fraction));
    }

    private void balanceFraction(float fraction) {
        balance = clamp(fraction);
        invalidate();
    }

    private static float clamp(float v) {
        return v < 0f ? 0f : (v > 1f ? 1f : v);
    }
}
