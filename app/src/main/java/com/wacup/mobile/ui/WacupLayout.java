package com.wacup.mobile.ui;

import android.content.Context;
import android.view.View;
import android.view.ViewGroup;

/**
 * Places the three windows in skin coordinates and picks the largest integer-ish
 * scale that fits the screen. Playlist goes beside the main window on wide screens
 * (landscape/tablet) and below it on phones.
 */
public class WacupLayout extends ViewGroup {

    private static final int SKIN_MAIN_W = 275;
    private static final int SKIN_MAIN_H = 116;
    private static final int SKIN_EQ_H = 116;
    private static final int SKIN_GAP = 6;

    private final MainWindowView mainWindow;
    private final EqWindowView eqWindow;
    private final PlaylistWindowView playlistWindow;

    private boolean sideBySide;
    private boolean eqVisible;
    private boolean playlistVisible = true;
    private int playlistSkinHeight = 116;

    public WacupLayout(Context context, MainWindowView main, EqWindowView eq,
                       PlaylistWindowView playlist) {
        super(context);
        this.mainWindow = main;
        this.eqWindow = eq;
        this.playlistWindow = playlist;

        addView(main);
        addView(eq);
        addView(playlist);
        eq.setVisibility(GONE);
    }

    public void setEqVisible(boolean visible) {
        eqVisible = visible;
        eqWindow.setVisibility(visible ? VISIBLE : GONE);
        requestLayout();
    }

    public boolean isEqVisible() {
        return eqVisible;
    }

    public void setPlaylistVisible(boolean visible) {
        playlistVisible = visible;
        playlistWindow.setVisibility(visible ? VISIBLE : GONE);
        requestLayout();
    }

    public boolean isPlaylistVisible() {
        return playlistVisible;
    }

    public void setPlaylistSkinHeight(int skinHeight) {
        this.playlistSkinHeight = skinHeight;
        requestLayout();
    }

    @Override
    protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
        int width = MeasureSpec.getSize(widthMeasureSpec);
        int height = MeasureSpec.getSize(heightMeasureSpec);
        if (width == 0 || height == 0) {
            super.onMeasure(widthMeasureSpec, heightMeasureSpec);
            return;
        }

        float density = getResources().getDisplayMetrics().density;
        float pad = 6f * density;

        boolean canBeSideBySide = width > 2.2f * SKIN_MAIN_W * density * 0.65f;
        sideBySide = playlistVisible && canBeSideBySide;

        float skinWidth = sideBySide ? (SKIN_MAIN_W + SKIN_GAP + SKIN_MAIN_W) : SKIN_MAIN_W;
        float skinHeight = SKIN_MAIN_H
                + (eqVisible ? SKIN_GAP + SKIN_EQ_H : 0)
                + ((!sideBySide && playlistVisible) ? SKIN_GAP + playlistSkinHeight : 0);

        float scale = Math.min((width - 2 * pad) / skinWidth, (height - 2 * pad) / skinHeight);
        scale = Math.max(0.55f, Math.min(3.2f, scale));

        mainWindow.setScale(scale);
        eqWindow.setScale(scale);
        playlistWindow.setScale(scale);

        int childWidthSpec = MeasureSpec.makeMeasureSpec(0, MeasureSpec.UNSPECIFIED);
        int childHeightSpec = MeasureSpec.makeMeasureSpec(0, MeasureSpec.UNSPECIFIED);
        mainWindow.measure(childWidthSpec, childHeightSpec);
        eqWindow.measure(childWidthSpec, childHeightSpec);
        playlistWindow.measure(childWidthSpec, childHeightSpec);

        setMeasuredDimension(width, height);
    }

    @Override
    protected void onLayout(boolean changed, int l, int t, int r, int b) {
        int width = getWidth();
        int height = getHeight();
        float density = getResources().getDisplayMetrics().density;
        float pad = 6f * density;

        int mainW = mainWindow.getMeasuredWidth();
        int mainH = mainWindow.getMeasuredHeight();
        int gap = (int) (SKIN_GAP * mainWindow.scale());

        int totalWidth = mainW + (sideBySide ? gap + playlistWindow.getMeasuredWidth() : 0);
        int totalHeight = mainH
                + (eqVisible ? gap + eqWindow.getMeasuredHeight() : 0)
                + ((!sideBySide && playlistVisible) ? gap + playlistWindow.getMeasuredHeight() : 0);

        int startX = Math.max((int) pad, (width - totalWidth) / 2);
        int startY = Math.max((int) pad, (height - totalHeight) / 2);

        mainWindow.layout(startX, startY, startX + mainW, startY + mainH);

        int y = startY + mainH + gap;
        if (eqVisible) {
            eqWindow.layout(startX, y, startX + eqWindow.getMeasuredWidth(),
                    y + eqWindow.getMeasuredHeight());
            y += eqWindow.getMeasuredHeight() + gap;
        }

        if (playlistVisible) {
            if (sideBySide) {
                int x = startX + mainW + gap;
                playlistWindow.layout(x, startY, x + playlistWindow.getMeasuredWidth(),
                        startY + playlistWindow.getMeasuredHeight());
            } else {
                playlistWindow.layout(startX, y, startX + playlistWindow.getMeasuredWidth(),
                        y + playlistWindow.getMeasuredHeight());
            }
        }
    }
}
