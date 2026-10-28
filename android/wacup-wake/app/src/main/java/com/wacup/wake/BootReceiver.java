package com.wacup.wake;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

/** Re-arms the screen-on listener after a reboot or an app update. */
public class BootReceiver extends BroadcastReceiver {

    @Override
    public void onReceive(Context context, Intent intent) {
        if (context == null || intent == null) return;
        if (!Prefs.enabled(context)) return;
        if (Prefs.targetPackage(context).isEmpty()) return;

        Intent service = new Intent(context, WakeService.class);
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(service);
            } else {
                context.startService(service);
            }
        } catch (Exception ignored) {
            // Android 12+ can refuse background FGS starts; the tile/main screen re-arms it.
        }
    }
}
