package com.tongyou.travel;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.SharedPreferences;
import android.content.res.Configuration;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.Consumer;

/** An optional foreground check, separate from startup, business APIs and WebView state. */
final class AppUpdates {
    interface Source { UpdateInfo fetch() throws Exception; }
    private final Activity activity;
    private final Source source;
    private final Consumer<String> download;
    private final SharedPreferences prefs;
    private final ExecutorService worker=Executors.newSingleThreadExecutor();
    private final Handler main=new Handler(Looper.getMainLooper());
    private boolean ready, resumed, closed, checking;
    private long nextCheck;
    private UpdateInfo pending;
    private AlertDialog dialog;

    AppUpdates(Activity activity, Source source, Consumer<String> download, SharedPreferences prefs) {
        this.activity=activity; this.source=source; this.download=download; this.prefs=prefs;
    }
    void onReady() { ready=true; check(); }
    void onResume() { resumed=true; showPending(); check(); }
    void onPause() { resumed=false; dismiss(); }
    void onAppearanceChanged() { dismiss(); showPending(); }
    void close() { closed=true; dismiss(); main.removeCallbacksAndMessages(null); worker.shutdownNow(); }

    private void check() {
        if(closed || !ready || !resumed || checking || SystemClock.elapsedRealtime()<nextCheck) return;
        checking=true;
        worker.execute(()-> {
            UpdateInfo info=null; boolean success=false;
            try { info=source.fetch(); success=true; } catch(Exception ignored) { /* Optional: preserve normal use offline. */ }
            final UpdateInfo result=info; final boolean fetched=success;
            main.post(()-> {
                if(closed) return;
                checking=false;
                nextCheck=SystemClock.elapsedRealtime()+(fetched?6*3600000L:5*60000L);
                if(result!=null && result.shouldOffer(BuildConfig.VERSION_CODE,Build.VERSION.SDK_INT,
                        prefs.getInt("deferred_code",0),prefs.getLong("deferred_until",0),System.currentTimeMillis())) {
                    pending=result; showPending();
                }
            });
        });
    }
    private void dismiss() { if(dialog!=null) { dialog.dismiss(); dialog=null; } }
    private void defer(UpdateInfo release) {
        prefs.edit().putInt("deferred_code",release.code).putLong("deferred_until",System.currentTimeMillis()+86400000L).apply();
        pending=null;
    }
    private void showPending() {
        if(closed || !ready || !resumed || pending==null || dialog!=null || activity.isFinishing() || activity.isDestroyed()) return;
        UpdateInfo release=pending;
        boolean dark=(activity.getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK)==Configuration.UI_MODE_NIGHT_YES;
        int theme=dark?android.R.style.Theme_Material_Dialog_Alert:android.R.style.Theme_Material_Light_Dialog_Alert;
        String size=String.format(Locale.CHINA,"%.1f MB",release.bytes/1048576.0);
        String notes=release.notes.trim().isEmpty()?"体验改进与问题修复":release.notes;
        dialog=new AlertDialog.Builder(activity,theme)
                .setTitle("发现新版本 "+release.version)
                .setMessage(notes+"\n\n安装包 "+size+"\n下载后按手机提示覆盖安装，无需卸载旧版。")
                .setPositiveButton("下载更新",(d,w)-> { pending=null; download.accept(release.url); })
                .setNegativeButton("稍后",(d,w)->defer(release))
                .setOnCancelListener(d->defer(release)).create();
        dialog.setOnDismissListener(d->{if(dialog==d)dialog=null;});
        dialog.show();
        int accent=android.graphics.Color.rgb(dark?123:37,dark?169:99,dark?255:235);
        dialog.getButton(AlertDialog.BUTTON_POSITIVE).setTextColor(accent);
        dialog.getButton(AlertDialog.BUTTON_NEGATIVE).setTextColor(accent);
    }

    static UpdateInfo parse(String raw) throws Exception {
        JSONObject m=new JSONObject(raw);
        if(m.getInt("schema_version")!=1 || !"Android".equals(m.getString("platform"))
                || !"com.tongyou.travel".equals(m.getString("application_id"))) throw new IOException("Wrong manifest");
        if(!m.getBoolean("enabled")) return null;
        // Reject coercion/truncation of version numbers rather than suggesting the wrong package.
        for(String field:new String[]{"version_code","min_sdk","bytes"})
            if(!m.get(field).toString().matches("[1-9][0-9]{0,9}")) throw new IOException("Invalid number");
        if(m.getLong("version_code")>Integer.MAX_VALUE || m.getLong("min_sdk")>100)
            throw new IOException("Number outside supported range");
        return new UpdateInfo(m.getInt("version_code"),m.getString("version"),m.getString("url"),
                m.getString("notes"),m.getLong("bytes"),m.getString("sha256"),m.getInt("min_sdk"));
    }
    static UpdateInfo fetchOfficial() throws Exception {
        HttpURLConnection connection=(HttpURLConnection)new URL(UpdateInfo.MANIFEST_URL).openConnection();
        try {
            connection.setConnectTimeout(5000); connection.setReadTimeout(5000);
            connection.setInstanceFollowRedirects(false); connection.setUseCaches(false);
            connection.setRequestProperty("Accept","application/json");
            connection.setRequestProperty("Cache-Control","no-cache");
            if(connection.getResponseCode()!=200) throw new IOException("No update metadata");
            try(InputStream in=connection.getInputStream()) { return parse(readManifest(in)); }
        } finally { connection.disconnect(); }
    }
    static String readManifest(InputStream in) throws IOException {
        ByteArrayOutputStream out=new ByteArrayOutputStream(); byte[] buffer=new byte[2048]; int n;
        while((n=in.read(buffer))!=-1) {
            if(out.size()+n>16384) throw new IOException("Manifest too large");
            out.write(buffer,0,n);
        }
        return out.toString(StandardCharsets.UTF_8.name());
    }
}
