package com.wacup.mobile.ui;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.view.MotionEvent;

import com.wacup.mobile.MusicEngine;
import com.wacup.mobile.skin.SkinLayout;
import com.wacup.mobile.skin.SkinPaint;

/**
 * The equaliser window.
 *
 * The whole panel (grooves, dB scale, frequency labels, buttons) is painted by the
 * skin in eqmain.bmp's first 116 rows, so this view draws that art and then puts
 * only the interactive bits on top: the eleven slider thumbs and the ON button
 * state. Thumbs come from eqmain.bmp (0,164) / (0,176).
 */
public class EqWindowView extends SkinSurface {

    public interface Callbacks {
        void onToggleEqEnabled();
        void onPresetMenu();
        void onTitleButton(int which);
    }

    private static final float MAX_DB = 12f;

    private final MusicEngine engine;
    private Callbacks callbacks;
    private int draggedSlider = -1;    // 0 preamp, 1..10 bands
    private boolean shaded;

    public EqWindowView(Context context, MusicEngine engine) {
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

    @Override
    protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
        setMeasuredDimension((int) Math.ceil(SkinLayout.EQ_W * scale),
                (int) Math.ceil((shaded ? SkinLayout.SHADE_H : SkinLayout.EQ_H) * scale));
    }

    @Override
    protected void onDraw(Canvas canvas) {
        canvas.save();
        canvas.scale(scale, scale);

        if (shaded) {
            drawShade(canvas);
            canvas.restore();
            return;
        }

        if (skin.eqmain != null) {
            canvas.drawBitmap(skin.eqmain, 0, 0, plain);
        } else {
            plain.setColor(0xFF232323);
            canvas.drawRect(0, 0, SkinLayout.EQ_W, SkinLayout.EQ_H, plain);
        }

        drawOnButton(canvas);
        drawSliders(canvas);
        drawGraph(canvas);

        canvas.restore();
    }

    private void drawShade(Canvas c) {
        plain.setColor(0xFF232323);
        c.drawRect(0, 0, SkinLayout.EQ_W, SkinLayout.SHADE_H, plain);
        if (skin.eq_ex != null) {
            SkinPaint.sprite(c, skin.eq_ex, 0, 0, SkinLayout.EQ_W, SkinLayout.SHADE_H, 0, 0, plain);
        } else if (skin.eqmain != null) {
            SkinPaint.sprite(c, skin.eqmain, 0, 134, SkinLayout.EQ_W, SkinLayout.SHADE_H,
                    0, 0, plain);
        }
        skinPaint.drawText(c, engine.eqEnabled() ? "EQ ON" : "EQ OFF", 6, 4,
                skin.plNormal, 60);
    }

    /** ON button: shufrep-style 4-state sprite from eqmain.bmp. */
    private void drawOnButton(Canvas c) {
        if (skin.eqmain == null) return;
        boolean on = engine.eqEnabled();
        int srcX = on ? 69 : 10;
        SkinPaint.sprite(c, skin.eqmain, srcX, 119, SkinLayout.EQ_ON_W,
                SkinLayout.EQ_BUTTON_H, SkinLayout.EQ_ON_X, SkinLayout.EQ_BUTTON_Y, plain);
    }

    private void drawSliders(Canvas c) {
        float[] gains = engine.bandGains();
        for (int i = 0; i < gains.length; i++) {
            int x = i == 0 ? SkinLayout.EQ_PREAMP_X
                    : SkinLayout.EQ_BAND_X + (i - 1) * SkinLayout.EQ_BAND_PITCH;
            drawThumb(c, x, gains[i], draggedSlider == i);
        }
    }

    private void drawThumb(Canvas c, int x, float gainDb, boolean active) {
        int travel = SkinLayout.EQ_SLIDER_H - SkinLayout.EQ_THUMB_H;
        float fraction = (gainDb / MAX_DB + 1f) / 2f;      // 0 bottom .. 1 top
        fraction = Math.max(0f, Math.min(1f, fraction));
        int y = SkinLayout.EQ_SLIDER_Y + Math.round(travel * (1f - fraction));

        if (skin.eqmain != null) {
            int srcX = active ? 0 : 0;
            int srcY = active ? 176 : 164;
            if (srcY + SkinLayout.EQ_THUMB_H <= skin.eqmain.getHeight()) {
                SkinPaint.sprite(c, skin.eqmain, srcX, srcY, SkinLayout.EQ_THUMB_W,
                        SkinLayout.EQ_THUMB_H, x, y, plain);
                return;
            }
        }
        plain.setColor(0xFFC8C8C8);
        c.drawRect(x, y, x + SkinLayout.EQ_THUMB_W, y + SkinLayout.EQ_THUMB_H, plain);
        plain.setColor(0xFF444444);
        c.drawRect(x, y + 5, x + SkinLayout.EQ_THUMB_W, y + 6, plain);
    }

    /** The curve inside the skin's graph box, drawn from viscolor.txt. */
    private void drawGraph(Canvas c) {
        Paint line = new Paint(Paint.ANTI_ALIAS_FLAG);
        line.setColor(skin.visColors[Math.min(17, skin.visColors.length - 1)]);
        line.setStrokeWidth(1f);

        float[] gains = engine.bandGains();
        int gx = SkinLayout.EQ_GRAPH_X;
        int gy = SkinLayout.EQ_GRAPH_Y;
        int gw = SkinLayout.EQ_GRAPH_W;
        int gh = SkinLayout.EQ_GRAPH_H;
        float step = gw / 10f;

        float prevX = gx;
        float prevY = bandY(gy, gh, gains[0]);
        for (int i = 1; i < gains.length; i++) {
            float x = gx + step * i;
            float y = bandY(gy, gh, gains[i]);
            c.drawLine(prevX, prevY, x, y, line);
            prevX = x;
            prevY = y;
        }
    }

    private float bandY(int graphY, int graphH, float gainDb) {
        float fraction = (gainDb / MAX_DB + 1f) / 2f;
        return graphY + graphH - (graphH * fraction);
    }

    // ------------------------------------------------------------------ input

    @Override
    public boolean onTouchEvent(MotionEvent event) {
        float x = event.getX() / scale;
        float y = event.getY() / scale;

        switch (event.getActionMasked()) {
            case MotionEvent.ACTION_DOWN:
                if (y <= SkinLayout.TITLE_H) {
                    if (x >= SkinLayout.EQ_CLOSE_X - 2) {
                        if (callbacks != null) callbacks.onTitleButton(0);
                    } else if (x >= SkinLayout.EQ_SHADE_X - 2 && x < SkinLayout.EQ_CLOSE_X - 2) {
                        if (callbacks != null) callbacks.onTitleButton(1);
                    }
                    return true;
                }
                if (inside(x, y, SkinLayout.EQ_ON_X, SkinLayout.EQ_BUTTON_Y,
                        SkinLayout.EQ_ON_W, SkinLayout.EQ_BUTTON_H)) {
                    if (callbacks != null) callbacks.onToggleEqEnabled();
                    return true;
                }
                if (inside(x, y, SkinLayout.EQ_PRESETS_X, SkinLayout.EQ_BUTTON_Y,
                        SkinLayout.EQ_PRESETS_W, SkinLayout.EQ_BUTTON_H)) {
                    if (callbacks != null) callbacks.onPresetMenu();
                    return true;
                }
                draggedSlider = sliderAt(x);
                if (draggedSlider >= 0) {
                    applyGain(draggedSlider, y);
                    return true;
                }
                return true;

            case MotionEvent.ACTION_MOVE:
                if (draggedSlider >= 0) {
                    applyGain(draggedSlider, y);
                    return true;
                }
                return true;

            case MotionEvent.ACTION_UP:
            case MotionEvent.ACTION_CANCEL:
                draggedSlider = -1;
                invalidate();
                return true;

            default:
                return super.onTouchEvent(event);
        }
    }

    private int sliderAt(float x) {
        if (x >= SkinLayout.EQ_PREAMP_X - 4
                && x <= SkinLayout.EQ_PREAMP_X + SkinLayout.EQ_SLIDER_W + 4) {
            return 0;
        }
        for (int i = 1; i <= 10; i++) {
            int bandX = SkinLayout.EQ_BAND_X + (i - 1) * SkinLayout.EQ_BAND_PITCH;
            if (x >= bandX - 4 && x <= bandX + SkinLayout.EQ_SLIDER_W + 4) {
                return i;
            }
        }
        return -1;
    }

    private void applyGain(int slider, float y) {
        int top = SkinLayout.EQ_SLIDER_Y;
        int bottom = top + SkinLayout.EQ_SLIDER_H;
        float fraction = 1f - ((y - top) / (float) (bottom - top));
        fraction = Math.max(0f, Math.min(1f, fraction));
        float db = (fraction * 2f - 1f) * MAX_DB;
        if (slider == 0) {
            // preamp is applied as an offset on every band
            float delta = db - preampDb;
            preampDb = db;
            for (int i = 0; i < MusicEngine.BAND_LABELS.length; i++) {
                engine.setBandGain(i, engine.bandGains()[i] + delta);
            }
        } else {
            engine.setBandGain(slider - 1, db);
        }
        invalidate();
    }

    private float preampDb = 0f;

    public float preampDb() {
        return preampDb;
    }

    private boolean inside(float x, float y, int rx, int ry, int rw, int rh) {
        return x >= rx && x <= rx + rw && y >= ry && y <= ry + rh;
    }
}
