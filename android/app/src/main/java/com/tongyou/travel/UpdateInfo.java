package com.tongyou.travel;

/** Validated public release metadata. Never accepts executable URLs from arbitrary hosts. */
final class UpdateInfo {
    static final String MANIFEST_URL = "https://17tongyou.com/downloads/android/latest.json";
    final int code, minSdk;
    final String version, url, notes, sha256;
    final long bytes;

    UpdateInfo(int code, String version, String url, String notes, long bytes, String sha256, int minSdk) {
        if (code < 1 || version == null || !version.matches("[0-9]{1,4}\\.[0-9]{1,4}\\.[0-9]{1,4}")
                || bytes < 1 || bytes > 200L * 1024 * 1024 || sha256 == null || !sha256.matches("[a-f0-9]{64}")
                || minSdk < 26 || minSdk > 100 || notes == null || notes.length() > 2000)
            throw new IllegalArgumentException("Invalid release metadata");
        String expected = "https://17tongyou.com/downloads/android/" + version + "-" + code
                + "/17tongyou-android-" + version + "-" + code + ".apk";
        if (!expected.equals(url)) throw new IllegalArgumentException("Invalid release URL");
        this.code=code; this.version=version; this.url=url; this.notes=notes;
        this.bytes=bytes; this.sha256=sha256; this.minSdk=minSdk;
    }
    boolean shouldOffer(int installedCode, int sdk, int deferredCode, long deferredUntil, long now) {
        return code > installedCode && sdk >= minSdk && !(deferredCode == code && now < deferredUntil);
    }
}
