package com.wacup.mobile.ui;

import android.content.Context;
import android.graphics.Canvas;
import android.view.MotionEvent;

import com.wacup.mobile.MusicEngine;
import com.wacup.mobile.playlist.Track;
import com.wacup.mobile.skin.SkinLayout;
import com.wacup.mobile.skin.SkinPaint;

/**
 * Playlist editor window, built from the pledit.bmp tile set:
 * top bar (corner / repeating tile / corner), 12px left rail, 20px right rail and a
 * 38px bottom panel. Row metrics match Winamp: 13px rows, 3px top padding.
 */
public class PlaylistWindowView extends SkinSurface {

    public interface Callbacks {
        void onPlayTrack(int index);
        void onTrackMenu(int index);
        void onTitleButton(int which);
        void onListMenu();
    }

    private final MusicEngine engine;
    private Callbacks callbacks;

    private int visibleRows = 8;
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
        visibleRows = Math.max(SkinLayout.PL_MIN_ROWS, rows);
        requestLayout();
        invalidate();
    }

    public int visibleRows() {
        return visibleRows;
    }

    /** Height needed for the current row count, in skin pixels. */
    public int skinHeight() {
        return SkinLayout.PL_TITLE_H + visibleRows * SkinLayout.PL_ROW_H
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

        drawFrame(canvas, h);
        drawRows(canvas, h);
        drawScrollbar(canvas, h);

        canvas.restore();
    }

    /** pledit.bmp tiles, exactly as the format defines them. */
    private void drawFrame(Canvas c, int h) {
        plain.setColor(skin.plNormalBg);
        c.drawRect(0, 0, SkinLayout.PL_W, h, plain);

        if (skin.pledit == null) {
            plain.setColor(0xFF2A2A2A);
            c.drawRect(0, 0, SkinLayout.PL_W, SkinLayout.PL_TITLE_H, plain);
            plain.setColor(0xFF141414);
            c.drawRect(0, SkinLayout.PL_TITLE_H, SkinLayout.PL_W,
                    SkinLayout.PL_TITLE_H + 1, plain);
            plain.setColor(0xFF141414);
            c.drawRect(0, h - SkinLayout.PL_BOTTOM_H, SkinLayout.PL_W,
                    h - SkinLayout.PL_BOTTOM_H + 1, plain);
            skinPaint.drawText(c, "PLAYLIST", 30, 7, skin.plNormal, 200);
            return;
        }

        int top = SkinLayout.PL_TITLE_H;

        // top bar: 25px left corner, 25px repeating tile, 25px right corner
        SkinPaint.sprite(c, skin.pledit, 0, 21, 25, top, 0, 0, plain);
        for (int x = 25; x < SkinLayout.PL_W - 25; x += 25) {
            int w = Math.min(25, SkinLayout.PL_W - 25 - x);
            SkinPaint.sprite(c, skin.pledit, 127, 21, w, top, x, 0, plain);
        }
        SkinPaint.sprite(c, skin.pledit, 153, 21, 25, top, SkinLayout.PL_W - 25, 0, plain);

        // side rails
        int bodyBottom = h - SkinLayout.PL_BOTTOM_H;
        for (int y = top; y < bodyBottom; y += 29) {
            int hh = Math.min(29, bodyBottom - y);
            SkinPaint.sprite(c, skin.pledit, 0, 42, SkinLayout.PL_LEFT_W, hh, 0, y, plain);
            SkinPaint.sprite(c, skin.pledit, 31, 42, SkinLayout.PL_RIGHT_W, hh,
                    SkinLayout.PL_W - SkinLayout.PL_RIGHT_W, y, plain);
        }

        // bottom panel: 125px corner + 150px corner
        int bottomY = h - SkinLayout.PL_BOTTOM_H;
        SkinPaint.sprite(c, skin.pledit, 0, 72, 125, SkinLayout.PL_BOTTOM_H, 0, bottomY, plain);
        SkinPaint.sprite(c, skin.pledit, 126, 72, 150, SkinLayout.PL_BOTTOM_H,
                125, bottomY, plain);

        // the text well
        plain.setColor(skin.plNormalBg);
        c.drawRect(SkinLayout.PL_LEFT_W, top + SkinLayout.PL_TEXT_PAD_TOP,
                SkinLayout.PL_W - SkinLayout.PL_RIGHT_W,
                bodyBottom, plain);

        skinPaint.drawText(c, "WACUP MOBILE", 30, 7, skin.plNormal, 200);
    }

    private void drawRows(Canvas c, int h) {
        int total = engine.playlist().size();
        int current = engine.currentIndex();
        int bodyTop = SkinLayout.PL_TITLE_H + SkinLayout.PL_TEXT_PAD_TOP;
        int bodyBottom = h - SkinLayout.PL_BOTTOM_H;

        int first = (int) (scrollPx / SkinLayout.PL_ROW_H);
        int offset = (int) (scrollPx % SkinLayout.PL_ROW_H);

        c.save();
        c.clipRect(SkinLayout.PL_LEFT_W, bodyTop,
                SkinLayout.PL_W - SkinLayout.PL_RIGHT_W, bodyBottom);

        for (int row = 0; row <= visibleRows; row++) {
            int index = first + row;
            if (index >= total) break;
            int y = bodyTop + row * SkinLayout.PL_ROW_H - offset;

            if (index == current) {
                plain.setColor(skin.plSelectedBg);
                c.drawRect(SkinLayout.PL_LEFT_W, y,
                        SkinLayout.PL_W - SkinLayout.PL_RIGHT_W, y + SkinLayout.PL_ROW_H, plain);
            } else if (index == pressedRow) {
                plain.setColor(0x33FFFFFF);
                c.drawRect(SkinLayout.PL_LEFT_W, y,
                        SkinLayout.PL_W - SkinLayout.PL_RIGHT_W, y + SkinLayout.PL_ROW_H, plain);
            }

            Track track = engine.playlist().get(index);
            if (track == null) continue;
            int color = (index == current) ? skin.plCurrent : skin.plNormal;

            int textWidth = SkinLayout.PL_W - SkinLayout.PL_RIGHT_W
                    - SkinLayout.PL_TEXT_X - 46;
            skinPaint.drawText(c, (index + 1) + ". " + track.title,
                    SkinLayout.PL_TEXT_X, y + 4, color, textWidth);

            String duration = track.durationLabel();
            int width = (int) skinPaint.textWidth(duration);
            skinPaint.drawText(c, duration,
                    SkinLayout.PL_W - SkinLayout.PL_RIGHT_W - 4 - width, y + 4,
                    color, 40);
        }
        c.restore();

        // footer: track count, current index, total time
        skinPaint.drawText(c, total + " tracks", 16, h - SkinLayout.PL_BOTTOM_H + 6,
                skin.plNormal, 150);
        String position = (Math.max(1, current + 1)) + "/" + total;
        skinPaint.drawText(c, position, 16, h - SkinLayout.PL_BOTTOM_H + 17,
                skin.plNormal, 60);

        long totalMs = engine.playlist().totalDurationMs();
        if (totalMs > 0) {
            long seconds = totalMs / 1000L;
            String label = String.format(java.util.Locale.US, "%d:%02d",
                    seconds / 60L, seconds % 60L);
            skinPaint.drawText(c, label, 150, h - SkinLayout.PL_BOTTOM_H + 6,
                    skin.plNormal, 80);
        }
    }

    private void drawScrollbar(Canvas c, int h) {
        int total = engine.playlist().size();
        if (total <= visibleRows || skin.pledit == null) return;

        int x = SkinLayout.PL_W - SkinLayout.PL_RIGHT_W + 4;
        int top = SkinLayout.PL_TITLE_H + 2;
        int bottom = h - SkinLayout.PL_BOTTOM_H - 2;
        int trackHeight = bottom - top;

        int thumbHeight = Math.max(18, (int) (trackHeight * (visibleRows / (float) total)));
        int maxScroll = Math.max(1, total - visibleRows);
        float fraction = (scrollPx / SkinLayout.PL_ROW_H) / maxScroll;
        int thumbY = top + (int) ((trackHeight - thumbHeight) * fraction);

        if (skin.pledit.getHeight() >= 71 && skin.pledit.getWidth() >= 60) {
            SkinPaint.sprite(c, skin.pledit, 52, 53, 8, Math.min(18, thumbHeight),
                    x, thumbY, plain);
        } else {
            plain.setColor(0xFF666666);
            c.drawRect(x, thumbY, x + 8, thumbY + thumbHeight, plain);
        }
    }

    // ------------------------------------------------------------------ input

    @Override
    public boolean onTouchEvent(MotionEvent event) {
        float x = event.getX() / scale;
        float y = event.getY() / scale;
        int h = skinHeight();

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
                    scrollPx -= dy / scale;
                    downY = event.getY();
                    clampScroll();
                    invalidate();
                }
                return true;
            }

            case MotionEvent.ACTION_UP:
                if (!dragging) {
                    if (y < SkinLayout.PL_TITLE_H) {
                        if (x >= SkinLayout.PL_W - 25 && callbacks != null) {
                            callbacks.onTitleButton(0);
                        } else if (x >= SkinLayout.PL_W - 35 && callbacks != null) {
                            callbacks.onTitleButton(1);
                        }
                    } else if (y > h - SkinLayout.PL_BOTTOM_H) {
                        if (callbacks != null) callbacks.onListMenu();
                    } else {
                        int row = rowAt(y);
                        if (row >= 0 && callbacks != null) {
                            if (System.currentTimeMillis() - downTime > 500L) {
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

    private int rowAt(float y) {
        int bodyTop = SkinLayout.PL_TITLE_H + SkinLayout.PL_TEXT_PAD_TOP;
        if (y < bodyTop) return -1;
        if (y > skinHeight() - SkinLayout.PL_BOTTOM_H) return -1;
        int first = (int) (scrollPx / SkinLayout.PL_ROW_H);
        int offset = (int) (scrollPx % SkinLayout.PL_ROW_H);
        int row = (int) ((y - bodyTop + offset) / SkinLayout.PL_ROW_H);
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
