package com.wacup.mobile;

import android.app.Activity;
import android.os.Bundle;
import android.widget.TextView;

public class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        TextView tv = new TextView(this);
        tv.setText("WACUP Mobile\n\nbuild pipeline check");
        tv.setTextSize(22);
        tv.setPadding(48, 48, 48, 48);
        setContentView(tv);
    }
}
