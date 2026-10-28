package com.wacup.mobile.ui;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.view.MotionEvent;

import com.wacup.mobile.MusicEngine;
import com.wacup.mobile.skin.SkinLayout;
import com.wacup.mobile.skin.SkinPaint;

/** The 275x116 equaliser window: ten sliders, on/off and presets. */
public class EqWindowView extends SkinSurface {

    public interface Callbacks {
        void onToggleEqEnabled();
        void onCyclePreset();
        void onMenu();
    }

    private static final float MAX_DB = 12f;

    private static final String[] PRESET_NAMES = {
            "FLAT", "ROCK", "POP", "JAZZ", "CLASSIC", "DANCE", "BASS", "TREBLE"
    };

    private static final float[][] PRESETS = {
            {0, 0, 0, 0, 0, 0, 0, 0, 0, 0},
            {5, 4, 3, 1, -1, -1, 0, 2, 3, 4},
            {-1, 2, 4, 4, 1, -1, -1, 1, 2, 2},
            {3, 2, 1, 2, -1, -1, 0, 1, 2, 3},
            {4, 3, 2, 1, -1, -1, 0, 2, 3, 4},
            {6, 5, 2, 0, 0, -2, -3, -3, 0, 1},
            {7, 6, 4, 2, 0, 0, 0, 0, 0, 0},
            {-3, -2, 0, 1, 2, 3, 4, 5, 6, 6}
    };

    private final MusicEngine engine;
    private Callbacks callbacks;
    private int presetIndex = -1;
    private int draggedBand = -1;

    public EqWindowView(Context context, MusicEngine engine) {
        super(context);
        this.engine = engine;
    }

    public void setCallbacks(Callbacks callbacks) {
        this.callbacks = callbacks;
    }

    @Override
    protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
        setMeasuredDimension((int) Math.ceil(SkinLayout.EQ_W * scale),
                (int) Math.ceil(SkinLayout.EQ_H * scale));
    }

    @Override
    protected void onDraw(Canvas canvas) {
        canvas.save();
        canvas.scale(scale, scale);

        if (skin.eqmain != null) {
            canvas.drawBitmap(skin.eqmain, 0, 0, plain);
            // The skin's own slider artwork varies; draw our handles on top.
        } else {
            plain.setColor(0xFF232323);
            canvas.drawRect(0, 0, SkinLayout.EQ_W, SkinLayout.EQ_H, plain);
            plain.setColor(0xFF131313);
            canvas.drawRect(0, 0, SkinLayout.EQ_W, SkinLayout.TITLE_HEIGHT, plain);
        }

        drawHeader(canvas);
        drawSliders(canvas);
        drawLabels(canvas);

        canvas.restore();
    }

    private void drawHeader(Canvas canvas) {
        green.setColor(engine.eqEnabled() ? 0xFF00F800 : 0xFF006000);
        plain.setColor(engine.eqEnabled() ? 0xFF0B2B0B : 0xFF141414);
        canvas.drawRect(14, 14, 44, 28, plain);
        skinPaint.drawText(canvas, engine.eqEnabled() ? "ON" : "OFF", 18, 18, green, 24);

        plain.setColor(0xFF141414);
        canvas.drawRect(48, 14, 108, 28, plain);
        green.setColor(0xFF00B000);
        String preset = presetIndex >= 0 && presetIndex < PRESET_NAMES.length
                ? PRESET_NAMES[presetIndex] : "CUSTOM";
        skinPaint.drawText(canvas, preset, 52, 18, green, 54);

        green.setColor(0xFF00F800);
        skinPaint.drawText(canvas, "EQ", 4, 18, green, 12);
    }

    private void drawSliders(Canvas canvas) {
        float[] gains = engine.bandGains();
        for (int i = 0; i < gains.length; i++) {
            int x = SkinLayout.EQ_BAND_X + i * SkinLayout.EQ_BAND_GAP;
            int top = SkinLayout.EQ_SLIDER_TOP;
            int bottom = top + SkinLayout.EQ_SLIDER_H;

            // Slot
            plain.setColor(0xFF0A0A0A);
            canvas.drawRect(x + 3, top, x + 8, bottom, plain);
            // Zero line
            plain.setColor(0xFF1E3A1E);
            int mid = (top + bottom) / 2;
            canvas.drawRect(x + 2, mid, x + 9, mid + 1, plain);

            // Filled level from the middle
            float fraction = gains[i] / MAX_DB;              // -1..1
            int handleCenter = mid - (int) (fraction * (SkinLayout.EQ_SLIDER_H / 2f));
            plain.setColor(0xFF00F800);
            if (fraction >= 0) {
                canvas.drawRect(x + 4, handleCenter, x + 7, mid, plain);
            } else {
                canvas.drawRect(x + 4, mid, x + 7, handleCenter, plain);
            }

            // Handle
            int handleTop = handleCenter - SkinLayout.EQ_SLIDER_THUMB_H / 2;
            plain.setColor(0xFFB0B0B0);
            canvas.drawRect(x, handleTop, x + SkinLayout.EQ_SLIDER_THUMB_W,
                    handleTop + SkinLayout.EQ_SLIDER_THUMB_H, plain);
            plain.setColor(0xFF3A3A3A);
            canvas.drawRect(x, handleTop, x + SkinLayout.EQ_SLIDER_THUMB_W,
                    handleTop + 1, plain);
        }
    }

    private void drawLabels(Canvas canvas) {
        green.setColor(0xFF00A000);
        for (int i = 0; i < MusicEngine.BAND_LABELS.length; i++) {
            int x = SkinLayout.EQ_BAND_X + i * SkinLayout.EQ_BAND_GAP - 2;
            skinPaint.drawText(canvas, MusicEngine.BAND_LABELS[i], x,
                    SkinLayout.EQ_SLIDER_TOP + SkinLayout.EQ_SLIDER_H + 3, green, 20);
        }
        green.setColor(0xFF00F800);
        skinPaint.drawText(canvas, "PRE", 2, SkinLayout.EQ_SLIDER_TOP + 4, green, 16);
    }

    // ------------------------------------------------------------------ input

    @Override
    public boolean onTouchEvent(MotionEvent event) {
        float x = event.getX() / scale;
        float y = event.getY() / scale;

        switch (event.getActionMasked()) {
            case MotionEvent.ACTION_DOWN:
                if (x >= 14 && x <= 44 && y >= 12 && y <= 30) {
                    if (callbacks != null) callbacks.onToggleEqEnabled();
                    return true;
                }
                if (x >= 48 && x <= 108 && y >= 12 && y <= 30) {
                    if (callbacks != null) callbacks.onCyclePreset();
                    return true;
                }
                draggedBand = bandAt(x);
                if (draggedBand >= 0) {
                    applyGain(draggedBand, y);
                    return true;
                }
                if (y < SkinLayout.TITLE_HEIGHT) {
                    if (callbacks != null) callbacks.onMenu();
                }
                return true;

            case MotionEvent.ACTION_MOVE:
                if (draggedBand >= 0) {
                    applyGain(draggedBand, y);
                    return true;
                }
                return true;

            case MotionEvent.ACTION_UP:
                draggedBand = -1;
                return true;

            case MotionEvent.ACTION_CANCEL:
                draggedBand = -1;
                return true;

            default:
                return super.onTouchEvent(event);
        }
    }

    private int bandAt(float x) {
        for (int i = 0; i < MusicEngine.BAND_LABELS.length; i++) {
            int left = SkinLayout.EQ_BAND_X + i * SkinLayout.EQ_BAND_GAP - 4;
            if (x >= left && x <= left + SkinLayout.EQ_BAND_GAP) return i;
        }
        return -1;
    }

    private void applyGain(int band, float y) {
        int top = SkinLayout.EQ_SLIDER_TOP;
        int bottom = top + SkinLayout.EQ_SLIDER_H;
        float fraction = 1f - ((y - top) / (float) (bottom - top));   // 0 top .. 1 bottom
        fraction = Math.max(0f, Math.min(1f, fraction));
        float db = (fraction * 2f - 1f) * MAX_DB;
        presetIndex = -1;
        engine.setBandGain(band, db);
        invalidate();
    }

    public void applyPreset(int index) {
        if (index < 0 || index >= PRESETS.length) return;
        presetIndex = index;
        for (int i = 0; i < PRESETS[index].length; i++) {
            engine.setBandGain(i, PRESETS[index][i]);
        }
        invalidate();
    }

    public void nextPreset() {
        applyPreset((presetIndex + 1) % PRESETS.length);
    }
}
