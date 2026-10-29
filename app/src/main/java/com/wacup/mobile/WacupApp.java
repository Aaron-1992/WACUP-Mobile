package com.wacup.mobile;

import android.app.Application;

/** Registers the crash recorder before any activity is created. */
public class WacupApp extends Application {

    @Override
    public void onCreate() {
        super.onCreate();
        CrashLog.install(this);
    }
}
