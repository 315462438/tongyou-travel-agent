package com.tongyou.travel;

import android.content.Intent;
import android.os.SystemClock;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.rule.ActivityTestRule;
import androidx.test.uiautomator.*;
import org.junit.*;
import org.junit.runner.RunWith;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;
import java.io.File;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class HostInstrumentedTest {
    @Rule public ActivityTestRule<MainActivity> rule=new ActivityTestRule<>(MainActivity.class,false,false);
    private MainActivity activity;
    private UiDevice device;
    private String js(String script) throws Exception {
        CountDownLatch latch=new CountDownLatch(1); AtomicReference<String> result=new AtomicReference<>();
        InstrumentationRegistry.getInstrumentation().runOnMainSync(()->activity.web.evaluateJavascript(script,v->{result.set(v);latch.countDown();}));
        assertTrue("JS callback",latch.await(10,TimeUnit.SECONDS));return result.get();
    }
    private void tapWeb(String selector) throws Exception {
        device.waitForIdle();
        String quoted=org.json.JSONObject.quote(selector);
        org.json.JSONObject r=new org.json.JSONObject(js("(()=>{const r=document.querySelector("+quoted+").getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,w:innerWidth}})()"));
        int[] origin=new int[2]; InstrumentationRegistry.getInstrumentation().runOnMainSync(()->activity.web.getLocationOnScreen(origin));
        double scale=activity.web.getWidth()/r.getDouble("w");
        device.click(origin[0]+(int)(r.getDouble("x")*scale),origin[1]+(int)(r.getDouble("y")*scale));
    }
    private void until(String expression) throws Exception {
        long deadline=SystemClock.elapsedRealtime()+15000;
        while(SystemClock.elapsedRealtime()<deadline) {if("true".equals(js("Boolean("+expression+")"))) return;SystemClock.sleep(100);}
        fail("Timed out: "+expression+"; DOM="+js("document.body.innerText.slice(0,500)"));
    }
    @Before public void launch() throws Exception {
        activity=rule.launchActivity(new Intent(Intent.ACTION_MAIN).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_ACTIVITY_CLEAR_TASK).putExtra("test_startup","normal"));
        device=UiDevice.getInstance(InstrumentationRegistry.getInstrumentation());
        until("window.fixtureReady && document.querySelector('.mobile-bottom-nav')");
        launchFinished();
    }
    @After public void finishCurrentActivity() {
        if(activity!=null)InstrumentationRegistry.getInstrumentation().runOnMainSync(()->{if(!activity.isDestroyed())activity.finish();});
    }
    @Test public void packagedAppBridgeBackAndPersistence() throws Exception {
        assertEquals("true",js("document.documentElement.classList.contains('native-android')"));
        js("[...document.querySelectorAll('.mobile-bottom-nav button')].find(x=>x.innerText.includes('记账')).click()");until("document.querySelector('.ledger-book')");
        js("document.querySelector('button[aria-label=\"＋ 新建账本\"]').click()");until("document.querySelector('[role=dialog]')");
        tapWeb("[role=dialog] input");
        until("document.documentElement.classList.contains('android-ime-open')");
        assertEquals("\"none\"",js("getComputedStyle(document.querySelector('.mobile-bottom-nav')).display"));
        js("document.querySelector('[role=dialog] input').value='测试账本'; document.querySelector('[role=dialog] .ledger-actions').scrollIntoView({block:'end'})");
        assertEquals("true",js("(()=>{const e=document.querySelector('[role=dialog] .ledger-actions button');const r=e.getBoundingClientRect();return r.height>=44&&r.bottom<=innerHeight&&e.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))})()"));
        device.waitForIdle();SystemClock.sleep(400);
        device.takeScreenshot(new File(activity.getExternalFilesDir(null),"android-keyboard.png"));
        device.pressBack();until("!document.documentElement.classList.contains('android-ime-open')");
        assertEquals("true",js("!!document.querySelector('[role=dialog]')"));
        device.pressBack();until("!document.querySelector('[role=dialog]')");assertEquals("true",js("!!document.querySelector('.ledger-shell')"));
        device.pressBack();until("!document.querySelector('.ledger-shell')");
        js("localStorage.setItem('android_persist_check','retained');location.reload()");until("window.fixtureReady && document.querySelector('.mobile-bottom-nav')");
        assertEquals("\"retained\"",js("localStorage.getItem('android_persist_check')"));
        device.waitForIdle();SystemClock.sleep(400);
        device.takeScreenshot(new File(activity.getExternalFilesDir(null),"android-home.png"));
    }
    @Test public void tripWorkspaceLayoutAndSystemBack() throws Exception {
        js("[...document.querySelectorAll('.mobile-bottom-nav button')].find(x=>x.innerText==='行程').click()");until("document.querySelector('.trip-card')");
        js("document.querySelector('.trip-card').click()");until("document.querySelector('.android-trip-stop')");
        assertEquals("true",js("(()=>{const e=document.querySelector('.android-trip-stop'),r=e.getBoundingClientRect();return r.bottom<=innerHeight && document.documentElement.scrollWidth<=innerWidth})()"));
        assertEquals("\"none\"",js("getComputedStyle(document.querySelector('.mobile-bottom-nav')).display"));
        device.waitForIdle();SystemClock.sleep(400);
        device.takeScreenshot(new File(activity.getExternalFilesDir(null),"android-trip.png"));
        js("document.querySelector('[aria-label=\"行程更多操作\"]').click()");until("document.querySelector('.android-trip-sheet')");
        device.pressBack();until("!document.querySelector('.android-trip-sheet')");
        assertEquals("true",js("!!document.querySelector('.android-trip-board')"));
        js("document.querySelector('[aria-label^=\"编辑 西湖\"]').click()");until("document.querySelector('.trip-edit-modal')");
        tapWeb(".trip-edit-modal input");
        until("document.documentElement.classList.contains('android-ime-open')");
        js("document.querySelector('.trip-edit-footer').scrollIntoView({block:'end'})");
        assertEquals("true",js("(()=>{const r=document.querySelector('.trip-edit-footer').getBoundingClientRect();return r.bottom<=innerHeight+1})()"));
        device.waitForIdle();SystemClock.sleep(400);
        device.takeScreenshot(new File(activity.getExternalFilesDir(null),"android-trip-keyboard.png"));
        device.pressBack();until("!document.documentElement.classList.contains('android-ime-open')");
        device.pressBack();until("!document.querySelector('.trip-edit-modal')");
        device.pressBack();until("document.querySelector('.trip-list-page')");
        assertEquals("true",js("getComputedStyle(document.querySelector('.mobile-bottom-nav')).display!=='none'"));
    }
    @Test public void homepageCompositionAndAppearance() throws Exception {
        device.executeShellCommand("cmd uimode night no");
        until("document.documentElement.dataset.androidAppearance==='light'");
        assertEquals("true",js("document.querySelector('.unified-submit').disabled"));
        assertEquals("true",js("document.querySelector('.unified-start').getBoundingClientRect().height<=180"));
        device.waitForIdle();SystemClock.sleep(400);
        device.takeScreenshot(new File(activity.getExternalFilesDir(null),"android-home-light.png"));
        js("(()=>{const e=document.querySelector('.unified-idea textarea');Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(e,'厦门三天');e.dispatchEvent(new Event('input',{bubbles:true}))})()");
        until("!document.querySelector('.unified-submit').disabled");
        try {
            device.executeShellCommand("cmd uimode night yes");
            until("document.documentElement.dataset.androidAppearance==='dark'");
            assertEquals("\"厦门三天\"",js("document.querySelector('.unified-idea textarea').value"));
            assertEquals("\"rgb(240, 242, 247)\"",js("getComputedStyle(document.querySelector('.unified-idea textarea')).color"));
            device.waitForIdle();SystemClock.sleep(400);
            device.takeScreenshot(new File(activity.getExternalFilesDir(null),"android-home-dark.png"));
        } finally { device.executeShellCommand("cmd uimode night no"); }
        until("document.documentElement.dataset.androidAppearance==='light'");
        assertEquals("\"厦门三天\"",js("document.querySelector('.unified-idea textarea').value"));
    }
    private boolean launching() {
        java.util.concurrent.atomic.AtomicBoolean value=new java.util.concurrent.atomic.AtomicBoolean();
        InstrumentationRegistry.getInstrumentation().runOnMainSync(()->value.set(activity.getWindow().getDecorView().findViewWithTag("tongyou-launch")!=null));
        return value.get();
    }
    private void launchFinished() {
        long deadline=SystemClock.elapsedRealtime()+15000;
        while(launching() && SystemClock.elapsedRealtime()<deadline)SystemClock.sleep(50);
        assertFalse("Native launch layer must leave",launching());
    }
    @Test public void startupWaitsForReactAndRecoversFromTimeout() throws Exception {
        js("sessionStorage.removeItem('startup_stall_seen')");
        InstrumentationRegistry.getInstrumentation().runOnMainSync(()->activity.web.loadUrl(UrlPolicy.HOME+"__android_test__?startup=slow"));
        SystemClock.sleep(600);assertTrue("PageFinished must not remove launch before React",launching());
        device.takeScreenshot(new File(activity.getExternalFilesDir(null),"android-startup-light.png"));
        until("document.querySelector('.mobile-bottom-nav')");launchFinished();
        InstrumentationRegistry.getInstrumentation().runOnMainSync(()->activity.web.loadUrl(UrlPolicy.HOME+"__android_test__?startup=stalled"));
        assertTrue(device.wait(Until.hasObject(By.text("重新加载")),16000));
        assertFalse("Timeout exposes recovery instead of empty page",launching());
        device.findObject(By.text("重新加载")).click();
        until("document.querySelector('.mobile-bottom-nav')");launchFinished();
        assertEquals("true",js("location.search.includes('startup=stalled')"));
    }
    @Test public void startupGuestAndConnectionFailureAreReadyScreens() throws Exception {
        InstrumentationRegistry.getInstrumentation().runOnMainSync(()->activity.web.loadUrl(UrlPolicy.HOME+"__android_test__?startup=offline"));
        until("document.body.innerText.includes('重新连接')");launchFinished();
        assertEquals("\"android-instrumentation\"",js("localStorage.getItem('travel_token')"));
        InstrumentationRegistry.getInstrumentation().runOnMainSync(()->activity.web.loadUrl(UrlPolicy.HOME+"__android_test__?startup=guest"));
        until("document.querySelector('input[type=password]')");launchFinished();
    }
    @Test public void startupDarkAndWarmResumeKeepsDraft() throws Exception {
        try {
            device.executeShellCommand("cmd uimode night yes");
            InstrumentationRegistry.getInstrumentation().runOnMainSync(()->activity.web.loadUrl(UrlPolicy.HOME+"__android_test__?startup=slow"));
            SystemClock.sleep(600);assertTrue(launching());
            device.takeScreenshot(new File(activity.getExternalFilesDir(null),"android-startup-dark.png"));
            until("document.querySelector('.unified-idea textarea')");launchFinished();
            js("(()=>{const e=document.querySelector('.unified-idea textarea');Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(e,'保留旅程草稿');e.dispatchEvent(new Event('input',{bubbles:true}));window.startupMarker='same-document'})()");
            device.pressHome();SystemClock.sleep(300);
            activity.startActivity(new Intent(activity,MainActivity.class).setAction(Intent.ACTION_MAIN).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_ACTIVITY_SINGLE_TOP));
            device.waitForIdle();
            assertFalse("Warm resume must not replay splash",launching());
            assertEquals("\"same-document\"",js("window.startupMarker"));
            assertEquals("\"保留旅程草稿\"",js("document.querySelector('.unified-idea textarea').value"));
        } finally {device.executeShellCommand("cmd uimode night no");}
    }
    @Test public void startupRecreationWithoutAnimations() throws Exception {
        String scale=device.executeShellCommand("settings get global animator_duration_scale").trim();
        try {
            device.executeShellCommand("settings put global animator_duration_scale 0");
            js("localStorage.setItem('startup_restore','kept')");
            InstrumentationRegistry.getInstrumentation().runOnMainSync(()->activity.recreate());
            long deadline=SystemClock.elapsedRealtime()+10000;
            MainActivity previous=activity;
            while(activity==previous && SystemClock.elapsedRealtime()<deadline) {
                InstrumentationRegistry.getInstrumentation().runOnMainSync(()->{
                    for(android.app.Activity a:androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry.getInstance().getActivitiesInStage(androidx.test.runner.lifecycle.Stage.RESUMED))
                        if(a instanceof MainActivity)activity=(MainActivity)a;
                });SystemClock.sleep(100);
            }
            assertNotSame(previous,activity);
            until("document.querySelector('.mobile-bottom-nav')");launchFinished();
            assertEquals("\"kept\"",js("localStorage.getItem('startup_restore')"));
        } finally {device.executeShellCommand("settings put global animator_duration_scale "+scale);}
    }
    @Test public void allModuleColorsFollowSystemAndKeepNavigation() throws Exception {
        try {
            device.executeShellCommand("cmd uimode night yes");
            until("document.documentElement.dataset.androidAppearance==='dark'");
            String[] tabs={"行程","记账","历史","同游圈"};
            String[] labels={".trip-card-title",".ledger-book h2",".mobile-history-row strong",".relay-card>p"};
            for(int i=0;i<tabs.length;i++) {
                js("[...document.querySelectorAll('.mobile-bottom-nav button')].find(x=>x.innerText==='"+tabs[i]+"').click()");
                // Empty history fixtures are allowed; the page title must still inherit night mode.
                String selector=i==2?".mobile-page-header h1":labels[i];
                until("document.querySelector('"+selector+"')");
                assertEquals("\"rgb(240, 242, 247)\"",js("getComputedStyle(document.querySelector('"+selector+"')).color"));
                assertEquals("true",js("document.documentElement.scrollWidth<=innerWidth"));
            }
            SystemClock.sleep(300);device.takeScreenshot(new File(activity.getExternalFilesDir(null),"android-modules-social-dark.png"));
            assertEquals("true",js("document.querySelector('.android-relay-actions').getBoundingClientRect().height>=44"));
            device.executeShellCommand("cmd uimode night no");until("document.documentElement.dataset.androidAppearance==='light'");
            assertEquals("\"rgb(25, 35, 53)\"",js("getComputedStyle(document.querySelector('.relay-card>p')).color"));
            device.pressBack();until("!document.querySelector('.social-overlay')");
        } finally { device.executeShellCommand("cmd uimode night no"); }
    }
    @Test public void exportIsDecodedByNativeHost() throws Exception {
        device.executeShellCommand("rm -f /sdcard/Download/android-export.txt");
        js("(()=>{const a=document.createElement('a');a.download='android-export.txt';a.href=URL.createObjectURL(new Blob(['android export test'],{type:'text/plain'}));a.click();URL.revokeObjectURL(a.href)})()");
        assertTrue(device.wait(Until.hasObject(By.text("保存到手机")),10000));
        File[] dirs=new File(activity.getCacheDir(),"exports").listFiles();assertNotNull(dirs);
        boolean found=false;
        for(File dir:dirs){File f=new File(dir,"android-export.txt");if(f.exists()) {assertEquals("android export test",new String(java.nio.file.Files.readAllBytes(f.toPath()),java.nio.charset.StandardCharsets.UTF_8));found=true;}}
        assertTrue(found);device.findObject(By.text("保存到手机")).click();
        UiObject2 save=device.wait(Until.findObject(By.text(java.util.regex.Pattern.compile("(?i)save|保存"))),10000);
        assertNotNull("System document save action",save);save.click();
        long deadline=SystemClock.elapsedRealtime()+5000;String saved="";
        while(SystemClock.elapsedRealtime()<deadline) {saved=device.executeShellCommand("cat /sdcard/Download/android-export.txt").trim();if(saved.equals("android export test"))break;SystemClock.sleep(100);}
        assertEquals("android export test",saved);
    }
    @Test public void filePickerAndExternalIframeIsolation() throws Exception {
        js("(()=>{const i=document.createElement('input');i.id='file-test';i.type='file';i.accept='image/*';i.onchange=async()=>window.uploadResult=await i.files[0].text();document.body.prepend(i);const b=document.createElement('button');b.innerText='上传测试';b.style='position:fixed;top:0;left:0;z-index:99999;height:60px';b.onclick=()=>i.click();document.body.append(b)})()");
        // Click through the real input so Android's document picker receives a user gesture.
        device.wait(Until.findObject(By.text("上传测试")),5000).click();
        assertTrue(device.wait(Until.hasObject(By.pkg("com.google.android.documentsui")),5000) || device.wait(Until.hasObject(By.pkg("com.android.documentsui")),5000));
        File folder=new File(activity.getCacheDir(),"exports/picker-test");folder.mkdirs();
        File picked=new File(folder,"picked.png");java.nio.file.Files.write(picked.toPath(),"upload fixture".getBytes(java.nio.charset.StandardCharsets.UTF_8));
        android.net.Uri pickedUri=androidx.core.content.FileProvider.getUriForFile(activity,BuildConfig.APPLICATION_ID+".files",picked);
        InstrumentationRegistry.getInstrumentation().runOnMainSync(()->activity.onActivityResult(41,android.app.Activity.RESULT_OK,new Intent().setData(pickedUri)));
        device.pressBack();until("window.uploadResult==='upload fixture'");
        js("window.frameResult='waiting';window.addEventListener('message',e=>window.frameResult=e.data);const frame=document.createElement('iframe');frame.sandbox='allow-scripts';frame.srcdoc='<script>parent.postMessage(typeof TongyouNative,\"*\")<\\/script>';document.body.append(frame)");
        until("window.frameResult==='undefined'");
    }
    @Test public void printPreviewUsesSystemPdfFlow() throws Exception {
        js("(()=>{const b=document.createElement('button');b.innerText='预览测试';b.style='position:fixed;top:0;left:0;z-index:99999;height:60px';b.onclick=()=>{const w=window.open('','_blank');w.document.write('<html><body><h1>旅行攻略 PDF 测试</h1></body></html>');w.document.close()};document.body.append(b)})()");
        device.wait(Until.findObject(By.text("预览测试")),5000).click();
        assertTrue(device.wait(Until.hasObject(By.text("保存 PDF")),5000));
        device.findObject(By.text("保存 PDF")).click();
        assertTrue(device.wait(Until.hasObject(By.pkg("com.android.printspooler")),10000));
        device.pressBack();device.pressBack();
        until("document.querySelector('.mobile-bottom-nav')");
    }
}
