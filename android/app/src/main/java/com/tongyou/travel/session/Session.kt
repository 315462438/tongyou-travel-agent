package com.tongyou.travel.session

import android.content.Context
import com.tongyou.travel.data.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.serialization.json.JsonObject

data class SessionState(val checking: Boolean = true, val token: String? = null, val account: JsonObject? = null, val error: String? = null)

/** Where the encrypted token lives. An interface so restore/migration rules are testable off-device. */
interface SessionVault {
    fun read(): String?
    fun save(token: String?)
    fun migrated(): Boolean
}

class Session(private val vault: SessionVault, private val legacy: LegacyStore) {
    constructor(context: Context, vault: TokenVault) : this(vault, LegacySession.store(context.applicationContext))
    private val mutable = MutableStateFlow(SessionState())
    val state = mutable.asStateFlow()
    @Volatile private var current: String? = null
    fun token(): String? = current

    suspend fun restore(api: TravelService) {
        try {
            mutable.value = mutable.value.copy(checking = true, error = null)
            val saved = withContext(Dispatchers.IO) { vault.read() }
            val needsMigration = !vault.migrated()
            var token = saved
            if (saved == null && needsMigration) {
                // Only the one-time migration initializes WebView. Later native cold starts
                // do not pay the browser startup cost or depend on its engine version.
                when (val old = legacy.read()) {
                    is LegacyRead.Found -> token = old.token
                    LegacyRead.Empty -> Unit
                    // Could not read the old profile (WebView busy, timeout, storage error). This is not
                    // "signed out": committing here would mark the migration done and then erase the only
                    // copy of the user's session. Leave everything untouched and let them retry.
                    LegacyRead.Failed -> { mutable.value = SessionState(false, error = "登录信息暂时无法读取，请重试"); return }
                }
            }
            if (needsMigration) {
                withContext(Dispatchers.IO) { vault.save(token) }
                legacy.clear()   // best effort: the fallback also rewrites its storage from the vault at document start
            }
            synchronized(this) { current = token; mutable.value = SessionState(false, token) }
            if (token != null) refresh(api)
        } catch (e: CancellationException) { throw e }
        catch (e: Exception) { mutable.value = mutable.value.copy(checking = false, error = "登录信息暂时无法读取，请重试") }
    }

    /**
     * The way out of a session that cannot be read (lost Keystore key, broken WebView): forget it and
     * show the login screen. Without this a failing restore offered only "重试", which fails the same way.
     */
    suspend fun resetToLogin() {
        try { withContext(Dispatchers.IO) { vault.save(null) } }
        catch (e: CancellationException) { throw e } catch (_: Exception) { }
        synchronized(this) { current = null; mutable.value = SessionState(false, null) }
    }

    suspend fun refresh(api: TravelService) {
        val expected = current ?: return
        try {
            val account = withContext(Dispatchers.IO) { api.request("GET", "auth/me").obj() }
            synchronized(this) { if (current == expected) mutable.value = SessionState(false, expected, account) }
        } catch (e: CancellationException) { throw e }
        catch (e: Exception) { /* Offline keeps the encrypted session; 401 uses invalidate. */ }
    }

    suspend fun authenticate(api: TravelService, name: String, password: String, invite: String?) {
        val reply = withContext(Dispatchers.IO) {
            api.request("POST", if (invite == null) "auth/login" else "auth/register",
                jsonBody("username" to name.trim(), "password" to password, "invite_code" to invite.orEmpty()), authenticated = false).obj()
        }
        val token = reply["token"].string().ifBlank { error("登录未返回凭证，请重试") }
        withContext(Dispatchers.IO) { replace(token, reply) }
    }

    @Synchronized private fun replace(token: String?, account: JsonObject? = null) {
        vault.save(token)
        current = token
        mutable.value = SessionState(false, token, account)
    }
    fun invalidate(expected: String) {
        synchronized(this) { if (current != expected) return; replace(null) }
        // The committed migration marker prevents the old WebView plaintext from ever being imported again.
    }
    suspend fun logout(api: TravelService) {
        val expected = current ?: return
        // Call server while the old token is still available, then erase locally even offline.
        try { withContext(Dispatchers.IO) { api.request("POST", "auth/logout") } }
        catch (e: CancellationException) { throw e } catch (_: Exception) { }
        invalidate(expected)
    }

    /** Swaps in a token the server just issued (password change). A stale caller cannot replace a newer login. */
    @Synchronized fun replaceToken(expected: String?, token: String?) {
        if (current != expected) return
        replace(token?.takeIf { it.isNotEmpty() }, mutable.value.account.takeIf { token != null })
    }
}
