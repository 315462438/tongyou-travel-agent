package com.tongyou.travel;

import java.net.URI;

/** Shared by navigation, incoming links and bridge validation. Fail closed. */
public final class UrlPolicy {
    public static final String ORIGIN = "https://17tongyou.com";
    public static final String HOME = ORIGIN + "/travel/";
    public static final int MAX_EXPORT_BYTES = 20 * 1024 * 1024;
    public static boolean trustedOrigin(String url) {
        try {
            URI u = new URI(url);
            return "https".equalsIgnoreCase(u.getScheme()) && "17tongyou.com".equalsIgnoreCase(u.getHost())
                && u.getRawUserInfo() == null && (u.getPort() == -1 || u.getPort() == 443);
        } catch (Exception e) { return false; }
    }
    public static boolean appPage(String url) {
        if (!trustedOrigin(url)) return false;
        try {
            String p = new URI(url).getPath();
            return (p.equals("/travel") || p.equals("/travel/") || p.matches("/t/[A-Za-z0-9_-]{8}")) && !url.contains("\\");
        } catch (Exception e) { return false; }
    }
    public static boolean external(String url) {
        try {
            URI u = new URI(url);
            return ("https".equalsIgnoreCase(u.getScheme()) || "http".equalsIgnoreCase(u.getScheme()))
                && u.getHost() != null && u.getRawUserInfo() == null;
        } catch (Exception e) { return false; }
    }
    public static String safeName(String name) {
        String result = name == null ? "" : name.replaceAll("[\\\\/\\p{Cntrl}:*?\"<>|]", "_").replaceAll("^\\.+", "").trim();
        if (result.isEmpty()) result = "17同游导出文件";
        if (result.length() > 120) result = result.substring(result.length() - 120);
        return result;
    }
    private UrlPolicy() {}
}
