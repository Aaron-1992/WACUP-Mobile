package com.wacup.mobile.ui;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Rect;
import android.view.MotionEvent;
import android.view.View;

import androidx.annotation.Nullable;

import com.wacup.mobile.MusicEngine;
import com.wacup.mobile.playlist.Track;
import com.wacup.mobile.skin.SkinLayout;
import com.wacup.mobile.skin.SkinPaint;

/**
 * The 275x116 main window, drawn entirely from the loaded skin.
 *
 * Touch targets follow the classic layout, but they are enlarged for fingers: the
 * hit test runs in skin coordinates and neighbouring controls stay reachable.
 */
public class MainWindowView extends SkinSurface {

    public interface Callbacks {
        void onTransport(int button);      // 0 prev, 1 play, 2 pause, 3 stop, 4 next, 5 eject
        void onSeek(float fraction);
        void onVolume(int percent);
        void onToggleEq();
        void onTogglePlaylist();
        void onShuffle();
        void onRepeat();
        void onMenu();
    }

    private static final int BUTTON_COUNT = 6;

    private final MusicEngine engine;
    private Callbacks callbacks;

    private int pressedButton = -1;
    private boolean draggingSeek;
    private boolean draggingVolume;
    private String scrollTitle = "";
    private int titleScrollPx;

    public MainWindowView(Context context, MusicEngine engine) {
        super(context);
        this.engine = engine;
        setFocusable(true);
    }

    public void setCallbacks(Callbacks callbacks) {
        this.callbacks = callbacks;
    }

    @Override
    protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
        int w = (int) Math.ceil(SkinLayout.MAIN_W * scale);
        int h = (int) Math.ceil(SkinLayout.MAIN_H * scale);
        setMeasuredDimension(w, h);
    }

    /** Called by the activity's animation ticker so the title can scroll. */
    public void tick() {
        if (!engine.isPlaying()) return;
        Track track = engine.currentTrack();
        String title = track == null ? "" : track.title;
        if (!title.equals(scrollTitle)) {
            scrollTitle = title;
            titleScrollPx = 0;
            return;
        }
        if (skinPaint.textWidth(title) > SkinLayout.TITLE_TEXT_W) {
            titleScrollPx += 1;
            if (titleScrollPx > skinPaint.textWidth(title) + 24) titleScrollPx = 0;
            invalidate();
        }
    }

    @Override
    protected void onDraw(Canvas canvas) {
        canvas.save();
        canvas.scale(scale, scale);
        drawBackground(canvas, SkinLayout.MAIN_W, SkinLayout.MAIN_H, true);

        drawTitle(canvas);
        drawTime(canvas);
        drawSeek(canvas);
        drawVolume(canvas);
        drawShuffleRepeat(canvas);
        drawTransport(canvas);
        drawStateIndicators(canvas);

        canvas.restore();
    }

    private void drawTitle(Canvas canvas) {
        Track track = engine.currentTrack();
        String title = track == null ? "WACUP Mobile" : track.title;
        canvas.save();
        canvas.clipRect(SkinLayout.TITLE_TEXT_X, SkinLayout.TITLE_TEXT_Y,
                SkinLayout.TITLE_TEXT_X + SkinLayout.TITLE_TEXT_W,
                SkinLayout.TITLE_TEXT_Y + SkinLayout.GLYPH_H);
        float x = SkinLayout.TITLE_TEXT_X - titleScrollPx;
        float w = skinPaint.textWidth(title) + 12;
        if (w < SkinLayout.TITLE_TEXT_W) x = SkinLayout.TITLE_TEXT_X;
        green.setColor(skin.isBase ? 0xFF00F800 : skin.plNormal);
        green.setAlpha(0xFF);
        skinPaint.drawText(canvas, title, x, SkinLayout.TITLE_TEXT_Y, green,
                SkinLayout.TITLE_TEXT_W * 4);
        canvas.restore();
    }

    private void drawTime(Canvas canvas) {
        green.setColor(skin.isBase ? 0xFF00F800 : skin.visColors[Math.min(23, skin.visColors.length - 1)]);
        skinPaint.drawTime(canvas, engine.timeLabel(), SkinLayout.TIME_X,
                SkinLayout.TIME_Y, green);
    }

    private void drawSeek(Canvas canvas) {
        // Track background
        if (skin.posbar != null) {
            SkinPaint.sprite(canvas, skin.posbar, 0, 0,
                    SkinLayout.POSBAR_W, SkinLayout.POSBAR_H,
                    SkinLayout.POSBAR_X, SkinLayout.POSBAR_Y, plain);
        } else {
            plain.setColor(0xFF0B100B);
            canvas.drawRect(SkinLayout.POSBAR_X, SkinLayout.POSBAR_Y,
                    SkinLayout.POSBAR_X + SkinLayout.POSBAR_W,
                    SkinLayout.POSBAR_Y + SkinLayout.POSBAR_H, plain);
        }

        float fraction = engine.positionFraction();
        int travel = SkinLayout.POSBAR_W - SkinLayout.POSBAR_THUMB_W;
        int thumbX = SkinLayout.POSBAR_X + (int) (travel * fraction);

        if (skin.posbar != null && skin.posbar.getHeight() >= 20) {
            SkinPaint.sprite(canvas, skin.posbar, 0, 10,
                    SkinLayout.POSBAR_THUMB_W, SkinLayout.POSBAR_H,
                    thumbX, SkinLayout.POSBAR_Y, plain);
        } else {
            plain.setColor(0xFF00F800);
            canvas.drawRect(thumbX, SkinLayout.POSBAR_Y, thumbX + 6,
                    SkinLayout.POSBAR_Y + SkinLayout.POSBAR_H, plain);
        }
    }

    private void drawVolume(Canvas canvas) {
        int volume = engine.volumePercent();
        if (skin.volume != null) {
            SkinPaint.sprite(canvas, skin.volume, 0, 0,
                    SkinLayout.VOLUME_W, SkinLayout.VOLUME_H,
                    SkinLayout.VOLUME_X, SkinLayout.VOLUME_Y, plain);
            int thumbW = 14;
            int travel = SkinLayout.VOLUME_W - thumbW;
            int x = SkinLayout.VOLUME_X + (int) (travel * volume / 100f);
            SkinPaint.sprite(canvas, skin.volume, 0, 0, thumbW,
                    SkinLayout.VOLUME_H, x, SkinLayout.VOLUME_Y, plain);
        } else {
            plain.setColor(0xFF0B100B);
            canvas.drawRect(SkinLayout.VOLUME_X, SkinLayout.VOLUME_Y,
                    SkinLayout.VOLUME_X + SkinLayout.VOLUME_W,
                    SkinLayout.VOLUME_Y + SkinLayout.VOLUME_H, plain);
            plain.setColor(0xFF00F800);
            int filled = (int) (SkinLayout.VOLUME_W * volume / 100f);
            canvas.drawRect(SkinLayout.VOLUME_X, SkinLayout.VOLUME_Y,
                    SkinLayout.VOLUME_X + filled,
                    SkinLayout.VOLUME_Y + SkinLayout.VOLUME_H, plain);
        }
    }

    private void drawShuffleRepeat(Canvas canvas) {
        if (skin.shufrep == null) {
            drawToggleText(canvas, SkinLayout.SHUFFLE_X, SkinLayout.SHUFFLE_Y,
                    "SHUF " + (engine.shuffle() ? "ON" : "OFF"), engine.shuffle());
            drawToggleText(canvas, SkinLayout.REPEAT_X, SkinLayout.REPEAT_Y,
                    engine.repeatLabel(), engine.repeatMode() != 0);
            return;
        }
        // shufrep.bmp: shuffle off at (28,0) / on at (28,15); repeat off (0,0) / on (0,30)
        SkinPaint.sprite(canvas, skin.shufrep, 28, engine.shuffle() ? 15 : 0,
                SkinLayout.SHUFREP_W, SkinLayout.SHUFREP_H,
                SkinLayout.SHUFFLE_X, SkinLayout.SHUFFLE_Y, plain);
        int repeatRow = engine.repeatMode() == 0 ? 0
                : (engine.repeatMode() == 1 ? 30 : 45);
        SkinPaint.sprite(canvas, skin.shufrep, 0, repeatRow,
                SkinLayout.SHUFREP_W, SkinLayout.SHUFREP_H,
                SkinLayout.REPEAT_X, SkinLayout.REPEAT_Y, plain);
    }

    private void drawToggleText(Canvas canvas, int x, int y, String label, boolean on) {
        plain.setColor(on ? 0xFF00F800 : 0xFF00A000);
        canvas.drawRect(x, y, x + SkinLayout.SHUFREP_W, y + SkinLayout.SHUFREP_H, plain);
        green.setColor(0xFF000000);
        skinPaint.drawText(canvas, label, x + 2, y + 4, green, SkinLayout.SHUFREP_W - 4);
    }

    private void drawTransport(Canvas canvas) {
        int[] rows = {0, 18};   // normal, pressed
        for (int i = 0; i < BUTTON_COUNT; i++) {
            int x = SkinLayout.CBUTTONS_X[i];
            int w = SkinLayout.CBUTTONS_W[i];
            int rowY = (pressedButton == i) ? rows[1] : rows[0];
            if (skin.cbuttons != null) {
                SkinPaint.sprite(canvas, skin.cbuttons, x, rowY, w,
                        SkinLayout.CBUTTONS_H, x, SkinLayout.CBUTTONS_Y, plain);
            } else {
                plain.setColor(pressedButton == i ? 0xFF333333 : 0xFF454545);
                canvas.drawRect(x + 1, SkinLayout.CBUTTONS_Y + 1, x + w - 1,
                        SkinLayout.CBUTTONS_Y + SkinLayout.CBUTTONS_H - 1, plain);
                green.setColor(0xFFE8E8E8);
                String glyph;
                switch (i) {
                    case 0: glyph = "|<"; break;
                    case 1: glyph = ">"; break;
                    case 2: glyph = "||"; break;
                    case 3: glyph = "[]"; break;
                    case 4: glyph = ">|"; break;
                    default: glyph = "^"; break;
                }
                skinPaint.drawText(canvas, glyph, x + 3, SkinLayout.CBUTTONS_Y + 6,
                        green, w - 6);
            }
        }
    }

    private void drawStateIndicators(Canvas canvas) {
        if (skin.playpaus != null) {
            int state = engine.isPlaying() ? 0 : 2;   // 0 play, 1 pause, 2 stop
            SkinPaint.sprite(canvas, skin.playpaus, state * 9, 0, 9, 9,
                    SkinLayout.PLAYPAUS_X, SkinLayout.PLAYPAUS_Y, plain);
        }
        if (skin.monoster != null) {
            SkinPaint.sprite(canvas, skin.monoster, 28, 0, 27, 12,
                    SkinLayout.STEREO_X, SkinLayout.STEREO_Y, plain);
            SkinPaint.sprite(canvas, skin.monoster, 0, 12, 27, 12,
                    SkinLayout.MONO_X, SkinLayout.MONO_Y, plain);
        }
    }

    // ------------------------------------------------------------------ input

    @Override
    public boolean onTouchEvent(MotionEvent event) {
        float x = event.getX() / scale;
        float y = event.getY() / scale;

        switch (event.getActionMasked()) {
            case MotionEvent.ACTION_DOWN:
                if (insideButton(x, y) >= 0) {
                    pressedButton = insideButton(x, y);
                    invalidate();
                    return true;
                }
                if (insideRect(x, y, SkinLayout.POSBAR_X, SkinLayout.POSBAR_Y,
                        SkinLayout.POSBAR_W, SkinLayout.POSBAR_H)) {
                    draggingSeek = true;
                    seekTo(x);
                    return true;
                }
                if (insideRect(x, y, SkinLayout.VOLUME_X, SkinLayout.VOLUME_Y,
                        SkinLayout.VOLUME_W, SkinLayout.VOLUME_H)) {
                    draggingVolume = true;
                    setVolume(x);
                    return true;
                }
                return true;

            case MotionEvent.ACTION_MOVE:
                if (draggingSeek) {
                    seekTo(x);
                    return true;
                }
                if (draggingVolume) {
                    setVolume(x);
                    return true;
                }
                return true;

            case MotionEvent.ACTION_UP:
                if (pressedButton >= 0) {
                    int button = pressedButton;
                    pressedButton = -1;
                    invalidate();
                    dispatchButton(button, x, y);
                    return true;
                }
                if (draggingSeek || draggingVolume) {
                    draggingSeek = false;
                    draggingVolume = false;
                    return true;
                }
                if (insideRect(x, y, SkinLayout.EQ_BUTTON_X, SkinLayout.EQ_BUTTON_Y,
                        SkinLayout.TOGGLE_W, SkinLayout.TOGGLE_H)) {
                    if (callbacks != null) callbacks.onToggleEq();
                    return true;
                }
                if (insideRect(x, y, SkinLayout.PL_BUTTON_X, SkinLayout.PL_BUTTON_Y,
                        SkinLayout.TOGGLE_W, SkinLayout.TOGGLE_H)) {
                    if (callbacks != null) callbacks.onTogglePlaylist();
                    return true;
                }
                if (insideRect(x, y, SkinLayout.SHUFFLE_X, SkinLayout.SHUFFLE_Y,
                        SkinLayout.SHUFREP_W, SkinLayout.SHUFREP_H)) {
                    if (callbacks != null) callbacks.onShuffle();
                    return true;
                }
                if (insideRect(x, y, SkinLayout.REPEAT_X, SkinLayout.REPEAT_Y,
                        SkinLayout.SHUFREP_W, SkinLayout.SHUFREP_H)) {
                    if (callbacks != null) callbacks.onRepeat();
                    return true;
                }
                if (y < SkinLayout.TITLE_HEIGHT * 2 && callbacks != null) {
                    callbacks.onMenu();
                    return true;
                }
                return true;

            case MotionEvent.ACTION_CANCEL:
                pressedButton = -1;
                draggingSeek = false;
                draggingVolume = false;
                invalidate();
                return true;

            default:
                return super.onTouchEvent(event);
        }
    }

    private void dispatchButton(int button, float x, float y) {
        if (callbacks == null) return;
        // The transport row is small; treat any tap in the row as the nearest button.
        callbacks.onTransport(button);
    }

    private int insideButton(float x, float y) {
        if (y < SkinLayout.CBUTTONS_Y - 3 || y > SkinLayout.CBUTTONS_Y + SkinLayout.CBUTTONS_H + 3) {
            return -1;
        }
        for (int i = 0; i < BUTTON_COUNT; i++) {
            int bx = SkinLayout.CBUTTONS_X[i];
            int bw = SkinLayout.CBUTTONS_W[i];
            if (x >= bx - 2 && x <= bx + bw + 2) return i;
        }
        return -1;
    }

    private boolean insideRect(float x, float y, int rx, int ry, int rw, int rh) {
        return x >= rx && x <= rx + rw && y >= ry && y <= ry + rh;
    }

    private void seekTo(float x) {
        float fraction = (x - SkinLayout.POSBAR_X) / (float) SkinLayout.POSBAR_W;
        if (callbacks != null) callbacks.onSeek(Math.max(0f, Math.min(1f, fraction)));
    }

    private void setVolume(float x) {
        float fraction = (x - SkinLayout.VOLUME_X) / (float) SkinLayout.VOLUME_W;
        int percent = Math.round(Math.max(0f, Math.min(1f, fraction)) * 100f);
        if (callbacks != null) callbacks.onVolume(percent);
    }
}
