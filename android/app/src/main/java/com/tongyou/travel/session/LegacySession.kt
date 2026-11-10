package com.tongyou.travel.session

import android.annotation.SuppressLint
import android.content.Context
import android.webkit.WebView
import android.webkit.WebViewClient
import com.tongyou.travel.UrlPolicy
import com.tongyou.travel.data.bool
import com.tongyou.travel.data.obj
import com.tongyou.travel.data.string
import com.tongyou.travel.data.wireJson
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import kotlin.coroutines.resume

/** What the old WebView profile said. `Failed` is NOT "signed out": the caller must not commit a migration on it. */
sealed interface LegacyRead {
    data class Found(val token: String) : LegacyRead
    data object Empty : LegacyRead
    data object Failed : LegacyRead
}

/** The plaintext session left behind by the WebView-only releases. */
interface LegacyStore {
    suspend fun read(): LegacyRead
    /** Returns false when the old storage could not be reached; the fallback clears it at document start anyway. */
    suspend fun clear(): Boolean
}

/** An offline page at the EXACT old origin. Reads the existing WebView profile without navigation. */
object LegacySession {
    fun store(context: Context): LegacyStore = object : LegacyStore {
        override suspend fun read() = parse(run(context, READ))
        override suspend fun clear() = parse(run(context, script(null))) != LegacyRead.Failed
    }

    /** Kept for tests and tools: read (default) or overwrite the legacy token. Null also means "could not read". */
    suspend fun exchange(context: Context, token: String? = null, write: Boolean = false): String? =
        (parse(run(context, if (write) script(token) else READ)) as? LegacyRead.Found)?.token?.takeIf { !write }

    // A thrown SecurityError and a missing key both used to come back as `null`; the wrapper makes
    // "the script ran and storage answered" explicit, so a failure can never look like "signed out".
    private const val READ = "(function(){try{return JSON.stringify({ok:true,token:localStorage.getItem('travel_token')})}catch(e){return JSON.stringify({ok:false})}})()"
    private fun script(token: String?) = "(function(){try{" +
        (if (token == null) "localStorage.removeItem('travel_token')" else "localStorage.setItem('travel_token',${org.json.JSONObject.quote(token)})") +
        ";return JSON.stringify({ok:true,token:localStorage.getItem('travel_token')})}catch(e){return JSON.stringify({ok:false})}})()"

    /** `raw` is evaluateJavascript's JSON-encoded result (a JSON string holding our JSON), or null on timeout. */
    fun parse(raw: String?): LegacyRead {
        val reply = runCatching { wireJson.parseToJsonElement(wireJson.parseToJsonElement(raw!!).string()).obj() }.getOrNull()
        if (reply == null || !reply["ok"].bool()) return LegacyRead.Failed
        return reply["token"].string().takeIf { it.isNotEmpty() }?.let(LegacyRead::Found) ?: LegacyRead.Empty
    }

    @SuppressLint("SetJavaScriptEnabled")
    private suspend fun run(context: Context, script: String): String? = withContext(Dispatchers.Main) {
        var web: WebView? = null
        try {
            // withTimeoutOrNull, not withTimeout: a timeout is an ordinary failed read. Thrown as a
            // CancellationException it silently ended the restore coroutine and left the spinner forever.
            withTimeoutOrNull(8000) {
                suspendCancellableCoroutine { continuation ->
                    web = WebView(context).apply {
                        settings.javaScriptEnabled = true
                        settings.domStorageEnabled = true
                        settings.allowFileAccess = false
                        settings.allowContentAccess = false
                        settings.blockNetworkLoads = true
                        webViewClient = object : WebViewClient() {
                            override fun onPageFinished(view: WebView, url: String) {
                                view.evaluateJavascript(script) { raw -> if (continuation.isActive) continuation.resume(raw) }
                            }
                        }
                        loadDataWithBaseURL(UrlPolicy.HOME, "<!doctype html><title>Session migration</title>", "text/html", "UTF-8", null)
                    }
                }
            }
        } finally { web?.stopLoading(); web?.destroy() }
    }
}
