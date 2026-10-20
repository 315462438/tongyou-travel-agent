package com.tongyou.travel;
import org.junit.Test;
import static org.junit.Assert.*;

public class UrlPolicyTest {
    @Test public void trustedOriginIsExact() {
        assertTrue(UrlPolicy.trustedOrigin(UrlPolicy.HOME));
        assertTrue(UrlPolicy.trustedOrigin("https://17tongyou.com:443/travel/api"));
        for (String u : new String[]{"http://17tongyou.com/travel/", "https://17tongyou.com.evil.test/travel/", "https://17tongyou.com@evil.test", "https://evil@17tongyou.com", "https://17tongyou.com:8080", "file:///etc/passwd", "javascript:alert(1)", "https://17tongyou.com\\@evil.test"}) assertFalse(u, UrlPolicy.trustedOrigin(u));
    }
    @Test public void linksCannotOpenApisInsideApp() {
        assertTrue(UrlPolicy.appPage(UrlPolicy.HOME + "?ledger_join=abc"));
        assertTrue(UrlPolicy.appPage(UrlPolicy.HOME + "#trips/abc"));
        assertTrue(UrlPolicy.appPage("https://17tongyou.com/t/abcd1234"));
        assertFalse(UrlPolicy.appPage("https://17tongyou.com/t/../admin"));
        assertFalse(UrlPolicy.appPage(UrlPolicy.HOME + "api/auth/me"));
        assertFalse(UrlPolicy.appPage(UrlPolicy.HOME + "../admin"));
        assertFalse(UrlPolicy.appPage("https://17tongyou.com/"));
    }
    @Test public void externalLinksDoNotAllowArbitraryIntents() {
        assertTrue(UrlPolicy.external("https://example.com/guide"));
        assertFalse(UrlPolicy.external("intent://admin/#Intent;end"));
        assertFalse(UrlPolicy.external("content://private/file"));
    }
    @Test public void filenamesCannotEscapeExportDirectory() {
        assertEquals("_.._private.txt", UrlPolicy.safeName("../../private.txt"));
        assertEquals("17同游导出文件", UrlPolicy.safeName("..."));
        assertEquals("旅行.png", UrlPolicy.safeName("旅行.png"));
        assertTrue(UrlPolicy.safeName("x".repeat(200) + ".pdf").endsWith(".pdf"));
    }
}
