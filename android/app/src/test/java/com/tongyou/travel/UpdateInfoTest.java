package com.tongyou.travel;

import org.junit.Test;
import static org.junit.Assert.*;

public class UpdateInfoTest {
    private UpdateInfo release(int code,int sdk) {
        return new UpdateInfo(code,"0.6.0","https://17tongyou.com/downloads/android/0.6.0-"+code+"/17tongyou-android-0.6.0-"+code+".apk","改进体验",3000000,"a".repeat(64),sdk);
    }
    @Test public void offerOnlyNewCompatibleVersion() {
        assertTrue(release(10,26).shouldOffer(9,35,0,0,100));
        assertFalse(release(9,26).shouldOffer(9,35,0,0,100));
        assertFalse(release(8,26).shouldOffer(9,35,0,0,100));
        assertFalse(release(10,36).shouldOffer(9,35,0,0,100));
    }
    @Test public void snoozeOnlySameReleaseUntilExpiry() {
        assertFalse(release(10,26).shouldOffer(9,35,10,200,100));
        assertTrue(release(10,26).shouldOffer(9,35,10,200,201));
        assertTrue(release(11,26).shouldOffer(9,35,10,200,100));
    }
    @Test public void rejectUntrustedOrMismatchedUrls() {
        for(String url:new String[]{"http://17tongyou.com/a.apk","https://evil.test/a.apk","https://17tongyou.com.evil.test/a.apk",
                "https://17tongyou.com/downloads/android/0.6.0-10/17tongyou-android-0.6.0-10.apk?next=evil",
                "https://17tongyou.com/downloads/android/0.5.0-8/17tongyou-android-0.5.0-8.apk"})
            assertThrows(IllegalArgumentException.class,()->new UpdateInfo(10,"0.6.0",url,"",1,"a".repeat(64),26));
    }
    @Test public void rejectInvalidVersionSizeAndDigest() {
        assertThrows(IllegalArgumentException.class,()->release(0,26));
        assertThrows(IllegalArgumentException.class,()->release(10,0));
        String url="https://17tongyou.com/downloads/android/0.6.0-10/17tongyou-android-0.6.0-10.apk";
        assertThrows(IllegalArgumentException.class,()->new UpdateInfo(10,"0.6.0",url,"",0,"a".repeat(64),26));
        assertThrows(IllegalArgumentException.class,()->new UpdateInfo(10,"0.6.0",url,"",1,"wrong",26));
        assertThrows(IllegalArgumentException.class,()->new UpdateInfo(10,"0.6.0",url,"x".repeat(2001),1,"a".repeat(64),26));
    }
}
