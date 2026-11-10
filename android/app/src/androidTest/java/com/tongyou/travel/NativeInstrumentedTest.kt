package com.tongyou.travel

import android.content.Intent
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.UiDevice
import com.tongyou.travel.data.*
import com.tongyou.travel.session.*
import kotlinx.coroutines.*
import kotlinx.serialization.json.*
import org.junit.*
import org.junit.Assert.*
import java.io.File

class NativeInstrumentedTest {
    @get:Rule val compose = createEmptyComposeRule()
    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()
    private val app get() = instrumentation.targetContext.applicationContext as TongyouApplication
    private lateinit var fake: NativeFixture
    private var scenario: ActivityScenario<MainActivity>? = null
    private val device get() = UiDevice.getInstance(instrumentation)

    @Before fun setup() {
        fake = NativeFixture(); app.service = fake
        TokenVault(app).save("native-fixture")
        runBlocking { app.session.restore(fake) }
    }
    @After fun after() {
        scenario?.close()
        device.executeShellCommand("cmd uimode night no")
        device.executeShellCommand("settings put system font_scale 1.0")
        device.executeShellCommand("settings put global animator_duration_scale 1")
    }
    private fun launch() { scenario = ActivityScenario.launch(MainActivity::class.java); compose.waitUntil(15000) { compose.onAllNodesWithText("把期待，\n变成一段旅行。").fetchSemanticsNodes().isNotEmpty() } }
    private fun screenshot(name: String) { compose.waitForIdle(); device.takeScreenshot(File(app.getExternalFilesDir(null), "native-$name.png")) }

    @Test fun nativeHomeChatSuggestionsAndBack() {
        launch(); compose.onNodeWithText("杭州三日 · 山水慢游").assertExists(); screenshot("home")
        compose.onNodeWithTag("open-ai").performClick()
        compose.onNode(hasSetTextAction()).performTextInput("杭州怎么玩")
        compose.onNodeWithContentDescription("发送").performClick()
        compose.waitUntil(10000) { fake.sends == 1 && compose.onAllNodesWithText("西湖", substring = true).fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("吃什么").performScrollTo().performClick()
        compose.waitUntil(5000) { fake.sends == 2 }
        screenshot("chat")
        compose.onNodeWithContentDescription("返回旅行").performClick()
        compose.onNodeWithText("我的旅行").assertExists()
    }
    @Test fun offlineSendRetainsDraftAndCanRetry() {
        launch(); compose.onNodeWithTag("open-ai").performClick()
        fake.failSend = true
        compose.onNode(hasSetTextAction()).performTextInput("保留我的草稿")
        compose.onNodeWithContentDescription("发送").performClick()
        compose.waitUntil(5000) { compose.onAllNodesWithText("模拟断网").fetchSemanticsNodes().isNotEmpty() }
        compose.onNode(hasSetTextAction()).assertTextContains("保留我的草稿")
        fake.failSend = false; compose.onNodeWithContentDescription("发送").performClick()
        compose.waitUntil(5000) { fake.sends == 2 }
        compose.onNode(hasSetTextAction()).assertTextEquals("")
    }
    @Test fun deepAndSearchFieldsAndStopReachApi() {
        launch(); compose.onNodeWithTag("open-ai").performClick()
        compose.onNodeWithText("深度推理").performClick(); compose.onNodeWithText("联网搜索").performClick()
        fake.running = true
        compose.onNode(hasSetTextAction()).performTextInput("对比两个目的地")
        compose.onNodeWithContentDescription("发送").performClick()
        compose.waitUntil(5000) { compose.onAllNodesWithContentDescription("停止生成").fetchSemanticsNodes().isNotEmpty() }
        assertTrue(fake.sentBody!!["deep_reasoning"].bool()); assertTrue(fake.sentBody!!["web_search"].bool())
        compose.onNodeWithContentDescription("停止生成").performClick()
        compose.waitUntil(5000) { fake.stops == 1 }
        compose.waitUntil(5000) { compose.onAllNodesWithContentDescription("发送").fetchSemanticsNodes().isNotEmpty() }
    }
    @Test fun darkLargeFontReducedMotionPreserveDraft() {
        launch(); compose.onNodeWithTag("open-ai").performClick()
        compose.onNode(hasSetTextAction()).performTextInput("保留外观切换草稿")
        device.executeShellCommand("cmd uimode night yes")
        device.executeShellCommand("settings put system font_scale 1.3")
        device.executeShellCommand("settings put global animator_duration_scale 0")
        compose.waitForIdle(); compose.onNode(hasSetTextAction()).assertTextContains("保留外观切换草稿")
        compose.onNodeWithContentDescription("发送").assertIsDisplayed(); screenshot("dark-large-font")
    }
    @Test fun nativeLoginAndInviteRegistrationAreUsable() {
        runBlocking { app.session.logout(fake) }
        scenario = ActivityScenario.launch(MainActivity::class.java)
        compose.waitUntil(10000) { compose.onAllNodesWithText("登录 17同游").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("邀请码注册").performClick()
        compose.onNodeWithText("用户名").performTextInput("测试朋友")
        compose.onNodeWithText("密码").performTextInput("fixture-password")
        compose.onNodeWithText("邀请码", substring = false).performTextInput("invite-fixture")
        screenshot("login")
        compose.onNodeWithText("注册并登录").performScrollTo().performClick()
        compose.waitUntil(10000) { compose.onAllNodesWithText("我的旅行").fetchSemanticsNodes().isNotEmpty() }
        assertEquals("invite-fixture", fake.registerBody!!["invite_code"].string())
        assertEquals("native-fixture", TokenVault(app).read())
    }
    @Test fun legacyMigrationEncryptsAndNeverResurrectsSignedOutToken() = runBlocking {
        app.getSharedPreferences("native_session", 0).edit().clear().commit()
        LegacySession.exchange(app, "legacy-fixture", write = true)
        val session = Session(app, TokenVault(app)); session.restore(fake)
        assertEquals("legacy-fixture", session.token()); assertEquals("legacy-fixture", TokenVault(app).read())
        val coldFallback = Session(app, TokenVault(app))
        assertTrue(coldFallback.restoreForFallback()); assertEquals("legacy-fixture", coldFallback.token())
        assertNull(LegacySession.exchange(app))
        val persisted = app.getSharedPreferences("native_session", 0).getString("ciphertext", "")!!
        assertFalse(persisted.contains("legacy-fixture"))
        session.invalidate("stale-token"); assertEquals("legacy-fixture", session.token())
        session.invalidate("legacy-fixture"); assertNull(session.token())
        LegacySession.exchange(app, "stale-web-token", write = true)
        val restarted = Session(app, TokenVault(app)); restarted.restore(fake)
        assertNull(restarted.token()); assertTrue(TokenVault(app).migrated())
    }
    @Test fun failedOrCorruptStorageNeverLooksLikeAValidSession() = runBlocking {
        // Real WebView: an ordinary read answers explicitly, with or without a token.
        LegacySession.exchange(app, "legacy-fixture", write = true)
        assertEquals(LegacyRead.Found("legacy-fixture"), LegacySession.store(app).read())
        assertTrue(LegacySession.store(app).clear())
        assertEquals(LegacyRead.Empty, LegacySession.store(app).read())
        // Real Keystore: ciphertext that is not ours is dropped, so the user reaches the login screen.
        app.getSharedPreferences("native_session", android.content.Context.MODE_PRIVATE).edit()
            .putString("ciphertext", "AAAAAAAAAAAAAAAA:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA").putBoolean("migrated", true).commit()
        assertNull(TokenVault(app).read())
        assertNull(app.getSharedPreferences("native_session", android.content.Context.MODE_PRIVATE).getString("ciphertext", null))
        val session = Session(app, TokenVault(app)); session.restore(fake)
        assertNull(session.token()); assertNull(session.state.value.error); assertFalse(session.state.value.checking)
    }
    @Test fun webSignOutAndStaleWebViewCannotOverwriteNewSession() {
        app.session.fromWeb("other-token", "bad-token"); assertEquals("native-fixture", app.session.token())
        app.session.fromWeb("native-fixture", null); assertNull(app.session.token()); assertNull(TokenVault(app).read())
        app.session.fromWeb("native-fixture", "resurrected"); assertNull(app.session.token())
    }
    @Test fun navigationRejectsSpoofedLinksAndPreservesInvitationAcrossLogin() {
        assertNull(MainActivity.incoming(Intent(Intent.ACTION_VIEW, android.net.Uri.parse("https://17tongyou.com.evil/travel/?ledger_join=x"))))
        assertNull(MainActivity.incoming(Intent(Intent.ACTION_VIEW, android.net.Uri.parse("https://17tongyou.com@evil/travel/"))))
        val link = "https://17tongyou.com/travel/?ledger_join=fixture"
        assertEquals(link, MainActivity.incoming(Intent(Intent.ACTION_SEND).putExtra(Intent.EXTRA_TEXT, "邀请：$link")))
        scenario = ActivityScenario.launch(Intent(app, MainActivity::class.java).setData(android.net.Uri.parse(link)))
        compose.waitUntil(10000) { compose.onAllNodesWithText("打开收到的同游链接？").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("取消").performClick()
        compose.onNodeWithText("我的旅行").assertExists()
    }
}

private class NativeFixture : TravelService {
    @Volatile var sends = 0; @Volatile var stops = 0; @Volatile var failSend = false; @Volatile var running = false
    @Volatile var sentBody: JsonObject? = null; @Volatile var registerBody: JsonObject? = null
    override suspend fun upload(bytes: ByteArray, mime: String) = "fixture-image"
    override suspend fun request(method: String, path: String, body: JsonObject?, query: List<Pair<String, String>>, authenticated: Boolean): JsonElement {
        return when {
            path == "auth/me" -> jsonBody("username" to "native_test", "display_name" to "测试朋友", "is_admin" to false)
            path == "auth/register" || path == "auth/login" -> { registerBody = body; jsonBody("token" to "native-fixture", "username" to "native_test", "display_name" to "测试朋友") }
            path == "trips" -> wireJson.parseToJsonElement("""[{"id":"fixture-trip","title":"杭州三日 · 山水慢游","destination":"杭州","days":3,"role":"owner"}]""")
            path == "trips/today" -> jsonBody("trip" to JsonNull)
            path == "onboarding" -> jsonBody("trending" to JsonArray(listOf(JsonPrimitive("杭州"), JsonPrimitive("武汉"))))
            path == "onboarding/covers" -> jsonBody("covers" to jsonBody())
            path.contains("unread") -> jsonBody("unread" to 0)
            path == "chat/conversations" && method == "POST" -> jsonBody("conversation_id" to "fixture-chat")
            path == "chat/conversations" -> JsonArray(listOf(jsonBody("id" to "fixture-chat", "title" to "杭州慢游")))
            path.endsWith("/stop") -> { stops++; running = false; jsonBody() }
            path.endsWith("/messages") && method == "POST" -> { sends++; sentBody = body; if (failSend) throw ApiFailure(0, "模拟断网"); jsonBody() }
            path.endsWith("/messages") -> jsonBody("running" to running, "messages" to JsonArray(listOf(
                jsonBody("id" to "u", "role" to "user", "content" to (sentBody?.get("content").string())),
                jsonBody("id" to "a", "role" to "assistant", "content" to "## 杭州慢游\n\n从**西湖**开始，沿湖走走。\n\n| 地点 | 时间 |\n| --- | --- |\n| 西湖 | 09:00 |\n\n> 带好雨伞。",
                    "meta" to jsonBody("streaming" to running, "suggestions" to JsonArray(listOf(JsonPrimitive("吃什么"))),
                        "sources" to JsonArray(listOf(jsonBody("title" to "地点参考", "url" to "https://example.com")))))
            )))
            else -> jsonBody()
        }
    }
}
