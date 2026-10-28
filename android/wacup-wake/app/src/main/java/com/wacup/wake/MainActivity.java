package com.wacup.wake;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.PowerManager;
import android.provider.Settings;
import android.view.View;
import android.widget.TextView;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;

/** Setup screen: pick the target app (Winlator), grant the two permissions, arm it. */
public class MainActivity extends Activity {

    private TextView targetLabel;
    private TextView status;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        targetLabel = findViewById(R.id.target_label);
        status = findViewById(R.id.status);

        findViewById(R.id.pick_app).setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { pickApp(); }
        });

        findViewById(R.id.toggle).setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { toggle(); }
        });

        findViewById(R.id.overlay_perm).setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) {
                startActivity(new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                        Uri.parse("package:" + getPackageName())));
            }
        });

        findViewById(R.id.battery).setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) {
                try {
                    startActivity(new Intent(
                            Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                            Uri.parse("package:" + getPackageName())));
                } catch (Exception e) {
                    startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS));
                }
            }
        });

        findViewById(R.id.test).setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { testNow(); }
        });
    }

    @Override
    protected void onResume() {
        super.onResume();
        refresh();
        requestNotificationPermissionIfNeeded();
    }

    private void refresh() {
        String pkg = Prefs.targetPackage(this);
        if (pkg.isEmpty()) {
            targetLabel.setText("No app chosen yet");
        } else {
            targetLabel.setText("Target: " + Prefs.targetLabel(this) + "\n" + pkg);
        }

        status.setText((Prefs.enabled(this) ? "ARMED — screen on opens your app" : "Disarmed")
                + "\n\n• display over other apps: "
                + (Prefs.canDrawOverlays(this) ? "granted" : "NOT granted (required)")
                + "\n• battery optimisation: "
                + (isIgnoringBattery() ? "ignored" : "still optimised (can be killed)")
                + "\n• notifications: " + (canNotify() ? "allowed" : "blocked"));
    }

    private boolean isIgnoringBattery() {
        PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
        return pm != null && pm.isIgnoringBatteryOptimizations(getPackageName());
    }

    private boolean canNotify() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return true;
        return checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS)
                == PackageManager.PERMISSION_GRANTED;
    }

    private void requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && !canNotify()) {
            requestPermissions(new String[]{android.Manifest.permission.POST_NOTIFICATIONS}, 1);
        }
    }

    private void pickApp() {
        final PackageManager pm = getPackageManager();
        Intent main = new Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER);
        List<ResolveInfo> infos = pm.queryIntentActivities(main, 0);

        final List<ResolveInfo> items = new ArrayList<>(infos);
        Collections.sort(items, new Comparator<ResolveInfo>() {
            @Override public int compare(ResolveInfo a, ResolveInfo b) {
                return a.loadLabel(pm).toString().compareToIgnoreCase(b.loadLabel(pm).toString());
            }
        });

        if (items.isEmpty()) {
            toast("No launchable apps found");
            return;
        }

        String[] labels = new String[items.size()];
        for (int i = 0; i < items.size(); i++) {
            labels[i] = items.get(i).loadLabel(pm) + "\n" + items.get(i).activityInfo.packageName;
        }

        new AlertDialog.Builder(this)
                .setTitle("Open this on screen wake")
                .setItems(labels, new DialogInterface.OnClickListener() {
                    @Override public void onClick(DialogInterface dialog, int which) {
                        ResolveInfo ri = items.get(which);
                        Prefs.setTarget(MainActivity.this,
                                ri.activityInfo.packageName,
                                ri.loadLabel(pm).toString());
                        refresh();
                    }
                })
                .setNegativeButton("Cancel", null)
                .show();
    }

    private void toggle() {
        if (Prefs.enabled(this)) {
            Prefs.setEnabled(this, false);
            stopService(new Intent(this, WakeService.class));
            refresh();
            return;
        }

        if (Prefs.targetPackage(this).isEmpty()) {
            toast("Pick an app first");
            return;
        }
        if (!Prefs.canDrawOverlays(this)) {
            toast("Grant \"display over other apps\" first");
            startActivity(new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:" + getPackageName())));
            return;
        }
        if (!canNotify()) {
            toast("Allow notifications, the service needs one");
            requestNotificationPermissionIfNeeded();
        }
        if (!isIgnoringBattery()) {
            toast("Tip: also ignore battery optimisation for reliability");
        }

        Prefs.setEnabled(this, true);
        startForegroundService(new Intent(this, WakeService.class));
        refresh();
    }

    private void testNow() {
        if (Prefs.targetPackage(this).isEmpty()) {
            toast("Pick an app first");
            return;
        }
        startActivity(new Intent(this, LaunchActivity.class));
    }

    private void toast(String message) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show();
    }
}
