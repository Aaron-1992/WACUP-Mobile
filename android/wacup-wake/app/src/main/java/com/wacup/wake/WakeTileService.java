package com.wacup.wake;

import android.app.PendingIntent;
import android.content.Intent;
import android.os.Build;
import android.service.quicksettings.Tile;
import android.service.quicksettings.TileService;

/** Quick Settings toggle — tap to arm/disarm from the notification shade. */
public class WakeTileService extends TileService {

    @Override
    public void onStartListening() {
        super.onStartListening();
        updateTile();
    }

    @Override
    public void onClick() {
        super.onClick();

        if (Prefs.enabled(this)) {
            Prefs.setEnabled(this, false);
            stopService(new Intent(this, WakeService.class));
            updateTile();
            return;
        }

        // Not configured yet: send the user to the setup screen (which needs an
        // unlocked device anyway).
        if (Prefs.targetPackage(this).isEmpty() || !Prefs.canDrawOverlays(this)) {
            Intent setup = new Intent(this, MainActivity.class);
            setup.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
                PendingIntent pi = PendingIntent.getActivity(this, 0, setup,
                        PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
                startActivityAndCollapse(pi);
            } else {
                startActivityAndCollapse(setup);
            }
            return;
        }

        Prefs.setEnabled(this, true);
        startForegroundService(new Intent(this, WakeService.class));
        updateTile();
    }

    private void updateTile() {
        Tile tile = getQsTile();
        if (tile == null) return;
        tile.setState(Prefs.enabled(this) ? Tile.STATE_ACTIVE : Tile.STATE_INACTIVE);
        tile.setLabel(getString(R.string.tile_label));
        tile.updateTile();
    }
}
