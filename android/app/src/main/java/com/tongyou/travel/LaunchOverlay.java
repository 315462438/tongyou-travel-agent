package com.tongyou.travel;

import android.animation.ValueAnimator;
import android.content.Context;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.view.Gravity;
import android.view.View;
import android.widget.*;

/** Native first frame: available before the WebView engine or bundled JS starts. */
final class LaunchOverlay extends FrameLayout {
    private final LinearLayout brand;
    private final TextView title, subtitle, status;

    LaunchOverlay(Context context, boolean dark) {
        super(context);
        setContentDescription("17同游正在启动");setTag("tongyou-launch");
        setClickable(true); // Do not let taps pass through into a half-ready page.
        setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_YES);
        brand=new LinearLayout(context); brand.setOrientation(LinearLayout.VERTICAL); brand.setGravity(Gravity.CENTER);
        ImageView icon=new ImageView(context); icon.setImageResource(R.drawable.ic_launcher);
        brand.addView(icon,new LinearLayout.LayoutParams(dp(72),dp(72)));
        title=text("17同游",26); title.setTypeface(null,android.graphics.Typeface.BOLD);
        LinearLayout.LayoutParams name=new LinearLayout.LayoutParams(-2,-2);name.topMargin=dp(22);brand.addView(title,name);
        subtitle=text("一起规划，一起出发",14);
        LinearLayout.LayoutParams slogan=new LinearLayout.LayoutParams(-2,-2);slogan.topMargin=dp(8);brand.addView(subtitle,slogan);
        FrameLayout.LayoutParams center=new FrameLayout.LayoutParams(-1,-2,Gravity.CENTER);center.bottomMargin=dp(48);addView(brand,center);
        status=text("正在准备你的旅程…",12);
        FrameLayout.LayoutParams bottom=new FrameLayout.LayoutParams(-1,-2,Gravity.BOTTOM|Gravity.CENTER_HORIZONTAL);bottom.bottomMargin=dp(40);addView(status,bottom);
        applyAppearance(dark);
    }
    private int dp(int n) { return Math.round(n*getResources().getDisplayMetrics().density); }
    private TextView text(String value,int size) { TextView v=new TextView(getContext());v.setText(value);v.setTextSize(size);v.setGravity(Gravity.CENTER);return v; }
    void applyAppearance(boolean dark) {
        setBackground(new GradientDrawable(GradientDrawable.Orientation.TL_BR,dark
            ?new int[]{Color.rgb(21,37,73),Color.rgb(13,17,27),Color.rgb(27,24,47)}
            :new int[]{Color.rgb(226,235,255),Color.rgb(245,247,252),Color.rgb(239,235,250)}));
        title.setTextColor(dark?Color.rgb(240,242,247):Color.rgb(28,39,60));
        subtitle.setTextColor(dark?Color.rgb(163,176,201):Color.rgb(100,115,139));
        status.setTextColor(dark?Color.rgb(138,154,183):Color.rgb(117,131,152));
    }
    @Override protected void onAttachedToWindow() {
        super.onAttachedToWindow();
        if(ValueAnimator.areAnimatorsEnabled()) {
            brand.setAlpha(0.45f);brand.setTranslationY(dp(8));brand.setScaleX(.97f);brand.setScaleY(.97f);
            brand.animate().alpha(1).translationY(0).scaleX(1).scaleY(1).setDuration(420).start();
        }
    }
    @Override protected void onDetachedFromWindow() { brand.animate().cancel();animate().cancel();super.onDetachedFromWindow(); }
}
