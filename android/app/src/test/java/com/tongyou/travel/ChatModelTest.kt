package com.tongyou.travel

import androidx.lifecycle.SavedStateHandle
import com.tongyou.travel.chat.*
import com.tongyou.travel.data.*
import kotlinx.coroutines.*
import kotlinx.coroutines.test.*
import kotlinx.serialization.json.*
import org.junit.*
import org.junit.Assert.*

@OptIn(ExperimentalCoroutinesApi::class)
class ChatModelTest {
    private val scheduler = TestCoroutineScheduler()
    private val dispatcher = StandardTestDispatcher(scheduler)
    private lateinit var service: FakeService
    private lateinit var model: ChatModel
    @Before fun before() { Dispatchers.setMain(dispatcher); service = FakeService(); model = ChatModel(service, SavedStateHandle(), dispatcher) }
    @After fun after() { model.deactivate(); Dispatchers.resetMain() }
    @Test fun duplicateTapsPostOnceAndClearOnlyAcceptedDraft() = runTest(dispatcher) {
        model.activate(); model.draft("杭州三天"); model.send(); model.send(); advanceUntilIdle()
        assertEquals(1, service.sends); assertEquals("", model.state.value.draft)
        assertEquals("a", model.state.value.id); assertFalse(model.state.value.running)
        assertEquals("杭州三天", service.sentBody!!["content"].string())
    }
    @Test fun failureKeepsDraftAndUploadedImages() = runTest(dispatcher) {
        model.upload { byteArrayOf(1) to "image/png" }; advanceUntilIdle()
        service.sendStatus = 500; model.draft("保留草稿"); model.send(); advanceUntilIdle()
        assertEquals("保留草稿", model.state.value.draft); assertEquals(listOf("photo"), model.state.value.images)
        assertFalse(model.state.value.sending); assertNotNull(model.state.value.error)
    }
    @Test fun conflictFollowsRunningTurnWithoutLosingUnsentDraft() = runTest(dispatcher) {
        service.sendStatus = 409; service.running = true
        model.activate(); model.draft("下一轮"); model.send(); runCurrent()
        assertEquals("下一轮", model.state.value.draft); assertTrue(model.state.value.running)
        assertEquals(1, service.sends); model.deactivate()
    }
    @Test fun pollingIs800msAndStopsWhenLeavingOrFinishing() = runTest(dispatcher) {
        service.running = true; model.open("a"); model.activate(); runCurrent(); assertEquals(1, service.reads)
        advanceTimeBy(799); runCurrent(); assertEquals(1, service.reads)
        advanceTimeBy(1); runCurrent(); assertEquals(2, service.reads)
        model.deactivate(); advanceTimeBy(5000); runCurrent(); assertEquals(2, service.reads)
        service.running = false; model.activate(); runCurrent(); assertEquals(3, service.reads)
        advanceTimeBy(5000); runCurrent(); assertEquals(3, service.reads)
    }
    @Test fun staleConversationResponseCannotOverwriteNewConversation() = runTest(dispatcher) {
        service.readDelay = 2000; model.open("old"); model.activate(); runCurrent()
        model.open("new"); runCurrent(); advanceTimeBy(2100); runCurrent()
        assertEquals("new", model.state.value.id); assertEquals("new", model.state.value.messages.first().content)
    }
    @Test fun stopFailureAllowsRetryAndDoesNotPretendToStopServer() = runTest(dispatcher) {
        service.running = true; model.open("a"); model.activate(); runCurrent()
        service.stopFails = true; model.stop(); runCurrent()
        assertTrue(model.state.value.running); assertFalse(model.state.value.stopping); assertNotNull(model.state.value.error)
        service.stopFails = false; model.stop(); runCurrent(); assertFalse(model.state.value.running)
        model.deactivate()
    }
    @Test fun sendLocationAndDeepPreferenceAreRequestFields() = runTest(dispatcher) {
        model.search(true); model.draft("附近吃什么"); model.send(location = "121,31", forceDeep = true); advanceUntilIdle()
        assertEquals("121,31", service.sentBody!!["location"].string()); assertTrue(service.sentBody!!["deep_reasoning"].bool()); assertTrue(service.sentBody!!["web_search"].bool())
        assertTrue(wantsNearby("周边去哪儿")); assertFalse(wantsNearby("上海三日游"))
    }
    @Test fun webSearchIsOnByDefaultAndOnlyAnExplicitChoiceIsRemembered() = runTest(dispatcher) {
        assertTrue(model.state.value.webSearch)                       // same default as web and iOS
        model.draft("合肥洗浴中心"); model.send(); advanceUntilIdle()
        assertTrue(service.sentBody!!["web_search"].bool())
        val prefs = MemoryChatPrefs()
        val first = ChatModel(service, SavedStateHandle(), dispatcher, prefs)
        first.search(false); first.open()                             // a new conversation keeps the choice
        assertFalse(first.state.value.webSearch)
        assertFalse(ChatModel(service, SavedStateHandle(), dispatcher, prefs).state.value.webSearch)   // and so does a restart
        assertFalse(first.state.value.deep)                           // deep reasoning is never sticky
    }
    @Test fun validationDoesNotSilentlyTruncateAndNewDraftDuringSendSurvives() = runTest(dispatcher) {
        model.draft("长".repeat(4001)); model.send(); advanceUntilIdle(); assertEquals(0, service.sends)
        model.draft("第一条"); model.send(); model.draft("第二条"); advanceUntilIdle(); assertEquals("第二条", model.state.value.draft)
    }
    @Test fun suggestionDoesNotEraseAnUnrelatedComposerDraft() = runTest(dispatcher) {
        model.draft("还没写完的另一条需求"); model.send("推荐酒店"); advanceUntilIdle()
        assertEquals("还没写完的另一条需求", model.state.value.draft)
        assertEquals("推荐酒店", service.sentBody!!["content"].string())
    }
    private class FakeService : TravelService {
        var sends = 0; var reads = 0; var sendStatus = 200; var running = false; var stopFails = false; var readDelay = 0L
        var sentBody: JsonObject? = null
        override suspend fun upload(bytes: ByteArray, mime: String) = "photo"
        override suspend fun request(method: String, path: String, body: JsonObject?, query: List<Pair<String, String>>, authenticated: Boolean): JsonElement {
            if (path == "chat/conversations") return jsonBody("conversation_id" to "a")
            if (method == "POST" && path.endsWith("/messages")) { sends++; sentBody = body; if (sendStatus != 200) throw ApiFailure(sendStatus, "failed"); return jsonBody() }
            if (path.endsWith("/stop")) { if (stopFails) throw ApiFailure(500, "failed"); running = false; return jsonBody() }
            reads++; delay(readDelay)
            return jsonBody("running" to running, "messages" to JsonArray(listOf(jsonBody("id" to "m", "role" to "assistant", "content" to path.split('/')[1]))))
        }
    }
}
