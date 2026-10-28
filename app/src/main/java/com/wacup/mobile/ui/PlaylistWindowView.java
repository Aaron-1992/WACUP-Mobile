package com.wacup.mobile.ui;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.view.MotionEvent;

import com.wacup.mobile.MusicEngine;
import com.wacup.mobile.playlist.Track;
import com.wacup.mobile.skin.SkinLayout;
import com.wacup.mobile.skin.SkinPaint;

/** The playlist editor window: pledit.bmp chrome, coloured rows, scrollbar. */
public class PlaylistWindowView extends SkinSurface {

    public interface Callbacks {
        void onPlayTrack(int index);
        void onTrackMenu(int index);
        void onMenu();
    }

    private final MusicEngine engine;
    private Callbacks callbacks;

    private int visibleRows = 6;
    private float scrollPx;
    private float downY;
    private long downTime;
    private boolean dragging;
    private int pressedRow = -1;

    public PlaylistWindowView(Context context, MusicEngine engine) {
        super(context);
        this.engine = engine;
    }

    public void setCallbacks(Callbacks callbacks) {
        this.callbacks = callbacks;
    }

    public void setVisibleRows(int rows) {
        this.visibleRows = Math.max(1, rows);
        requestLayout();
        invalidate();
    }

    private int skinHeight() {
        return SkinLayout.PL_TITLEBAR_H + visibleRows * SkinLayout.PL_ROW_H
                + SkinLayout.PL_BOTTOM_H;
    }

    @Override
    protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
        setMeasuredDimension((int) Math.ceil(SkinLayout.PL_W * scale),
                (int) Math.ceil(skinHeight() * scale));
    }

    @Override
    protected void onDraw(Canvas canvas) {
        canvas.save();
        canvas.scale(scale, scale);
        int h = skinHeight();
        drawChrome(canvas, h);
        drawTitle(canvas);
        drawRows(canvas, h);
        drawFooter(canvas, h);
        drawScrollbar(canvas, h);
        canvas.restore();
    }

    private void drawChrome(Canvas canvas, int h) {
        // Interior first so the frame sits on top.
        plain.setColor(skin.plNormalBg);
        canvas.drawRect(0, 0, SkinLayout.PL_W, h, plain);

        if (skin.pledit == null) {
            plain.setColor(0xFF2A2A2A);
            canvas.drawRect(0, 0, SkinLayout.PL_W, SkinLayout.PL_TITLEBAR_H, plain);
            plain.setColor(0xFF131313);
            canvas.drawRect(0, SkinLayout.PL_TITLEBAR_H, SkinLayout.PL_W,
                    SkinLayout.PL_TITLEBAR_H + 1, plain);
            canvas.drawRect(0, h - SkinLayout.PL_BOTTOM_H, SkinLayout.PL_W,
                    h - SkinLayout.PL_BOTTOM_H + 1, plain);
            return;
        }

        // Top row: left corner, tiled centre, right corner
        SkinPaint.sprite(canvas, skin.pledit, 0, 0, 25, SkinLayout.PL_TITLEBAR_H, 0, 0, plain);
        for (int x = 25; x < SkinLayout.PL_W - 25; x += 25) {
            int w = Math.min(25, SkinLayout.PL_W - 25 - x);
            SkinPaint.sprite(canvas, skin.pledit, 127, 0, w, SkinLayout.PL_TITLEBAR_H, x, 0, plain);
        }
        SkinPaint.sprite(canvas, skin.pledit, 153, 0, 25, SkinLayout.PL_TITLEBAR_H,
                SkinLayout.PL_W - 25, 0, plain);

        // Sides
        int bodyTop = SkinLayout.PL_TITLEBAR_H;
        int bodyBottom = h - SkinLayout.PL_BOTTOM_H;
        for (int y = bodyTop; y < bodyBottom; y += 29) {
            int hh = Math.min(29, bodyBottom - y);
            SkinPaint.sprite(canvas, skin.pledit, 0, 21, SkinLayout.PL_LEFT_W, hh, 0, y, plain);
            SkinPaint.sprite(canvas, skin.pledit, 32, 21, SkinLayout.PL_RIGHT_W, hh,
                    SkinLayout.PL_W - SkinLayout.PL_RIGHT_W, y, plain);
        }

        // Bottom row
        int bottomY = h - SkinLayout.PL_BOTTOM_H;
        SkinPaint.sprite(canvas, skin.pledit, 0, 72, 125, SkinLayout.PL_BOTTOM_H, 0, bottomY, plain);
        SkinPaint.sprite(canvas, skin.pledit, 127, 72,
                SkinLayout.PL_W - 125, SkinLayout.PL_BOTTOM_H, 125, bottomY, plain);

        // Re-paint the text area so tiled side art does not bleed into the rows.
        plain.setColor(skin.plNormalBg);
        canvas.drawRect(SkinLayout.PL_LEFT_W, bodyTop,
                SkinLayout.PL_W - SkinLayout.PL_RIGHT_W, bodyBottom, plain);
    }

    private void drawTitle(Canvas canvas) {
        green.setColor(skin.plNormal);
        skinPaint.drawText(canvas, "WACUP MOBILE", 30, 7, green, 200);
    }

    private void drawRows(Canvas canvas, int h) {
        int total = engine.playlist().size();
        int first = (int) (scrollPx / SkinLayout.PL_ROW_H);
        int offset = (int) (scrollPx % SkinLayout.PL_ROW_H);
        int current = engine.currentIndex();

        canvas.save();
        canvas.clipRect(SkinLayout.PL_LEFT_W, SkinLayout.PL_TITLEBAR_H,
                SkinLayout.PL_W - SkinLayout.PL_RIGHT_W,
                h - SkinLayout.PL_BOTTOM_H);

        for (int row = 0; row <= visibleRows; row++) {
            int index = first + row;
            if (index >= total) break;

            int y = SkinLayout.PL_TITLEBAR_H + row * SkinLayout.PL_ROW_H - offset;

            if (index == current) {
                plain.setColor(0xFF1B3A1B);
                canvas.drawRect(SkinLayout.PL_LEFT_W, y,
                        SkinLayout.PL_W - SkinLayout.PL_RIGHT_W, y + SkinLayout.PL_ROW_H, plain);
            }
            if (index == pressedRow) {
                plain.setColor(skin.plSelectedBg);
                canvas.drawRect(SkinLayout.PL_LEFT_W, y,
                        SkinLayout.PL_W - SkinLayout.PL_RIGHT_W, y + SkinLayout.PL_ROW_H, plain);
            }

            Track track = engine.playlist().get(index);
            if (track == null) continue;

            int color = (index == current) ? skin.plCurrent : skin.plNormal;
            green.setColor(color);
            String label = (index + 1) + ". " + track.title;
            int maxWidth = SkinLayout.PL_W - SkinLayout.PL_LEFT_W
                    - SkinLayout.PL_RIGHT_W - 60;
            skinPaint.drawText(canvas, label, SkinLayout.PL_TEXT_X + 4, y + 3, green, maxWidth);

            String dur = track.durationLabel();
            int durWidth = (int) skinPaint.textWidth(dur);
            green.setColor(color);
            skinPaint.drawText(canvas, dur,
                    SkinLayout.PL_W - SkinLayout.PL_RIGHT_W - 6 - durWidth, y + 3,
                    green, 40);
        }
        canvas.restore();
    }

    private void drawFooter(Canvas canvas, int h) {
        int total = engine.playlist().size();
        int current = engine.currentIndex() + 1;
        String left = total + " tracks";
        String right = (current > 0 ? current : 0) + "/" + total;
        green.setColor(skin.plNormal);
        skinPaint.drawText(canvas, left, 14, h - SkinLayout.PL_BOTTOM_H + 6, green, 160);
        skinPaint.drawText(canvas, right, 14, h - SkinLayout.PL_BOTTOM_H + 16, green, 160);
        skinPaint.drawText(canvas, engine.shuffle() ? "SHUF" : "    ", 240,
                h - SkinLayout.PL_BOTTOM_H + 6, green, 40);
    }

    private void drawScrollbar(Canvas canvas, int h) {
        int total = engine.playlist().size();
        if (total <= visibleRows) return;

        int trackX = SkinLayout.PL_W - SkinLayout.PL_RIGHT_W + 2;
        int top = SkinLayout.PL_TITLEBAR_H + 2;
        int bottom = h - SkinLayout.PL_BOTTOM_H - 2;
        int trackHeight = bottom - top;

        plain.setColor(0xFF141414);
        canvas.drawRect(trackX, top, trackX + SkinLayout.PL_SCROLL_W - 2, bottom, plain);

        float visibleFraction = visibleRows / (float) total;
        int thumbHeight = Math.max(12, (int) (trackHeight * visibleFraction));
        int maxScroll = Math.max(1, total - visibleRows);
        float scrollFraction = (scrollPx / SkinLayout.PL_ROW_H) / maxScroll;
        int thumbY = top + (int) ((trackHeight - thumbHeight) * scrollFraction);

        plain.setColor(0xFF4A4A4A);
        canvas.drawRect(trackX, thumbY, trackX + SkinLayout.PL_SCROLL_W - 2,
                thumbY + thumbHeight, plain);
    }

    // ------------------------------------------------------------------ input

    @Override
    public boolean onTouchEvent(MotionEvent event) {
        float x = event.getX() / scale;
        float y = event.getY() / scale;

        switch (event.getActionMasked()) {
            case MotionEvent.ACTION_DOWN:
                downY = event.getY();
                downTime = System.currentTimeMillis();
                dragging = false;
                pressedRow = rowAt(y);
                invalidate();
                return true;

            case MotionEvent.ACTION_MOVE: {
                float dy = event.getY() - downY;
                if (Math.abs(dy) > getResources().getDisplayMetrics().density * 6) {
                    dragging = true;
                    pressedRow = -1;
                    scrollPx -= dy;
                    downY = event.getY();
                    clampScroll();
                    invalidate();
                }
                return true;
            }

            case MotionEvent.ACTION_UP:
                if (!dragging) {
                    if (y < SkinLayout.PL_TITLEBAR_H && callbacks != null) {
                        callbacks.onMenu();
                    } else {
                        int row = rowAt(y);
                        boolean longPress = System.currentTimeMillis() - downTime > 500L;
                        if (row >= 0 && callbacks != null) {
                            if (longPress) {
                                callbacks.onTrackMenu(row);
                            } else {
                                callbacks.onPlayTrack(row);
                            }
                        }
                    }
                }
                pressedRow = -1;
                dragging = false;
                invalidate();
                return true;

            case MotionEvent.ACTION_CANCEL:
                pressedRow = -1;
                dragging = false;
                invalidate();
                return true;

            default:
                return super.onTouchEvent(event);
        }
    }

    /** Maps a y coordinate to an absolute playlist index, or -1. */
    private int rowAt(float y) {
        if (y < SkinLayout.PL_TITLEBAR_H) return -1;
        if (y > skinHeight() - SkinLayout.PL_BOTTOM_H) return -1;
        int first = (int) (scrollPx / SkinLayout.PL_ROW_H);
        int offset = (int) (scrollPx % SkinLayout.PL_ROW_H);
        int row = (int) ((y - SkinLayout.PL_TITLEBAR_H + offset) / SkinLayout.PL_ROW_H);
        int index = first + row;
        if (index < 0 || index >= engine.playlist().size()) return -1;
        return index;
    }

    private void clampScroll() {
        int max = Math.max(0, engine.playlist().size() - visibleRows + 1)
                * SkinLayout.PL_ROW_H;
        scrollPx = Math.max(0f, Math.min(max, scrollPx));
    }
}
