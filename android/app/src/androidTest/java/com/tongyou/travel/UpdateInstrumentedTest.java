package com.tongyou.travel;

import android.content.Intent;
import android.content.SharedPreferences;
import android.os.SystemClock;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.rule.ActivityTestRule;
import androidx.test.uiautomator.*;
import org.json.JSONObject;
import org.junit.*;
import org.junit.runner.RunWith;
import java.io.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class UpdateInstrumentedTest {
    @Rule public ActivityTestRule<MainActivity> rule=new ActivityTestRule<>(MainActivity.class,false,false);
    private MainActivity activity;
    private UiDevice device;
    private SharedPreferences prefs;
    private final AtomicReference<String> downloaded=new AtomicReference<>();
    private void ui(Runnable r) { InstrumentationRegistry.getInstrumentation().runOnMainSync(r); }
    private String js(String script) throws Exception {
        CountDownLatch latch=new CountDownLatch(1);AtomicReference<String> result=new AtomicReference<>();
        ui(()->activity.web.evaluateJavascript(script,v->{result.set(v);latch.countDown();}));
        assertTrue(latch.await(10,TimeUnit.SECONDS));return result.get();
    }
    private UpdateInfo release() { return new UpdateInfo(10,"0.7.0","https://17tongyou.com/downloads/android/0.7.0-10/17tongyou-android-0.7.0-10.apk","更新测试：跟随系统外观",3000000,"a".repeat(64),26); }
    private void install(AppUpdates.Source source,boolean foreground) {
        ui(()-> {
            activity.updates.close();
            activity.updates=new AppUpdates(activity,source,downloaded::set,prefs);
            activity.updates.onReady();
            if(foreground)activity.updates.onResume();
        });
    }
    private void prompt() { assertTrue(device.wait(Until.hasObject(By.text("发现新版本 0.7.0")),5000)); }
    @Before public void before() throws Exception {
        device=UiDevice.getInstance(InstrumentationRegistry.getInstrumentation());
        device.executeShellCommand("cmd uimode night no");
        activity=rule.launchActivity(new Intent(Intent.ACTION_MAIN).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_ACTIVITY_CLEAR_TASK).putExtra("test_startup","normal"));
        long until=SystemClock.elapsedRealtime()+15000;
        while(!"true".equals(js("Boolean(document.querySelector('.mobile-bottom-nav'))")) && SystemClock.elapsedRealtime()<until)SystemClock.sleep(100);
        assertEquals("true",js("Boolean(document.querySelector('.mobile-bottom-nav'))"));
        // Wait for the native first frame transition before replacing its optional checker.
        SystemClock.sleep(300);
        prefs=activity.getSharedPreferences("update_test",0);prefs.edit().clear().commit();
    }
    @After public void after() throws Exception {
        ui(()->{if(activity!=null&&!activity.isDestroyed())activity.finish();});
        device.executeShellCommand("cmd uimode night no");
    }
    @Test public void parseRejectsUnsafeBrokenAndOversizedMetadata() throws Exception {
        JSONObject m=new JSONObject().put("schema_version",1).put("enabled",true).put("platform","Android")
                .put("application_id","com.tongyou.travel").put("version_code",10).put("version","0.7.0")
                .put("url",release().url).put("bytes",3000000).put("sha256","a".repeat(64)).put("notes","改进体验").put("min_sdk",26);
        assertEquals(10,AppUpdates.parse(m.toString()).code);
        for(Object[] replacement:new Object[][]{{"application_id","other"},{"platform","iOS"},{"schema_version",2},
                {"url","https://evil.test/a.apk"},{"version_code",9999999999L},{"version_code",10.5},{"sha256","bad"}}) {
            JSONObject bad=new JSONObject(m.toString()).put((String)replacement[0],replacement[1]);
            assertThrows(Exception.class,()->AppUpdates.parse(bad.toString()));
        }
        assertNull(AppUpdates.parse(new JSONObject(m.toString()).put("enabled",false).toString()));
        assertThrows(Exception.class,()->AppUpdates.parse("<html>unavailable</html>"));
        assertThrows(IOException.class,()->AppUpdates.readManifest(new ByteArrayInputStream(new byte[16385])));
        assertEquals(m.toString(),AppUpdates.readManifest(new ByteArrayInputStream(m.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8))));
    }
    @Test public void laterPersistsAndDoesNotRepeatOnResumeOrRestart() throws Exception {
        AtomicInteger calls=new AtomicInteger();install(()->{calls.incrementAndGet();return release();},true);prompt();
        device.findObject(By.text("稍后")).click();
        assertTrue(device.wait(Until.gone(By.text("发现新版本 0.7.0")),2000));
        assertEquals(10,prefs.getInt("deferred_code",0));assertTrue(prefs.getLong("deferred_until",0)>System.currentTimeMillis());
        ui(()->{activity.updates.onPause();activity.updates.onResume();});
        device.waitForIdle();assertEquals(1,calls.get());assertFalse(device.hasObject(By.text("下载更新")));
        CountDownLatch fetched=new CountDownLatch(1);install(()->{fetched.countDown();return release();},true);
        assertTrue(fetched.await(5,TimeUnit.SECONDS));device.waitForIdle();assertFalse(device.hasObject(By.text("下载更新")));
    }
    @Test public void dialogFollowsSystemAndDownloadPreservesDraft() throws Exception {
        js("(()=>{const e=document.querySelector('.unified-idea textarea');Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(e,'厦门三天草稿');e.dispatchEvent(new Event('input',{bubbles:true}))})()");
        install(()->release(),true);prompt();device.waitForIdle();
        device.takeScreenshot(new File(activity.getExternalFilesDir(null),"android-update-light.png"));
        device.executeShellCommand("cmd uimode night yes");
        long until=SystemClock.elapsedRealtime()+5000;
        while(!"\"dark\"".equals(js("document.documentElement.dataset.androidAppearance")) && SystemClock.elapsedRealtime()<until)SystemClock.sleep(100);
        assertEquals("\"dark\"",js("document.documentElement.dataset.androidAppearance"));
        prompt();device.waitForIdle();device.takeScreenshot(new File(activity.getExternalFilesDir(null),"android-update-dark.png"));
        device.findObject(By.text("下载更新")).click();
        assertTrue(device.wait(Until.gone(By.text("发现新版本 0.7.0")),2000));
        assertEquals(release().url,downloaded.get());
        assertEquals("\"厦门三天草稿\"",js("document.querySelector('.unified-idea textarea').value"));
    }
    @Test public void failureIsSilentAndDoesNotBlockHome() throws Exception {
        CountDownLatch fetched=new CountDownLatch(1);install(()->{fetched.countDown();throw new IOException("offline");},true);
        assertTrue(fetched.await(5,TimeUnit.SECONDS));device.waitForIdle();assertFalse(device.hasObject(By.text("下载更新")));
        assertEquals("true",js("Boolean(document.querySelector('.unified-idea textarea'))"));
        js("document.querySelector('.unified-idea textarea').value='保留草稿'");
        assertEquals("\"保留草稿\"",js("document.querySelector('.unified-idea textarea').value"));
    }
    @Test public void signInAlsoFollowsSystemAppearanceWithoutLosingInput() throws Exception {
        ui(()->activity.web.loadUrl(UrlPolicy.HOME+"__android_test__?startup=guest"));
        long until=SystemClock.elapsedRealtime()+10000;
        while(!"true".equals(js("Boolean(document.querySelector('.auth-field input'))")) && SystemClock.elapsedRealtime()<until)SystemClock.sleep(100);
        assertEquals("true",js("Boolean(document.querySelector('.auth-field input'))"));
        js("document.querySelector('.auth-field input').value='旅行朋友'");
        device.executeShellCommand("cmd uimode night yes");
        until=SystemClock.elapsedRealtime()+5000;
        while(!"\"dark\"".equals(js("document.documentElement.dataset.androidAppearance")) && SystemClock.elapsedRealtime()<until)SystemClock.sleep(100);
        assertEquals("\"rgb(240, 242, 247)\"",js("getComputedStyle(document.querySelector('.auth-field input')).color"));
        assertEquals("\"rgb(240, 242, 247)\"",js("getComputedStyle(document.querySelector('.auth-screen .brand-cn')).color"));
        assertEquals("\"rgb(160, 169, 186)\"",js("getComputedStyle(document.querySelector('.auth-tagline')).color"));
        device.waitForIdle();device.takeScreenshot(new File(activity.getExternalFilesDir(null),"android-auth-dark.png"));
        device.executeShellCommand("cmd uimode night no");
        until=SystemClock.elapsedRealtime()+5000;
        while(!"\"light\"".equals(js("document.documentElement.dataset.androidAppearance")) && SystemClock.elapsedRealtime()<until)SystemClock.sleep(100);
        assertNotEquals("\"rgb(240, 242, 247)\"",js("getComputedStyle(document.querySelector('.auth-field input')).color"));
        assertEquals("\"旅行朋友\"",js("document.querySelector('.auth-field input').value"));
    }
    @Test public void pendingResultWaitsForForegroundAndCloseCancelsUi() throws Exception {
        CountDownLatch fetchStarted=new CountDownLatch(1),allowResult=new CountDownLatch(1);
        install(()->{fetchStarted.countDown();allowResult.await(5,TimeUnit.SECONDS);return release();},true);
        assertTrue(fetchStarted.await(5,TimeUnit.SECONDS));ui(()->activity.updates.onPause());allowResult.countDown();
        SystemClock.sleep(200);device.waitForIdle();assertFalse(device.hasObject(By.text("下载更新")));
        ui(()->activity.updates.onResume());prompt();
        ui(()->activity.updates.close());assertTrue(device.wait(Until.gone(By.text("下载更新")),2000));
        ui(()->activity.updates.onResume());assertFalse(device.hasObject(By.text("下载更新")));
    }
}
