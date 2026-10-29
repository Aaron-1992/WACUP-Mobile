package com.wacup.mobile;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Log;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStreamWriter;
import java.io.Writer;

/**
 * Last-resort crash recorder.
 *
 * The app cannot phone home, so a crash is written to shared preferences (shown on
 * the next launch) and to a text file next to the app's data. That turns "it won't
 * open" into a stack trace the user can read out or screenshot.
 */
public final class CrashLog {

    private static final String PREFS = "wacup_crash";
    private static final String KEY_LAST = "last_crash";
    private static final String TAG = "WacupCrash";

    private CrashLog() { }

    static void install(final Context context) {
        final Thread.UncaughtExceptionHandler previous =
                Thread.getDefaultUncaughtExceptionHandler();

        Thread.setDefaultUncaughtExceptionHandler(new Thread.UncaughtExceptionHandler() {
            @Override
            public void uncaughtException(Thread thread, Throwable error) {
                try {
                    record(context, error);
                } catch (Throwable ignored) {
                    // never mask the original crash
                }
                if (previous != null) {
                    previous.uncaughtException(thread, error);
                } else {
                    android.os.Process.killProcess(android.os.Process.myPid());
                    System.exit(10);
                }
            }
        });
    }

    private static void record(Context context, Throwable error) {
        StringBuilder text = new StringBuilder();
        text.append(error.toString()).append('\n');
        for (StackTraceElement element : error.getStackTrace()) {
            text.append("    at ").append(element.toString()).append('\n');
        }
        Throwable cause = error.getCause();
        while (cause != null) {
            text.append("Caused by: ").append(cause.toString()).append('\n');
            for (StackTraceElement element : cause.getStackTrace()) {
                text.append("    at ").append(element.toString()).append('\n');
            }
            cause = cause.getCause();
        }
        String report = text.toString();
        Log.e(TAG, report);

        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        prefs.edit().putString(KEY_LAST, report).apply();

        File dir = context.getExternalFilesDir(null);
        if (dir == null) dir = context.getFilesDir();
        Writer writer = null;
        try {
            File file = new File(dir, "last-crash.txt");
            writer = new OutputStreamWriter(new FileOutputStream(file), "UTF-8");
            writer.write(report);
        } catch (Exception ignored) {
            // storage may be unavailable; preferences already hold the report
        } finally {
            if (writer != null) try { writer.close(); } catch (Exception ignored) { }
        }
    }

    /** Returns the previous crash and clears it, or null. */
    static String takeLastCrash(Context context) {
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        String report = prefs.getString(KEY_LAST, null);
        if (report != null) {
            prefs.edit().remove(KEY_LAST).apply();
        }
        return report;
    }
}
