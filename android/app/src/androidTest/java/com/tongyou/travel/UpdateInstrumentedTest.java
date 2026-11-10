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
    private UpdateInfo release() { return new UpdateInfo(BuildConfig.VERSION_CODE+1,"0.9.0","https://17tongyou.com/downloads/android/0.9.0-"+(BuildConfig.VERSION_CODE+1)+"/17tongyou-android-0.9.0-"+(BuildConfig.VERSION_CODE+1)+".apk","更新测试：跟随系统外观",3000000,"a".repeat(64),26); }
    private void install(AppUpdates.Source source,boolean foreground) {
        ui(()-> {
            activity.getUpdates().close();
            activity.setUpdates(new AppUpdates(activity,source,downloaded::set,prefs));
            activity.getUpdates().onReady();
            if(foreground)activity.getUpdates().onResume();
        });
    }
    private void prompt() { assertTrue(device.wait(Until.hasObject(By.text("发现新版本 0.9.0")),5000)); }
    @Before public void before() throws Exception {
        device=UiDevice.getInstance(InstrumentationRegistry.getInstrumentation());
        device.executeShellCommand("cmd uimode night no");
        activity=rule.launchActivity(new Intent(Intent.ACTION_MAIN).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_ACTIVITY_CLEAR_TASK));
        device.waitForIdle();
        prefs=activity.getSharedPreferences("update_test",0);prefs.edit().clear().commit();
    }
    @After public void after() throws Exception {
        ui(()->{if(activity!=null&&!activity.isDestroyed())activity.finish();});
        device.executeShellCommand("cmd uimode night no");
    }
    @Test public void parseRejectsUnsafeBrokenAndOversizedMetadata() throws Exception {
        JSONObject m=new JSONObject().put("schema_version",1).put("enabled",true).put("platform","Android")
                .put("application_id","com.tongyou.travel").put("version_code",release().code).put("version","0.9.0")
                .put("url",release().url).put("bytes",3000000).put("sha256","a".repeat(64)).put("notes","改进体验").put("min_sdk",26);
        assertEquals(release().code,AppUpdates.parse(m.toString()).code);
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
        assertTrue(device.wait(Until.gone(By.text("发现新版本 0.9.0")),2000));
        assertEquals(release().code,prefs.getInt("deferred_code",0));assertTrue(prefs.getLong("deferred_until",0)>System.currentTimeMillis());
        ui(()->{activity.getUpdates().onPause();activity.getUpdates().onResume();});
        device.waitForIdle();assertEquals(1,calls.get());assertFalse(device.hasObject(By.text("下载更新")));
        CountDownLatch fetched=new CountDownLatch(1);install(()->{fetched.countDown();return release();},true);
        assertTrue(fetched.await(5,TimeUnit.SECONDS));device.waitForIdle();assertFalse(device.hasObject(By.text("下载更新")));
    }
    @Test public void dialogFollowsSystemAppearanceAndDownloads() throws Exception {
        install(()->release(),true);prompt();device.waitForIdle();
        device.takeScreenshot(new File(activity.getExternalFilesDir(null),"android-update-light.png"));
        device.executeShellCommand("cmd uimode night yes");
        SystemClock.sleep(800);
        prompt();device.waitForIdle();device.takeScreenshot(new File(activity.getExternalFilesDir(null),"android-update-dark.png"));
        device.findObject(By.text("下载更新")).click();
        assertTrue(device.wait(Until.gone(By.text("发现新版本 0.9.0")),2000));
        assertEquals(release().url,downloaded.get());
    }
    @Test public void failureIsSilent() throws Exception {
        CountDownLatch fetched=new CountDownLatch(1);install(()->{fetched.countDown();throw new IOException("offline");},true);
        assertTrue(fetched.await(5,TimeUnit.SECONDS));device.waitForIdle();assertFalse(device.hasObject(By.text("下载更新")));
        assertFalse(activity.isFinishing());
    }
    @Test public void pendingResultWaitsForForegroundAndCloseCancelsUi() throws Exception {
        CountDownLatch fetchStarted=new CountDownLatch(1),allowResult=new CountDownLatch(1);
        install(()->{fetchStarted.countDown();allowResult.await(5,TimeUnit.SECONDS);return release();},true);
        assertTrue(fetchStarted.await(5,TimeUnit.SECONDS));ui(()->activity.getUpdates().onPause());allowResult.countDown();
        SystemClock.sleep(200);device.waitForIdle();assertFalse(device.hasObject(By.text("下载更新")));
        ui(()->activity.getUpdates().onResume());prompt();
        ui(()->activity.getUpdates().close());assertTrue(device.wait(Until.gone(By.text("下载更新")),2000));
        ui(()->activity.getUpdates().onResume());assertFalse(device.hasObject(By.text("下载更新")));
    }
}
