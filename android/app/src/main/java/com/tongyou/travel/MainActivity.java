package com.tongyou.travel;

import android.annotation.SuppressLint;
import android.app.*;
import android.content.*;
import android.graphics.Color;
import android.net.*;
import android.os.*;
import android.print.PrintManager;
import android.provider.MediaStore;
import android.view.*;
import android.webkit.*;
import android.widget.*;
import androidx.core.content.FileProvider;
import androidx.core.graphics.Insets;
import androidx.core.view.*;
import androidx.webkit.*;
import org.json.*;
import java.io.*;
import java.util.*;
import java.util.concurrent.*;

/** The APK owns its UI snapshot; only API and user content reach the shared backend. */
public class MainActivity extends Activity {
    private static final int PICK_FILES = 41, SAVE_FILE = 42;
    WebView web;
    private WebView popup;
    private ScriptHandler appearanceScript;
    private LinearLayout popupContainer;
    private LinearLayout root;
    private FrameLayout stage;
    private TextView networkBanner;
    private ProgressBar progress;
    private View errorPanel;
    private LaunchOverlay launchOverlay;
    private final Handler launchHandler = new Handler(Looper.getMainLooper());
    private int launchGeneration;
    private String recoveryUrl=UrlPolicy.HOME;
    private final Runnable launchTimeout = () -> {
        if (launchOverlay != null && !isDestroyed()) showError("启动时间较长，请检查网络后重新加载。");
    };
    private ValueCallback<Uri[]> fileCallback;
    private File pendingFile;
    private String pendingMime;
    private boolean exporting;
    private long lastBack;
    private final Set<String> packaged = new HashSet<>();
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private ConnectivityManager connectivity;
    private ConnectivityManager.NetworkCallback networkCallback;
    AppUpdates updates;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        WindowCompat.setDecorFitsSystemWindows(getWindow(), false);
        root = new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL); root.setBackgroundColor(Color.rgb(239,243,255));
        ViewCompat.setOnApplyWindowInsetsListener(root, (v, insets) -> {
            Insets bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() | WindowInsetsCompat.Type.displayCutout());
            Insets ime = insets.getInsets(WindowInsetsCompat.Type.ime());
            v.setPadding(bars.left, bars.top, bars.right, Math.max(bars.bottom, ime.bottom));
            if (web != null) web.evaluateJavascript("document.documentElement?.classList.toggle('android-ime-open'," + insets.isVisible(WindowInsetsCompat.Type.ime()) + ")", null);
            return WindowInsetsCompat.CONSUMED;
        });
        setContentView(root);
        WindowCompat.getInsetsController(getWindow(), root).setAppearanceLightNavigationBars(true);
        if (Build.VERSION.SDK_INT >= 27) getWindow().setNavigationBarColor(Color.rgb(239,243,255));
        networkBanner = new TextView(this); networkBanner.setText("网络已断开，已填写内容会保留。联网后重试。");
        networkBanner.setTextColor(Color.rgb(115,70,12)); networkBanner.setBackgroundColor(Color.rgb(255,244,215));
        networkBanner.setPadding(dp(16),dp(8),dp(16),dp(8)); networkBanner.setVisibility(View.GONE); root.addView(networkBanner);
        progress = new ProgressBar(this,null,android.R.attr.progressBarStyleHorizontal); root.addView(progress,new LinearLayout.LayoutParams(-1,dp(2)));
        stage = new FrameLayout(this); root.addView(stage,new LinearLayout.LayoutParams(-1,0,1));
        showLaunch();
        try {
            JSONObject manifest = new JSONObject(readAsset("web-manifest.json"));
            manifest.keys().forEachRemaining(packaged::add);
        } catch (Exception e) { showFatal("安装包资源不完整，请重新安装。"); return; }
        android.content.pm.PackageInfo engine=WebView.getCurrentWebViewPackage();
        int engineMajor=0;
        try { if(engine!=null) engineMajor=Integer.parseInt(engine.versionName.split("\\.")[0]); } catch(Exception ignored) {}
        if (engineMajor<111 || !WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) {
            showFatal("请先更新手机的 Android System WebView 或系统浏览器，再打开 17同游。"); return;
        }
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);
        web = makeWebView(); stage.addView(web,0,new FrameLayout.LayoutParams(-1,-1));
        installAppearanceScript(); applyAppearance();
        // Debug fixtures never contact the public update service.
        updates=new AppUpdates(this, BuildConfig.DEBUG && getIntent().hasExtra("test_startup") ? ()->null : AppUpdates::fetchOfficial,
                this::openExternal,getSharedPreferences("app_updates",MODE_PRIVATE));
        installNetworkListener();
        if (Build.VERSION.SDK_INT >= 33) getOnBackInvokedDispatcher().registerOnBackInvokedCallback(android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT, this::handleBack);
        String initial = incoming(getIntent());
        if (state == null || web.restoreState(state) == null) web.loadUrl(initial == null ? UrlPolicy.HOME : initial);
        removeOldExports();
    }
    private void showLaunch() {
        launchGeneration++;
        launchHandler.removeCallbacks(launchTimeout);
        if (launchOverlay != null) { launchOverlay.animate().cancel(); stage.removeView(launchOverlay); }
        launchOverlay=new LaunchOverlay(this,darkAppearance());
        stage.addView(launchOverlay,new FrameLayout.LayoutParams(-1,-1));
        progress.setVisibility(View.GONE);
        launchHandler.postDelayed(launchTimeout,12000);
    }
    private void removeLaunch() {
        launchGeneration++;
        launchHandler.removeCallbacks(launchTimeout);
        if (launchOverlay != null) { launchOverlay.animate().cancel();stage.removeView(launchOverlay);launchOverlay=null; }
    }
    private void pageReady(WebView source) {
        if(source!=web || launchOverlay==null || errorPanel!=null) return;
        final int generation=launchGeneration;
        source.postVisualStateCallback(generation,new WebView.VisualStateCallback() {
            @Override public void onComplete(long id) {
                if(generation!=launchGeneration || launchOverlay==null || isDestroyed()) return;
                launchHandler.removeCallbacks(launchTimeout);
                progress.setVisibility(View.GONE);
                if(android.animation.ValueAnimator.areAnimatorsEnabled())
                    launchOverlay.animate().alpha(0).setDuration(180).withEndAction(()->{if(generation==launchGeneration){removeLaunch();if(updates!=null)updates.onReady();}}).start();
                else { removeLaunch();if(updates!=null)updates.onReady(); }
            }
        });
    }
    private boolean darkAppearance() {
        return (getResources().getConfiguration().uiMode & android.content.res.Configuration.UI_MODE_NIGHT_MASK) == android.content.res.Configuration.UI_MODE_NIGHT_YES;
    }
    private String appearanceJavascript() {
        String mode=darkAppearance()?"dark":"light";
        return "window.tongyouAndroidAppearance='"+mode+"';if(document.documentElement)document.documentElement.dataset.androidAppearance='"+mode+"';";
    }
    private void installAppearanceScript() {
        if(appearanceScript!=null) { appearanceScript.remove(); appearanceScript=null; }
        if(web!=null && WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT))
            appearanceScript=WebViewCompat.addDocumentStartJavaScript(web,appearanceJavascript(),Collections.singleton(UrlPolicy.ORIGIN));
    }
    private void applyAppearance() {
        boolean dark=darkAppearance();int background=dark?Color.rgb(13,17,27):Color.rgb(239,243,255);
        root.setBackgroundColor(background);
        if(launchOverlay!=null)launchOverlay.applyAppearance(dark);
        WindowCompat.getInsetsController(getWindow(),root).setAppearanceLightStatusBars(!dark);
        WindowCompat.getInsetsController(getWindow(),root).setAppearanceLightNavigationBars(!dark);
        getWindow().setStatusBarColor(background);
        if(Build.VERSION.SDK_INT>=27)getWindow().setNavigationBarColor(background);
        if(web!=null) { web.setBackgroundColor(background);web.evaluateJavascript(appearanceJavascript(),null); }
        if(errorPanel!=null) errorPanel.setBackgroundColor(background);
        if(errorPanel instanceof LinearLayout) {
            View title=((LinearLayout)errorPanel).getChildAt(0);
            if(title instanceof TextView) ((TextView)title).setTextColor(dark?Color.rgb(240,242,247):Color.rgb(25,35,53));
        }
        networkBanner.setTextColor(dark?Color.rgb(255,208,139):Color.rgb(115,70,12));
        networkBanner.setBackgroundColor(dark?Color.rgb(53,42,28):Color.rgb(255,244,215));
    }
    @Override public void onConfigurationChanged(android.content.res.Configuration configuration) {
        super.onConfigurationChanged(configuration);installAppearanceScript();applyAppearance();
        if(updates!=null)updates.onAppearanceChanged();
    }
    private static void copy(InputStream in,OutputStream out) throws IOException {
        byte[] buffer=new byte[16384]; int n;
        while((n=in.read(buffer))!=-1) out.write(buffer,0,n);
    }
    private int dp(int n) { return Math.round(n * getResources().getDisplayMetrics().density); }
    private String readAsset(String name) throws IOException {
        try (InputStream in=getAssets().open(name)) { ByteArrayOutputStream out=new ByteArrayOutputStream(); copy(in,out); return out.toString("UTF-8"); }
    }
    @SuppressLint("SetJavaScriptEnabled")
    private WebView makeWebView() {
        WebView view = new WebView(this);
        view.setBackgroundColor(Color.rgb(239,243,255));
        WebSettings s = view.getSettings();
        s.setJavaScriptEnabled(true); s.setDomStorageEnabled(true);
        s.setAllowFileAccess(false); s.setAllowContentAccess(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        s.setMediaPlaybackRequiresUserGesture(true); s.setSupportMultipleWindows(true);
        s.setJavaScriptCanOpenWindowsAutomatically(false);
        s.setUserAgentString(s.getUserAgentString()+" 17TongyouAndroid/"+BuildConfig.VERSION_NAME);
        CookieManager.getInstance().setAcceptCookie(true); CookieManager.getInstance().setAcceptThirdPartyCookies(view,false);
        if (WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) WebViewCompat.addWebMessageListener(view,"TongyouNative",Collections.singleton(UrlPolicy.ORIGIN), (v,message,origin,mainFrame,reply) -> {
            if (!mainFrame || !UrlPolicy.trustedOrigin(origin.toString())) return;
            onMessage(v,message.getData());
        });
        view.setWebViewClient(new WebViewClient() {
            @Override public WebResourceResponse shouldInterceptRequest(WebView v, WebResourceRequest req) {
                String url=req.getUrl().toString();
                if (!UrlPolicy.trustedOrigin(url) || !"GET".equals(req.getMethod())) return null;
                String path=req.getUrl().getPath();
                if (path == null) return null;
                if (BuildConfig.DEBUG && path.equals("/travel/__android_test__")) {
                    try { return response("text/html",getAssets().open("android-test.html")); } catch(IOException ignored) { return null; }
                }
                String key=(path.equals("/travel/") || path.equals("/travel")) ? "index.html" : path.startsWith("/travel/") ? path.substring(8) : "";
                if (!packaged.contains(key)) return null; // APIs are never intercepted or cached.
                try { return response(mime(key),getAssets().open("web/"+key)); }
                catch(IOException e) { return new WebResourceResponse("text/plain","UTF-8",500,"Missing asset",Collections.emptyMap(),new ByteArrayInputStream(new byte[0])); }
            }
            @Override public boolean shouldOverrideUrlLoading(WebView v,WebResourceRequest r) {
                String url=r.getUrl().toString();
                if (!r.isForMainFrame()) return !UrlPolicy.trustedOrigin(url);
                if (UrlPolicy.appPage(url)) return false;
                if (BuildConfig.DEBUG && UrlPolicy.trustedOrigin(url) && "/travel/__android_test__".equals(r.getUrl().getPath())) return false;
                if (r.hasGesture() || v == popup) { openExternal(url); if (v == popup) closePopup(); }
                return true;
            }
            @Override public void onPageStarted(WebView v,String url,android.graphics.Bitmap icon) {
                if (v == web) { if(UrlPolicy.appPage(url) || (BuildConfig.DEBUG && url.startsWith(UrlPolicy.HOME+"__android_test__"))) recoveryUrl=url; hideError(); showLaunch(); }
            }
            @Override public void onPageFinished(WebView v,String url) {
                if (v == web) { progress.setVisibility(View.GONE); applyAppearance(); }
                // Printing previews created with window.open/document.write do not run the React entry point.
                if (v == popup) v.evaluateJavascript("window.print=()=>TongyouNative.postMessage(JSON.stringify({type:'print',title:document.title}));",null);
            }
            @Override public void onReceivedError(WebView v,WebResourceRequest r,WebResourceError e) {
                if (r.isForMainFrame() && v == web) { showError("页面暂时无法打开，请检查网络后重试。"); }
            }
            @Override public void onReceivedHttpError(WebView v,WebResourceRequest r,WebResourceResponse response) {
                if (r.isForMainFrame() && v == web && response.getStatusCode() >= 400) { showError("服务暂时不可用，请稍后重试。"); }
            }
            @Override public boolean onRenderProcessGone(WebView v,RenderProcessGoneDetail detail) {
                if (v == popup) { closePopup(); return true; }
                stage.removeView(v); v.destroy(); web=null; showFatal("页面已暂停，请重新打开应用。"); return true;
            }
        });
        view.setWebChromeClient(new WebChromeClient() {
            @Override public void onProgressChanged(WebView v,int p) { if(v==web) progress.setProgress(p); }
            @Override public boolean onShowFileChooser(WebView v,ValueCallback<Uri[]> cb,FileChooserParams params) {
                if (!UrlPolicy.trustedOrigin(v.getUrl())) { cb.onReceiveValue(null); return true; }
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback=cb;
                Intent pick=new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*");
                String[] accept=Arrays.stream(params.getAcceptTypes()).filter(t->t.contains("/")).toArray(String[]::new);
                if (accept.length==1) pick.setType(accept[0]); else if(accept.length>1) pick.putExtra(Intent.EXTRA_MIME_TYPES,accept);
                pick.putExtra(Intent.EXTRA_ALLOW_MULTIPLE,params.getMode()==FileChooserParams.MODE_OPEN_MULTIPLE);
                try { startActivityForResult(pick,PICK_FILES); } catch(ActivityNotFoundException e) { fileCallback=null; cb.onReceiveValue(null); toast("手机没有可用的文件选择器"); }
                return true;
            }
            @Override public boolean onJsAlert(WebView v,String url,String msg,JsResult r) {
                new AlertDialog.Builder(MainActivity.this).setMessage(msg).setPositiveButton("确定",(d,w)->r.confirm()).setOnCancelListener(d->r.cancel()).show(); return true;
            }
            @Override public boolean onJsConfirm(WebView v,String url,String msg,JsResult r) {
                new AlertDialog.Builder(MainActivity.this).setMessage(msg).setPositiveButton("确定",(d,w)->r.confirm()).setNegativeButton("取消",(d,w)->r.cancel()).setOnCancelListener(d->r.cancel()).show(); return true;
            }
            @Override public boolean onJsPrompt(WebView v,String url,String msg,String value,JsPromptResult r) {
                EditText input=new EditText(MainActivity.this); input.setText(value);
                new AlertDialog.Builder(MainActivity.this).setMessage(msg).setView(input).setPositiveButton("确定",(d,w)->r.confirm(input.getText().toString())).setNegativeButton("取消",(d,w)->r.cancel()).setOnCancelListener(d->r.cancel()).show(); return true;
            }
            @Override public boolean onCreateWindow(WebView v,boolean dialog,boolean gesture,Message result) {
                if (!gesture || popup != null || !UrlPolicy.trustedOrigin(v.getUrl())) return false;
                String hit=v.getHitTestResult().getExtra();
                if (hit!=null && UrlPolicy.external(hit) && !UrlPolicy.appPage(hit)) { openExternal(hit); return false; }
                popup=makeWebView();
                popupContainer=new LinearLayout(MainActivity.this); popupContainer.setOrientation(LinearLayout.VERTICAL);
                popupContainer.setBackgroundColor(Color.WHITE);
                LinearLayout toolbar=new LinearLayout(MainActivity.this);
                Button close=new Button(MainActivity.this); close.setText("关闭预览"); close.setOnClickListener(b->closePopup()); toolbar.addView(close);
                Button print=new Button(MainActivity.this); print.setText("保存 PDF"); print.setOnClickListener(b->{ if(popup!=null) ((PrintManager)getSystemService(PRINT_SERVICE)).print("17同游旅行攻略",popup.createPrintDocumentAdapter("17同游旅行攻略"),null); }); toolbar.addView(print);
                popupContainer.addView(toolbar); popupContainer.addView(popup,new LinearLayout.LayoutParams(-1,0,1));
                stage.addView(popupContainer,new FrameLayout.LayoutParams(-1,-1));
                ((WebView.WebViewTransport)result.obj).setWebView(popup); result.sendToTarget(); return true;
            }
            @Override public void onCloseWindow(WebView v) { if(v==popup) closePopup(); }
        });
        view.setDownloadListener((url,ua,disposition,type,length)-> {
            if (!UrlPolicy.trustedOrigin(url)) { openExternal(url); return; }
            String name=URLUtil.guessFileName(url,disposition,type);
            view.evaluateJavascript("window.tongyouAndroidDownload?.("+JSONObject.quote(url)+","+JSONObject.quote(name)+")",null);
        });
        return view;
    }
    private WebResourceResponse response(String mime,InputStream in) {
        Map<String,String> headers=new HashMap<>(); headers.put("Cache-Control","no-store"); headers.put("X-Content-Type-Options","nosniff");
        return new WebResourceResponse(mime,"UTF-8",200,"OK",headers,in);
    }
    private String mime(String file) {
        if(file.endsWith(".js")) return "application/javascript";
        if(file.endsWith(".css")) return "text/css";
        if(file.endsWith(".html")) return "text/html";
        if(file.endsWith(".svg")) return "image/svg+xml";
        String result=MimeTypeMap.getSingleton().getMimeTypeFromExtension(MimeTypeMap.getFileExtensionFromUrl(file));
        return result==null?"application/octet-stream":result;
    }
    private void onMessage(WebView source,String raw) {
        if (raw==null || raw.length()>UrlPolicy.MAX_EXPORT_BYTES*1.4+4096) { toast("文件过大，请用网页版导出"); return; }
        try {
            JSONObject m=new JSONObject(raw);
            switch(m.optString("type")) {
                case "ready": pageReady(source); break;
                case "share": {
                    String text=m.optString("text"); if(text.length()>16000) return;
                    startActivity(Intent.createChooser(new Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT,text).putExtra(Intent.EXTRA_SUBJECT,m.optString("title","17同游")),"分享给朋友")); break;
                }
                case "message": toast(m.optString("text","请重试")); break;
                case "print": ((PrintManager)getSystemService(PRINT_SERVICE)).print("17同游旅行攻略",source.createPrintDocumentAdapter("17同游旅行攻略"),null); break;
                case "download": receiveFile(m); break;
                case "images": receiveImages(m); break;
                case "haptic": haptic(source,m.optString("kind")); break;
                default: break;
            }
        } catch(Exception e) { toast("操作未完成，请重试"); }
    }
    // performHapticFeedback 自带遵循系统「触感反馈」开关；CONFIRM/REJECT 是 API 30 才有的语义常量。
    private void haptic(WebView view,String kind) {
        boolean modern=Build.VERSION.SDK_INT>=Build.VERSION_CODES.R;
        int type;
        switch(kind) {
            case "confirm": type=modern?HapticFeedbackConstants.CONFIRM:HapticFeedbackConstants.VIRTUAL_KEY; break;
            case "reject": type=modern?HapticFeedbackConstants.REJECT:HapticFeedbackConstants.LONG_PRESS; break;
            case "tick": type=HapticFeedbackConstants.CLOCK_TICK; break;
            default: return;
        }
        view.performHapticFeedback(type);
    }
    private void receiveFile(JSONObject message) {
        if(exporting) { toast("请先完成上一个文件的保存或分享"); return; }
        exporting=true;
        io.execute(()-> {
            try {
                String data=message.getString("data"); int comma=data.indexOf(',');
                if(comma<0 || !data.startsWith("data:") || !data.substring(0,comma).endsWith(";base64")) throw new IOException();
                byte[] bytes=android.util.Base64.decode(data.substring(comma+1),android.util.Base64.DEFAULT);
                if(bytes.length>UrlPolicy.MAX_EXPORT_BYTES) throw new IOException();
                File folder=new File(getCacheDir(),"exports/"+UUID.randomUUID()); if(!folder.mkdirs()) throw new IOException();
                File file=new File(folder,UrlPolicy.safeName(message.optString("name")));
                try(FileOutputStream out=new FileOutputStream(file)) { out.write(bytes); }
                String type=message.optString("mime"); if(!type.matches("[a-zA-Z0-9.+-]+/[a-zA-Z0-9.+-]+")) type=mime(file.getName());
                final String finalType=type;
                runOnUiThread(()-> {
                    if(isFinishing() || isDestroyed()) { exporting=false; return; }
                    pendingFile=file; pendingMime=finalType;
                    new AlertDialog.Builder(this).setTitle(file.getName()).setItems(new String[]{"保存到手机","分享文件"},(d,which)-> {
                        if(which==0) {
                            Intent save=new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType(pendingMime).putExtra(Intent.EXTRA_TITLE,file.getName());
                            try { startActivityForResult(save,SAVE_FILE); } catch(ActivityNotFoundException e) { exporting=false; toast("没有可用的文件保存器"); }
                        } else { shareFile(file,finalType); exporting=false; }
                    }).setNegativeButton("取消",(d,w)->exporting=false).setOnCancelListener(d->exporting=false).show();
                });
            } catch(Exception e) { runOnUiThread(()-> { exporting=false; toast("文件导出失败，请重试"); }); }
        });
    }
    /** 计划单等多张图片一次交过来：全部存相册（Android 10+ 无需权限）或一起分享（ACTION_SEND_MULTIPLE）。 */
    private void receiveImages(JSONObject message) {
        if(exporting) { toast("请先完成上一个文件的保存或分享"); return; }
        exporting=true;
        io.execute(()-> {
            try {
                JSONArray items=message.getJSONArray("files");
                if(items.length()==0 || items.length()>20) throw new IOException();
                File folder=new File(getCacheDir(),"exports/"+UUID.randomUUID()); if(!folder.mkdirs()) throw new IOException();
                ArrayList<File> files=new ArrayList<>(); long total=0;
                for(int i=0;i<items.length();i++) {
                    JSONObject item=items.getJSONObject(i);
                    String data=item.getString("data"); int comma=data.indexOf(',');
                    if(comma<0 || !data.startsWith("data:image/png;base64")) throw new IOException();
                    byte[] bytes=android.util.Base64.decode(data.substring(comma+1),android.util.Base64.DEFAULT);
                    total+=bytes.length; if(total>UrlPolicy.MAX_EXPORT_BYTES*2L) throw new IOException();
                    File file=new File(folder,UrlPolicy.safeName(item.optString("name","17同游_"+(i+1)+".png")));
                    try(FileOutputStream out=new FileOutputStream(file)) { out.write(bytes); }
                    files.add(file);
                }
                runOnUiThread(()-> {
                    if(isFinishing() || isDestroyed()) { exporting=false; return; }
                    boolean gallery=Build.VERSION.SDK_INT>=Build.VERSION_CODES.Q;
                    String[] options=gallery?new String[]{"全部保存到相册","一起分享"}:new String[]{"一起分享"};
                    new AlertDialog.Builder(this).setTitle("共 "+files.size()+" 张图片").setItems(options,(d,which)-> {
                        if(gallery && which==0) saveImagesToGallery(files);
                        else { shareImages(files); exporting=false; }
                    }).setNegativeButton("取消",(d,w)->exporting=false).setOnCancelListener(d->exporting=false).show();
                });
            } catch(Exception e) { runOnUiThread(()-> { exporting=false; toast("图片导出失败，请重试"); }); }
        });
    }
    private void saveImagesToGallery(List<File> files) {
        io.execute(()-> {
            int saved=0;
            for(File file:files) {
                ContentValues values=new ContentValues();
                values.put(MediaStore.Images.Media.DISPLAY_NAME,file.getName());
                values.put(MediaStore.Images.Media.MIME_TYPE,"image/png");
                values.put(MediaStore.Images.Media.RELATIVE_PATH,Environment.DIRECTORY_PICTURES+"/17同游");
                values.put(MediaStore.Images.Media.IS_PENDING,1);
                Uri uri=getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI,values);
                if(uri==null) continue;
                try(OutputStream out=getContentResolver().openOutputStream(uri); InputStream in=new FileInputStream(file)) {
                    if(out==null) throw new IOException();
                    byte[] buffer=new byte[8192]; int n; while((n=in.read(buffer))>0) out.write(buffer,0,n);
                    values.clear(); values.put(MediaStore.Images.Media.IS_PENDING,0);
                    getContentResolver().update(uri,values,null,null); saved++;
                } catch(Exception e) { getContentResolver().delete(uri,null,null); }
            }
            final int count=saved;
            runOnUiThread(()-> { exporting=false; toast(count==files.size()?"已保存 "+count+" 张到相册":"保存了 "+count+" / "+files.size()+" 张，请重试"); });
        });
    }
    private void shareImages(List<File> files) {
        ArrayList<Uri> uris=new ArrayList<>();
        for(File file:files) uris.add(FileProvider.getUriForFile(this,BuildConfig.APPLICATION_ID+".files",file));
        Intent send=new Intent(Intent.ACTION_SEND_MULTIPLE).setType("image/png").putParcelableArrayListExtra(Intent.EXTRA_STREAM,uris).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        ClipData clip=ClipData.newRawUri("17同游计划单",uris.get(0));
        for(int i=1;i<uris.size();i++) clip.addItem(new ClipData.Item(uris.get(i)));
        send.setClipData(clip);
        try { startActivity(Intent.createChooser(send,"分享图片")); } catch(ActivityNotFoundException e) { toast("没有可用的分享应用"); }
    }
    private void shareFile(File file,String type) {
        Uri uri=FileProvider.getUriForFile(this,BuildConfig.APPLICATION_ID+".files",file);
        Intent send=new Intent(Intent.ACTION_SEND).setType(type).putExtra(Intent.EXTRA_STREAM,uri).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        send.setClipData(ClipData.newRawUri("17同游导出",uri));
        try { startActivity(Intent.createChooser(send,"分享文件")); } catch(ActivityNotFoundException e) { toast("没有可用的分享应用"); }
    }
    @Override protected void onActivityResult(int request,int result,Intent data) {
        super.onActivityResult(request,result,data);
        if(request==PICK_FILES && fileCallback!=null) {
            List<Uri> list=new ArrayList<>();
            if(result==RESULT_OK && data!=null) {
                if(data.getClipData()!=null) for(int i=0;i<data.getClipData().getItemCount();i++) list.add(data.getClipData().getItemAt(i).getUri());
                else if(data.getData()!=null) list.add(data.getData());
            }
            list.removeIf(u->!"content".equals(u.getScheme()));
            fileCallback.onReceiveValue(list.isEmpty()?null:list.toArray(new Uri[0])); fileCallback=null;
        }
        if(request==SAVE_FILE) {
            if(result==RESULT_OK && data!=null && data.getData()!=null && pendingFile!=null) {
                Uri dest=data.getData(); File source=pendingFile;
                io.execute(()-> {
                    try(InputStream in=new FileInputStream(source); OutputStream out=getContentResolver().openOutputStream(dest,"wt")) {
                        if(out==null) throw new IOException(); copy(in,out); runOnUiThread(()->toast("已保存到所选位置"));
                    } catch(Exception e) { runOnUiThread(()->toast("保存失败，请重新导出")); }
                    finally { runOnUiThread(()->exporting=false); }
                });
            } else exporting=false;
        }
    }
    private void openExternal(String url) {
        if (!UrlPolicy.external(url)) { toast("此链接暂不支持，请在浏览器中打开"); return; }
        // Explicitly select a browser so our own verified App Link cannot loop back into this Activity.
        Intent browserProbe=new Intent(Intent.ACTION_VIEW,Uri.parse("https://example.com")).addCategory(Intent.CATEGORY_BROWSABLE);
        java.util.List<android.content.pm.ResolveInfo> browsers=getPackageManager().queryIntentActivities(browserProbe,0);
        java.util.List<Intent> targets=new java.util.ArrayList<>();
        for(android.content.pm.ResolveInfo info:browsers) {
            String pkg=info.activityInfo.packageName;
            if(pkg.equals(getPackageName())) continue;
            targets.add(new Intent(Intent.ACTION_VIEW,Uri.parse(url)).addCategory(Intent.CATEGORY_BROWSABLE).setPackage(pkg));
        }
        if(targets.isEmpty()) { toast("没有可用的浏览器"); return; }
        try {
            Intent chooser=Intent.createChooser(targets.remove(0),"在浏览器打开");
            if(!targets.isEmpty()) chooser.putExtra(Intent.EXTRA_INITIAL_INTENTS,targets.toArray(new Intent[0]));
            startActivity(chooser);
        } catch(ActivityNotFoundException e) { toast("没有可用的浏览器"); }
    }
    private String incoming(Intent intent) {
        if(BuildConfig.DEBUG && intent.hasExtra("test_startup")) {
            String mode=intent.getStringExtra("test_startup");
            if(Arrays.asList("normal","slow","stalled","offline","guest").contains(mode))
                return UrlPolicy.HOME+"__android_test__?startup="+mode;
        }
        String url=intent.getDataString();
        if (Intent.ACTION_SEND.equals(intent.getAction())) {
            String text=intent.getStringExtra(Intent.EXTRA_TEXT);
            if(text!=null) { java.util.regex.Matcher m=java.util.regex.Pattern.compile("https://17tongyou\\.com/(?:travel/|t/)[^\\s<>\"，。]*").matcher(text); if(m.find()) url=m.group(); }
        }
        return url!=null && UrlPolicy.appPage(url)?url:null;
    }
    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent); setIntent(intent); String link=incoming(intent);
        if(link!=null && web!=null) new AlertDialog.Builder(this).setMessage("打开收到的同游链接？当前未保存的输入可能丢失。").setPositiveButton("打开",(d,w)->{closePopup();web.loadUrl(link);}).setNegativeButton("取消",null).show();
        else if(Intent.ACTION_SEND.equals(intent.getAction()) || intent.getData()!=null) toast("请分享 17同游的行程或账本链接");
    }
    @Override public void onBackPressed() { handleBack(); }
    void handleBack() {
        WindowInsetsCompat insets=ViewCompat.getRootWindowInsets(root);
        if(insets!=null && insets.isVisible(WindowInsetsCompat.Type.ime())) { new WindowInsetsControllerCompat(getWindow(),root).hide(WindowInsetsCompat.Type.ime()); return; }
        if(popup!=null) { closePopup(); return; }
        if(web==null) { finish(); return; }
        web.evaluateJavascript("Boolean(window.tongyouAndroidBack && window.tongyouAndroidBack())",value-> {
            if("true".equals(value)) { lastBack=0; return; }
            // React panels own back navigation; URL/hash history is not a reliable page stack.
            long now=SystemClock.elapsedRealtime();
            if(now-lastBack<2000) moveTaskToBack(true);
            else { lastBack=now; toast("再按一次返回退出 17同游"); }
        });
    }
    private void closePopup() { if(popup!=null) { stage.removeView(popupContainer); popupContainer.removeView(popup); popup.destroy(); popup=null; popupContainer=null; } }
    private void showFatal(String text) { showError(text); }
    private void showError(String text) {
        removeLaunch(); hideError(); progress.setVisibility(View.GONE);
        LinearLayout panel=new LinearLayout(this); panel.setOrientation(LinearLayout.VERTICAL); panel.setGravity(Gravity.CENTER); panel.setPadding(dp(24),dp(24),dp(24),dp(24)); panel.setBackgroundColor(Color.rgb(239,243,255));
        TextView title=new TextView(this); title.setText(text); title.setTextSize(18); title.setGravity(Gravity.CENTER); panel.addView(title);
        Button retry=new Button(this); retry.setText("重新加载"); retry.setOnClickListener(v->{if(web!=null){hideError();web.loadUrl(recoveryUrl);}else recreate();}); panel.addView(retry);
        Button browser=new Button(this); browser.setText("用浏览器打开"); browser.setOnClickListener(v->openExternal(UrlPolicy.HOME)); panel.addView(browser);
        stage.addView(panel,new FrameLayout.LayoutParams(-1,-1)); errorPanel=panel;
        applyAppearance();
    }
    private void hideError() { if(errorPanel!=null) { stage.removeView(errorPanel); errorPanel=null; } }
    private void toast(String text) { Toast.makeText(this,text,Toast.LENGTH_LONG).show(); }
    private void installNetworkListener() {
        connectivity=(ConnectivityManager)getSystemService(CONNECTIVITY_SERVICE);
        networkCallback=new ConnectivityManager.NetworkCallback() {
            @Override public void onAvailable(Network n) { updateConnection(); }
            @Override public void onLost(Network n) { updateConnection(); }
            @Override public void onCapabilitiesChanged(Network n,NetworkCapabilities c) { updateConnection(); }
        };
        connectivity.registerDefaultNetworkCallback(networkCallback); updateConnection();
    }
    private void updateConnection() {
        NetworkCapabilities c=connectivity.getNetworkCapabilities(connectivity.getActiveNetwork());
        boolean online=c!=null && c.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET);
        runOnUiThread(()-> {
            if(isDestroyed()) return;
            networkBanner.setVisibility(online?View.GONE:View.VISIBLE);
            if(web!=null) web.evaluateJavascript("window.dispatchEvent(new Event('"+(online?"online":"offline")+"'))",null);
        });
    }
    private void removeOldExports() {
        io.execute(()-> {
            File[] dirs=new File(getCacheDir(),"exports").listFiles(); if(dirs==null) return;
            for(File dir:dirs) if(System.currentTimeMillis()-dir.lastModified()>86400000L) {
                File[] files=dir.listFiles(); if(files!=null) for(File f:files) f.delete(); dir.delete();
            }
        });
    }
    @Override protected void onSaveInstanceState(Bundle out) { super.onSaveInstanceState(out); if(web!=null) web.saveState(out); }
    @Override protected void onResume() { super.onResume(); if(web!=null) { web.onResume(); web.evaluateJavascript("window.dispatchEvent(new Event('focus'))",null); } if(updates!=null)updates.onResume(); }
    @Override protected void onPause() { if(updates!=null)updates.onPause(); if(web!=null) web.onPause(); CookieManager.getInstance().flush(); super.onPause(); }
    @Override protected void onDestroy() {
        if(updates!=null)updates.close();
        launchHandler.removeCallbacksAndMessages(null);removeLaunch();
        if(networkCallback!=null) connectivity.unregisterNetworkCallback(networkCallback);
        if(fileCallback!=null) fileCallback.onReceiveValue(null);
        closePopup(); if(web!=null) { stage.removeView(web); web.destroy(); }
        io.shutdown(); super.onDestroy();
    }
}
