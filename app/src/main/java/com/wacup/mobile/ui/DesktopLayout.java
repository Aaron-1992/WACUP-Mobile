package com.wacup.mobile.ui;

import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Canvas;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;

import com.wacup.mobile.skin.SkinLayout;

/**
 * Free-floating Winamp-style windows over a virtual desktop.
 *
 * Two modes:
 *  - <b>auto-fit</b> (default): the windows are stacked flush like Winamp's
 *    "snap together" behaviour, the scale is chosen so the whole stack fits, and
 *    the playlist grows or shrinks to use the leftover height.
 *  - <b>manual</b>: dragging a title bar detaches a window; it can be placed
 *    anywhere and snaps to screen edges, to the centre lines and to the edges of
 *    the other windows.
 *
 * Positions live in skin coordinates and are persisted.
 */
public class DesktopLayout extends ViewGroup {

    public static final int MAIN = 0;
    public static final int EQ = 1;
    public static final int PLAYLIST = 2;

    private static final String PREFS = "wacup_windows";
    private static final long DOUBLE_TAP_MS = 320L;
    private static final float MIN_SCALE = 0.45f;
    private static final float MAX_SCALE = 3.2f;

    public interface Listener {
        void onTitleTap(int kind);
        void onToggleShade(int kind);
        void onWindowMoved();
        void onFitChanged(boolean autoFit);
    }

    private final View[] windows = new View[3];
    private final float[] posX = new float[3];
    private final float[] posY = new float[3];
    private final boolean[] shown = {true, false, true};
    private final boolean[] shaded = new boolean[3];

    private final SharedPreferences prefs;
    private Listener listener;

    private boolean autoFit = true;
    private float scale = 1f;
    private float contentLeft;
    private float contentTop;

    private int dragKind = -1;
    private float dragStartX;
    private float dragStartY;
    private float dragOriginX;
    private float dragOriginY;
    private boolean dragMoved;

    private long lastTapTime;
    private float lastTapX;
    private float lastTapY;
    private int lastTapKind = -1;

    public DesktopLayout(Context context, MainWindowView main,
                         EqWindowView eq, PlaylistWindowView playlist) {
        super(context);
        windows[MAIN] = main;
        windows[EQ] = eq;
        windows[PLAYLIST] = playlist;
        setClipChildren(false);

        addView(main);
        addView(eq);
        addView(playlist);

        prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        autoFit = prefs.getBoolean("autoFit", true);
        posX[MAIN] = prefs.getFloat("x0", 0f);
        posY[MAIN] = prefs.getFloat("y0", 0f);
        posX[EQ] = prefs.getFloat("x1", 0f);
        posY[EQ] = prefs.getFloat("y1", SkinLayout.MAIN_H);
        posX[PLAYLIST] = prefs.getFloat("x2", 0f);
        posY[PLAYLIST] = prefs.getFloat("y2", SkinLayout.MAIN_H + SkinLayout.EQ_H);
        shown[EQ] = prefs.getBoolean("show1", false);
        shaded[MAIN] = prefs.getBoolean("shade0", false);

        eq.setVisibility(shown[EQ] ? VISIBLE : GONE);
        playlist.setVisibility(shown[PLAYLIST] ? VISIBLE : GONE);
        main.setShaded(shaded[MAIN]);
        eq.setShaded(shaded[EQ]);
    }

    public void setListener(Listener listener) {
        this.listener = listener;
    }

    // ------------------------------------------------------------- visibility

    public void setWindowVisible(int kind, boolean visible) {
        shown[kind] = visible;
        windows[kind].setVisibility(visible ? VISIBLE : GONE);
        if (visible) windows[kind].bringToFront();
        prefs.edit().putBoolean("show" + kind, visible).apply();
        requestLayout();
    }

    public boolean isWindowVisible(int kind) {
        return shown[kind];
    }

    public void toggleWindow(int kind) {
        setWindowVisible(kind, !shown[kind]);
    }

    public void setShaded(int kind, boolean on) {
        shaded[kind] = on;
        if (kind == MAIN) ((MainWindowView) windows[MAIN]).setShaded(on);
        if (kind == EQ) ((EqWindowView) windows[EQ]).setShaded(on);
        prefs.edit().putBoolean("shade" + kind, on).apply();
        requestLayout();
    }

    public boolean isShaded(int kind) {
        return shaded[kind];
    }

    public boolean isAutoFit() {
        return autoFit;
    }

    /** Re-stacks everything and hands control back to the automatic layout. */
    public void fitToScreen() {
        autoFit = true;
        prefs.edit().putBoolean("autoFit", true).apply();
        if (listener != null) listener.onFitChanged(true);
        requestLayout();
    }

    /** Back to a fresh stack in the default place, keeping auto-fit on. */
    public void resetPositions() {
        posX[MAIN] = 0;
        posY[MAIN] = 0;
        posX[EQ] = 0;
        posY[EQ] = SkinLayout.MAIN_H;
        posX[PLAYLIST] = 0;
        posY[PLAYLIST] = SkinLayout.MAIN_H + SkinLayout.EQ_H;
        persistPositions();
        fitToScreen();
    }

    private void setManual() {
        if (!autoFit) return;
        autoFit = false;
        prefs.edit().putBoolean("autoFit", false).apply();
        if (listener != null) listener.onFitChanged(false);
    }

    private void persistPositions() {
        prefs.edit()
                .putFloat("x0", posX[MAIN]).putFloat("y0", posY[MAIN])
                .putFloat("x1", posX[EQ]).putFloat("y1", posY[EQ])
                .putFloat("x2", posX[PLAYLIST]).putFloat("y2", posY[PLAYLIST])
                .apply();
    }

    // --------------------------------------------------------------- measure

    @Override
    protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
        int width = MeasureSpec.getSize(widthMeasureSpec);
        int height = MeasureSpec.getSize(heightMeasureSpec);
        if (width == 0 || height == 0) {
            super.onMeasure(widthMeasureSpec, heightMeasureSpec);
            return;
        }

        float density = getResources().getDisplayMetrics().density;
        float pad = 4f * density;
        int spec = MeasureSpec.makeMeasureSpec(0, MeasureSpec.UNSPECIFIED);

        PlaylistWindowView playlist = (PlaylistWindowView) windows[PLAYLIST];
        float fixedSkin = mainHeight()
                + (shown[EQ] ? eqHeight() : 0f)
                + (shown[PLAYLIST] ? SkinLayout.PL_TITLE_H + SkinLayout.PL_BOTTOM_H : 0f);

        // Start from the largest scale the width allows, then give the playlist
        // whatever vertical room is left over.
        float candidate = Math.min((width - 2 * pad) / (float) SkinLayout.PL_W,
                MAX_SCALE);
        if (candidate < MIN_SCALE) candidate = MIN_SCALE;

        float availableSkin = (height - 2 * pad) / candidate;
        int rows = 3;
        if (shown[PLAYLIST]) {
            rows = (int) Math.floor((availableSkin - fixedSkin) / SkinLayout.PL_ROW_H);
            rows = Math.max(SkinLayout.PL_MIN_ROWS, Math.min(24, rows));
        }
        float stackSkin = fixedSkin + (shown[PLAYLIST] ? rows * SkinLayout.PL_ROW_H : 0f);

        float fitH = (height - 2 * pad) / stackSkin;
        scale = Math.max(MIN_SCALE, Math.min(candidate, fitH));

        // Recompute rows now that the scale is final, so the stack exactly fits.
        availableSkin = (height - 2 * pad) / scale;
        if (shown[PLAYLIST]) {
            rows = (int) Math.floor((availableSkin - fixedSkin) / SkinLayout.PL_ROW_H);
            rows = Math.max(SkinLayout.PL_MIN_ROWS, Math.min(24, rows));
            playlist.setVisibleRows(rows);
        }

        for (View child : windows) {
            if (child instanceof SkinSurface) ((SkinSurface) child).setScale(scale);
            child.measure(spec, spec);
        }

        float stackH = mainHeight()
                + (shown[EQ] ? eqHeight() : 0f)
                + (shown[PLAYLIST] ? playlist.skinHeight() : 0f);

        contentLeft = (width - SkinLayout.PL_W * scale) / 2f;
        float stackPixels = stackH * scale;
        contentTop = Math.max(pad, (height - stackPixels) / 2f);

        if (autoFit) {
            posX[MAIN] = 0;
            posY[MAIN] = 0;
            posX[EQ] = 0;
            posY[EQ] = mainHeight();
            posX[PLAYLIST] = 0;
            posY[PLAYLIST] = mainHeight() + (shown[EQ] ? eqHeight() : 0f);
        }

        setMeasuredDimension(width, height);
    }

    private float mainHeight() {
        return shaded[MAIN] ? SkinLayout.SHADE_H : SkinLayout.MAIN_H;
    }

    private float eqHeight() {
        return shaded[EQ] ? SkinLayout.SHADE_H : SkinLayout.EQ_H;
    }

    @Override
    protected void onLayout(boolean changed, int l, int t, int r, int b) {
        int width = getWidth();
        int height = getHeight();

        for (int kind = 0; kind < windows.length; kind++) {
            View child = windows[kind];
            if (child.getVisibility() != VISIBLE) continue;

            int cw = child.getMeasuredWidth();
            int chh = child.getMeasuredHeight();
            float maxX = Math.max(0, (width - cw - contentLeft) / Math.max(0.01f, scale));
            float maxY = Math.max(0, (height - chh - contentTop) / Math.max(0.01f, scale));
            posX[kind] = Math.max(0, Math.min(maxX, posX[kind]));
            posY[kind] = Math.max(0, Math.min(maxY, posY[kind]));

            int x = Math.round(contentLeft + posX[kind] * scale);
            int y = Math.round(contentTop + posY[kind] * scale);
            child.layout(x, y, x + cw, y + chh);
        }
    }

    @Override
    protected void dispatchDraw(Canvas canvas) {
        super.dispatchDraw(canvas);
    }

    // ----------------------------------------------------------------- touch

    @Override
    public boolean onInterceptTouchEvent(MotionEvent ev) {
        if (ev.getActionMasked() != MotionEvent.ACTION_DOWN) {
            return dragKind >= 0;
        }

        int kind = windowAt(ev.getX(), ev.getY());
        if (kind < 0) return false;
        if (!inTitleBar(kind, ev.getX(), ev.getY())) return false;

        // Let the main window keep its own title bar buttons (menu, shade, close).
        if (kind == MAIN) {
            View child = windows[kind];
            float skinX = (ev.getX() - child.getLeft()) / Math.max(0.01f, scale);
            float skinY = (ev.getY() - child.getTop()) / Math.max(0.01f, scale);
            if (((MainWindowView) child).isTitleButton(skinX, skinY)) return false;
        }

        long now = System.currentTimeMillis();
        boolean doubleTap = kind == lastTapKind
                && now - lastTapTime < DOUBLE_TAP_MS
                && Math.abs(ev.getX() - lastTapX) < 48
                && Math.abs(ev.getY() - lastTapY) < 48;

        windows[kind].bringToFront();

        if (doubleTap) {
            lastTapKind = -1;
            if (listener != null) listener.onToggleShade(kind);
            return false;
        }

        dragKind = kind;
        dragMoved = false;
        dragStartX = ev.getX();
        dragStartY = ev.getY();
        dragOriginX = posX[kind];
        dragOriginY = posY[kind];
        return true;
    }

    @Override
    public boolean onTouchEvent(MotionEvent ev) {
        if (dragKind < 0) return super.onTouchEvent(ev);

        switch (ev.getActionMasked()) {
            case MotionEvent.ACTION_MOVE: {
                float dx = (ev.getX() - dragStartX) / Math.max(0.01f, scale);
                float dy = (ev.getY() - dragStartY) / Math.max(0.01f, scale);
                if (!dragMoved && (Math.abs(dx) > 2 || Math.abs(dy) > 2)) {
                    dragMoved = true;
                    setManual();
                }
                if (dragMoved) {
                    posX[dragKind] = dragOriginX + dx;
                    posY[dragKind] = dragOriginY + dy;
                    snap(dragKind);
                    requestLayout();
                }
                return true;
            }

            case MotionEvent.ACTION_UP: {
                if (!dragMoved) {
                    lastTapTime = System.currentTimeMillis();
                    lastTapX = ev.getX();
                    lastTapY = ev.getY();
                    lastTapKind = dragKind;
                    if (listener != null) listener.onTitleTap(dragKind);
                } else {
                    persistPositions();
                    if (listener != null) listener.onWindowMoved();
                }
                dragKind = -1;
                return true;
            }

            case MotionEvent.ACTION_CANCEL:
                dragKind = -1;
                return true;

            default:
                return true;
        }
    }

    /**
     * Snaps the dragged window to the screen edges, the centre lines and every
     * other visible window's edges, so they butt up flush the way Winamp's windows
     * do on a desktop.
     */
    private void snap(int kind) {
        float threshold = (6f * getResources().getDisplayMetrics().density)
                / Math.max(0.01f, scale);

        View dragged = windows[kind];
        float w = dragged.getMeasuredWidth() / Math.max(0.01f, scale);
        float h = dragged.getMeasuredHeight() / Math.max(0.01f, scale);

        float maxX = (getWidth() - dragged.getMeasuredWidth() - contentLeft)
                / Math.max(0.01f, scale);
        float maxY = (getHeight() - dragged.getMeasuredHeight() - contentTop)
                / Math.max(0.01f, scale);

        // Screen edges and centre
        posX[kind] = snapValue(posX[kind], 0f, maxX / 2f, maxX, threshold);
        posY[kind] = snapValue(posY[kind], 0f, maxY / 2f, maxY, threshold);

        // Other windows: align edges, butt up against them, line up lefts/tops
        for (int other = 0; other < windows.length; other++) {
            if (other == kind || windows[other].getVisibility() != VISIBLE) continue;
            View o = windows[other];
            float ow = o.getMeasuredWidth() / Math.max(0.01f, scale);
            float oh = o.getMeasuredHeight() / Math.max(0.01f, scale);

            posX[kind] = snapValue(posX[kind], posX[other], posX[other] + ow,
                    posX[other] + ow - w, posX[other] - w, threshold);
            posY[kind] = snapValue(posY[kind], posY[other], posY[other] + oh,
                    posY[other] + oh - h, posY[other] - h, threshold);
        }
    }

    private float snapValue(float value, float... candidates) {
        float threshold = candidates[candidates.length - 1];
        float best = value;
        float bestDistance = threshold + 1f;
        for (int i = 0; i < candidates.length - 1; i++) {
            float distance = Math.abs(candidates[i] - value);
            if (distance < bestDistance) {
                bestDistance = distance;
                best = candidates[i];
            }
        }
        return bestDistance <= threshold ? best : value;
    }

    private int windowAt(float x, float y) {
        for (int i = getChildCount() - 1; i >= 0; i--) {
            View child = getChildAt(i);
            if (child.getVisibility() != VISIBLE) continue;
            if (x >= child.getLeft() && x <= child.getRight()
                    && y >= child.getTop() && y <= child.getBottom()) {
                return kindOf(child);
            }
        }
        return -1;
    }

    private int kindOf(View child) {
        for (int i = 0; i < windows.length; i++) {
            if (windows[i] == child) return i;
        }
        return -1;
    }

    private boolean inTitleBar(int kind, float x, float y) {
        View child = windows[kind];
        if (child.getVisibility() != VISIBLE) return false;
        if (x < child.getLeft() || x > child.getRight()) return false;
        float titleSkin = (kind == PLAYLIST) ? SkinLayout.PL_TITLE_H : SkinLayout.TITLE_H;
        float limit = child.getTop() + titleSkin * scale;
        return y >= child.getTop() && y <= limit;
    }
}
