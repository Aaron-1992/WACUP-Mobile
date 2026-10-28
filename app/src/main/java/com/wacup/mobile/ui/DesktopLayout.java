package com.wacup.mobile.ui;

import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Canvas;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;

/**
 * Free-floating windows, the way Winamp actually behaves: each window can be moved
 * independently, raised to the front, hidden, and rolled up (windowshade).
 *
 * Positions are kept in skin coordinates and persisted, so a layout survives
 * rotation, restarts and re-installs of the same data.
 */
public class DesktopLayout extends ViewGroup {

    public static final int MAIN = 0;
    public static final int EQ = 1;
    public static final int PLAYLIST = 2;

    private static final int SKIN_MAIN_W = 275;
    private static final int SKIN_MAIN_H = 116;
    private static final int SKIN_TITLE_H = 14;
    private static final int SKIN_PL_TITLE_H = 20;
    private static final float STACK_H = 360f;     // three windows stacked, skin px

    private static final String PREFS = "wacup_windows";
    private static final long DOUBLE_TAP_MS = 320L;

    public interface Listener {
        /** Single tap on a title bar: open that window's menu. */
        void onTitleTap(int kind);

        /** Double tap on a title bar: roll the window up / down. */
        void onToggleShade(int kind);

        void onWindowMoved();
    }

    private final View[] windows = new View[3];
    private final float[] posX = new float[3];
    private final float[] posY = new float[3];
    private final boolean[] shown = {true, false, true};
    private final boolean[] shaded = new boolean[3];

    private final SharedPreferences prefs;
    private Listener listener;

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
        posX[MAIN] = prefs.getFloat("x0", 0f);
        posY[MAIN] = prefs.getFloat("y0", 0f);
        posX[EQ] = prefs.getFloat("x1", 0f);
        posY[EQ] = prefs.getFloat("y1", SKIN_MAIN_H + 6f);
        posX[PLAYLIST] = prefs.getFloat("x2", 0f);
        posY[PLAYLIST] = prefs.getFloat("y2", (SKIN_MAIN_H + 6f) * 2);

        shown[EQ] = prefs.getBoolean("show1", false);
        shaded[MAIN] = prefs.getBoolean("shade0", false);
        eq.setVisibility(shown[EQ] ? VISIBLE : GONE);
        playlist.setVisibility(shown[PLAYLIST] ? VISIBLE : GONE);
        if (main instanceof MainWindowView) {
            ((MainWindowView) main).setShaded(shaded[MAIN]);
        }
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
        if (kind == MAIN) {
            ((MainWindowView) windows[MAIN]).setShaded(on);
        }
        prefs.edit().putBoolean("shade" + kind, on).apply();
        requestLayout();
    }

    public boolean isShaded(int kind) {
        return shaded[kind];
    }

    /** Puts every window back to its default place. */
    public void resetPositions() {
        posX[MAIN] = 0;
        posY[MAIN] = 0;
        posX[EQ] = 0;
        posY[EQ] = SKIN_MAIN_H + 6f;
        posX[PLAYLIST] = 0;
        posY[PLAYLIST] = (SKIN_MAIN_H + 6f) * 2;
        persistPositions();
        requestLayout();
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

        float fitW = (width - 2 * pad) / SKIN_MAIN_W;
        float fitH = (height - 2 * pad) / STACK_H;
        scale = Math.max(0.5f, Math.min(4f, Math.min(fitW, fitH)));

        int spec = MeasureSpec.makeMeasureSpec(0, MeasureSpec.UNSPECIFIED);
        for (View child : windows) {
            if (child instanceof SkinSurface) {
                ((SkinSurface) child).setScale(scale);
            }
            child.measure(spec, spec);
        }

        contentLeft = (width - SKIN_MAIN_W * scale) / 2f;
        contentTop = (height - STACK_H * scale) / 2f;
        if (contentTop < pad) contentTop = pad;

        setMeasuredDimension(width, height);
    }

    /** Converts a skin-space x to a pixel x. */
    private float px(float skinX) {
        return contentLeft + skinX * scale;
    }

    private float py(float skinY) {
        return contentTop + skinY * scale;
    }

    @Override
    protected void onLayout(boolean changed, int l, int t, int r, int b) {
        int width = getWidth();
        int height = getHeight();

        for (int kind = 0; kind < windows.length; kind++) {
            View child = windows[kind];
            int cw = child.getMeasuredWidth();
            int chh = child.getMeasuredHeight();

            float maxX = Math.max(0, (width - cw - contentLeft) / Math.max(0.01f, scale));
            float maxY = Math.max(0, (height - chh - contentTop) / Math.max(0.01f, scale));
            posX[kind] = Math.max(0, Math.min(maxX, posX[kind]));
            posY[kind] = Math.max(0, Math.min(maxY, posY[kind]));

            int x = Math.round(px(posX[kind]));
            int y = Math.round(py(posY[kind]));
            child.layout(x, y, x + cw, y + chh);
        }
    }

    @Override
    protected void dispatchDraw(Canvas canvas) {
        // Windows are drawn in child order; bringToFront() on touch handles stacking.
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
                if (Math.abs(dx) > 2 || Math.abs(dy) > 2) dragMoved = true;
                posX[dragKind] = dragOriginX + dx;
                posY[dragKind] = dragOriginY + dy;
                requestLayout();
                return true;
            }

            case MotionEvent.ACTION_UP: {
                if (!dragMoved) {
                    long now = System.currentTimeMillis();
                    lastTapTime = now;
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
        float titleSkin = (kind == PLAYLIST) ? SKIN_PL_TITLE_H : SKIN_TITLE_H;
        float limit = child.getTop() + titleSkin * scale;
        return y >= child.getTop() && y <= limit;
    }
}
