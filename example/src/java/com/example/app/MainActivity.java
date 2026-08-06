package com.example.app;

import android.app.Activity;
import android.os.Bundle;
import android.widget.TextView;

public class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        TextView tv = new TextView(this);
        tv.setText("Hello from termux-builder!");
        tv.setTextSize(24f);
        tv.setPadding(32, 32, 32, 32);
        setContentView(tv);
    }
}
