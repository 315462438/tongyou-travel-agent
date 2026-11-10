package com.tongyou.travel

import com.tongyou.travel.data.TravelService
import com.tongyou.travel.session.*
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

/** Upgrade from the WebView-only releases: a failed read must never be treated as "signed out". */
class SessionMigrationTest {
    private class Vault(var token: String? = null, var done: Boolean = false, var broken: Boolean = false) : SessionVault {
        var saves = 0
        override fun read(): String? { if (broken) throw java.security.ProviderException("keystore busy"); return token }
        override fun save(token: String?) { saves++; this.token = token; done = true }
        override fun migrated() = done
    }
    private class Legacy(var answer: LegacyRead) : LegacyStore {
        var reads = 0; var clears = 0
        override suspend fun read(): LegacyRead { reads++; return answer }
        override suspend fun clear(): Boolean { clears++; answer = LegacyRead.Empty; return true }
    }
    private val api = object : TravelService {
        override suspend fun request(method: String, path: String, body: JsonObject?, query: List<Pair<String, String>>, authenticated: Boolean): JsonElement =
            buildJsonObject { put("username", "fixture") }
        override suspend fun upload(bytes: ByteArray, mime: String) = "x"
    }

    @Test fun legacyTokenIsMovedIntoTheVaultAndPlaintextCleared() = runBlocking {
        val vault = Vault(); val legacy = Legacy(LegacyRead.Found("old-token"))
        val session = Session(vault, legacy); session.restore(api)
        assertEquals("old-token", session.token()); assertEquals("old-token", vault.token)
        assertTrue(vault.done); assertEquals(1, legacy.clears)
        assertFalse(session.state.value.checking); assertNull(session.state.value.error)
    }

    @Test fun failedLegacyReadDoesNotCommitMigrationOrEraseTheOldSession() = runBlocking {
        val vault = Vault(); val legacy = Legacy(LegacyRead.Failed)
        val session = Session(vault, legacy); session.restore(api)
        assertFalse("a failed read must not mark the migration done", vault.done)
        assertEquals(0, vault.saves); assertEquals("plaintext must survive for the retry", 0, legacy.clears)
        assertNull(session.token()); assertFalse(session.state.value.checking); assertNotNull(session.state.value.error)
        // The retry succeeds once the WebView answers: the user is still signed in.
        legacy.answer = LegacyRead.Found("old-token"); session.restore(api)
        assertEquals("old-token", session.token()); assertNull(session.state.value.error)
    }

    @Test fun genuinelySignedOutUserMigratesOnceAndNeverTouchesWebViewAgain() = runBlocking {
        val vault = Vault(); val legacy = Legacy(LegacyRead.Empty)
        Session(vault, legacy).restore(api)
        assertTrue(vault.done); assertNull(vault.token)
        Session(vault, legacy).restore(api)
        assertEquals(1, legacy.reads)
    }

    @Test fun afterMigrationAStalePlaintextTokenIsNeverImported() = runBlocking {
        val vault = Vault(done = true); val legacy = Legacy(LegacyRead.Found("stale"))
        val session = Session(vault, legacy); session.restore(api)
        assertNull(session.token()); assertEquals(0, legacy.reads)
    }

    @Test fun unreadableVaultShowsAnErrorAndCanAlwaysFallBackToLogin() = runBlocking {
        val vault = Vault(token = "t", done = true, broken = true)
        val session = Session(vault, Legacy(LegacyRead.Empty)); session.restore(api)
        assertFalse(session.state.value.checking); assertNotNull(session.state.value.error)
        session.restore(api)                                   // retry fails the same way…
        assertNotNull(session.state.value.error)
        session.resetToLogin()                                 // …so there must be a way out
        val state = session.state.value
        assertFalse(state.checking); assertNull(state.error); assertNull(state.token); assertNull(vault.token)
    }

    @Test fun legacyReplyDistinguishesMissingTokenFromFailure() {
        fun js(inner: String) = JsonPrimitive(inner).toString()     // evaluateJavascript JSON-encodes the returned string
        assertEquals(LegacyRead.Found("abc"), LegacySession.parse(js("""{"ok":true,"token":"abc"}""")))
        assertEquals(LegacyRead.Empty, LegacySession.parse(js("""{"ok":true,"token":null}""")))
        assertEquals(LegacyRead.Empty, LegacySession.parse(js("""{"ok":true,"token":""}""")))
        assertEquals(LegacyRead.Failed, LegacySession.parse(js("""{"ok":false}""")))    // storage threw
        assertEquals(LegacyRead.Failed, LegacySession.parse("null"))                    // script itself threw
        assertEquals(LegacyRead.Failed, LegacySession.parse(null))                      // timed out
        assertEquals(LegacyRead.Failed, LegacySession.parse("\"not json\""))
    }
}
