package com.wacup.wake;

import android.app.Activity;
import android.app.KeyguardManager;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;

/**
 * Invisible trampoline. Nothing is drawn: it asks the keyguard to dismiss itself
 * (which shows the PIN/fingerprint bouncer if the device has a secure lock) and
 * then opens the target app, so the user never sees the home screen.
 */
public class LaunchActivity extends Activity {

    private boolean handled = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true);
            setTurnScreenOn(true);
        }

        KeyguardManager km = (KeyguardManager) getSystemService(KEYGUARD_SERVICE);
        if (km != null && km.isKeyguardLocked()) {
            km.requestDismissKeyguard(this, new KeyguardManager.KeyguardDismissCallback() {
                @Override
                public void onDismissSucceeded() {
                    launchAndFinish();
                }

                @Override
                public void onDismissError() {
                    // No bouncer available (e.g. swipe-only lock): try anyway.
                    launchAndFinish();
                }

                @Override
                public void onDismissCancelled() {
                    handled = true;
                    finish();
                }
            });
            return;
        }

        launchAndFinish();
    }

    private void launchAndFinish() {
        if (handled) return;
        handled = true;

        String pkg = Prefs.targetPackage(this);
        if (!pkg.isEmpty()) {
            try {
                Intent launch = getPackageManager().getLaunchIntentForPackage(pkg);
                if (launch != null) {
                    launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                            | Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED);
                    startActivity(launch);
                }
            } catch (Exception ignored) {
                // Target app uninstalled or disabled — nothing sensible to do.
            }
        }
        finish();
        overridePendingTransition(0, 0);
    }
}
