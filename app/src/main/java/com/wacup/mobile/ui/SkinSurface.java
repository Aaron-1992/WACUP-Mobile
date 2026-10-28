package com.wacup.mobile.ui;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.PorterDuff;
import android.graphics.PorterDuffColorFilter;
import android.view.View;

import com.wacup.mobile.skin.Skin;
import com.wacup.mobile.skin.SkinPaint;

/**
 * Base for every skin-painted window: holds the skin, the sprite font helper and
 * the render scale (skin pixels -> device pixels).
 */
public abstract class SkinSurface extends View {

    protected Skin skin;
    protected SkinPaint skinPaint;
    protected float scale = 1f;

    protected final Paint plain = new Paint();
    protected final Paint green = new Paint();
    protected final Paint tint = new Paint();

    public SkinSurface(Context context) {
        super(context);
        setWillNotDraw(false);
        green.setColor(0xFF00F800);
        green.setFilterBitmap(false);
        plain.setFilterBitmap(false);
        tint.setFilterBitmap(false);
        setSkin(Skin.base());
    }

    public void setSkin(Skin newSkin) {
        this.skin = newSkin;
        this.skinPaint = new SkinPaint(newSkin);
        requestLayout();
        invalidate();
    }

    public Skin getSkin() {
        return skin;
    }

    public void setScale(float newScale) {
        this.scale = newScale;
        requestLayout();
        invalidate();
    }

    public float scale() {
        return scale;
    }

    /** Colour filter used for the "pressed" and "dimmed" sprite variants. */
    protected void setTint(Integer color) {
        if (color == null) {
            tint.setColorFilter(null);
        } else {
            tint.setColorFilter(new PorterDuffColorFilter(color, PorterDuff.Mode.SRC_ATOP));
        }
    }

    protected Paint spritePaint(boolean tinted) {
        return tinted ? tint : plain;
    }

    protected void drawBackground(Canvas c, int width, int height, boolean haveMain) {
        if (haveMain && skin.main != null) {
            c.drawBitmap(skin.main, 0, 0, plain);
        } else {
            plain.setColor(0xFF232323);
            c.drawRect(0, 0, width, height, plain);
        }
    }
}
