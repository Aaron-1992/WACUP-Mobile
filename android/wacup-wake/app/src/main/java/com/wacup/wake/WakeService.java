package com.wacup.wake;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import android.os.SystemClock;

/**
 * Foreground service that listens for ACTION_SCREEN_ON and hands off to
 * {@link LaunchActivity}, which dismisses the keyguard and starts the target app.
 *
 * ACTION_SCREEN_ON is a protected broadcast: it does not work from a manifest
 * receiver, hence the live registration here.
 */
public class WakeService extends Service {

    private static final String CHANNEL_ID = "wake";
    private static final int NOTIFICATION_ID = 42;
    private static final long DEBOUNCE_MS = 2500L;

    private long lastLaunchElapsed = 0L;
    private boolean receiverRegistered = false;

    private final BroadcastReceiver screenOnReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            if (intent != null && Intent.ACTION_SCREEN_ON.equals(intent.getAction())) {
                maybeLaunch();
            }
        }
    };

    @Override
    public void onCreate() {
        super.onCreate();
        createChannel();

        IntentFilter filter = new IntentFilter(Intent.ACTION_SCREEN_ON);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(screenOnReceiver, filter, Context.RECEIVER_NOT_EXPORTED);
        } else {
            registerReceiver(screenOnReceiver, filter);
        }
        receiverRegistered = true;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        Notification notification = buildNotification();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(NOTIFICATION_ID, notification,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        } else {
            startForeground(NOTIFICATION_ID, notification);
        }
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        if (receiverRegistered) {
            try {
                unregisterReceiver(screenOnReceiver);
            } catch (Exception ignored) {
                // already gone
            }
            receiverRegistered = false;
        }
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private void maybeLaunch() {
        if (!Prefs.enabled(this)) return;
        if (Prefs.targetPackage(this).isEmpty()) return;

        long now = SystemClock.elapsedRealtime();
        if (now - lastLaunchElapsed < DEBOUNCE_MS) return;   // screen-on fires more than once
        lastLaunchElapsed = now;

        Intent launch = new Intent(this, LaunchActivity.class);
        launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_NO_ANIMATION);
        try {
            startActivity(launch);
        } catch (Exception ignored) {
            // Background activity start blocked: the overlay permission has not been granted.
        }
    }

    private void createChannel() {
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm == null) return;
        if (nm.getNotificationChannel(CHANNEL_ID) == null) {
            NotificationChannel channel = new NotificationChannel(
                    CHANNEL_ID,
                    getString(R.string.channel_name),
                    NotificationManager.IMPORTANCE_MIN);
            channel.setShowBadge(false);
            channel.setSound(null, null);
            nm.createNotificationChannel(channel);
        }
    }

    private Notification buildNotification() {
        Intent open = new Intent(this, MainActivity.class);
        PendingIntent pi = PendingIntent.getActivity(
                this, 0, open,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);

        return new Notification.Builder(this, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.ic_media_play)
                .setContentTitle(getString(R.string.notification_title))
                .setContentText(getString(R.string.notification_text))
                .setContentIntent(pi)
                .setOngoing(true)
                .build();
    }
}
