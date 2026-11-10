package com.tongyou.travel.chat

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tongyou.travel.data.*
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.*

@Serializable data class ChatMessage(val id: String, val role: String, val content: String = "", val reasoning: String? = null, val meta: JsonObject? = null) {
    val streaming get() = meta?.get("streaming").bool()
    fun values(key: String) = meta?.get(key).array()
    fun data(key: String) = meta?.get(key)?.obj() ?: JsonObject(emptyMap())
    val guide get() = role == "assistant" && !streaming && !meta?.get("direct").bool() && values("sources").isNotEmpty() && content.contains("##")
}
@Serializable data class MessagesReply(val messages: List<ChatMessage>, val running: Boolean)
data class ChatState(
    val id: String? = null, val messages: List<ChatMessage> = emptyList(), val running: Boolean = false,
    val sending: Boolean = false, val loading: Boolean = false, val stopping: Boolean = false,
    val uploading: Boolean = false, val draft: String = "", val images: List<String> = emptyList(),
    val deep: Boolean = false, val webSearch: Boolean = true, val error: String? = null
)

/** Web search is on by default on every platform; only an explicit choice by the user is remembered. */
interface ChatPrefs { var webSearch: Boolean }
class MemoryChatPrefs(override var webSearch: Boolean = true) : ChatPrefs
class StoredChatPrefs(private val prefs: android.content.SharedPreferences) : ChatPrefs {
    override var webSearch: Boolean
        get() = prefs.getBoolean("web_search", true)
        set(value) { prefs.edit().putBoolean("web_search", value).apply() }
}

/** One send and one sequential poll at a time. Screen lifecycle only pauses reads, never the server task. */
class ChatModel(private val api: TravelService, private val saved: SavedStateHandle, private val io: CoroutineDispatcher = Dispatchers.IO,
                private val prefs: ChatPrefs = MemoryChatPrefs()) : ViewModel() {
    private val mutable = MutableStateFlow(ChatState(id = saved["cid"], draft = saved["draft"] ?: "", webSearch = prefs.webSearch))
    val state = mutable.asStateFlow()
    private var poll: Job? = null
    private var foreground = false
    private var generation = 0
    private var operation: Job? = null
    fun draft(value: String) { saved["draft"] = value; mutable.update { it.copy(draft = value) } }
    fun deep(value: Boolean) { mutable.update { it.copy(deep = value) } }
    fun search(value: Boolean) { prefs.webSearch = value; mutable.update { it.copy(webSearch = value) } }
    fun error(value: String?) { mutable.update { it.copy(error = value) } }
    fun removeImage(id: String) { mutable.update { it.copy(images = it.images - id) } }

    fun activate() { foreground = true; if (!state.value.sending) startPolling(immediate = true) }
    fun deactivate() { foreground = false; poll?.cancel() }
    fun open(id: String? = null, prompt: String = "") {
        if (state.value.sending) return
        generation++; operation?.cancel(); poll?.cancel()
        saved["cid"] = id; saved["draft"] = prompt
        mutable.value = ChatState(id = id, draft = prompt, loading = id != null, deep = state.value.deep, webSearch = state.value.webSearch)
        if (foreground) startPolling(immediate = true)
    }

    fun send(text: String = state.value.draft, location: String = "", forceDeep: Boolean? = null) {
        val before = state.value
        val content = text.trim()
        if (before.sending || before.running || before.uploading || (content.isEmpty() && before.images.isEmpty())) return
        if (content.length > 4000) { error("消息最多 4000 字，请缩短后发送"); return }
        poll?.cancel()
        mutable.update { it.copy(sending = true, error = null) }
        val epoch = generation
        operation = viewModelScope.launch {
            try {
                var id = before.id
                if (id == null) {
                    id = withContext(io) { api.request("POST", "chat/conversations").obj()["conversation_id"].string() }
                    check(id.isNotEmpty()) { "创建会话失败，请重试" }
                    saved["cid"] = id; mutable.update { it.copy(id = id) }
                }
                var accepted = true
                try {
                    withContext(io) { api.request("POST", "chat/$id/messages", jsonBody(
                        "content" to content, "deep_reasoning" to (forceDeep ?: before.deep), "web_search" to before.webSearch,
                        "sandbox_enabled" to false, "location" to location,
                        "image_ids" to JsonArray(before.images.map(::JsonPrimitive)))) }
                } catch (e: ApiFailure) { if (e.status != 409) throw e; accepted = false }
                if (epoch != generation) return@launch
                // 409 means this draft was NOT accepted. Keep it while following the existing turn.
                if (accepted && content == before.draft.trim() && state.value.draft == before.draft) draft("")
                mutable.update { it.copy(sending = false, running = true,
                    images = if (accepted) emptyList() else it.images,
                    error = if (accepted) null else "上一轮仍在进行，当前输入已保留。") }
                startPolling(immediate = true)
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { if (epoch == generation) mutable.update { it.copy(sending = false, error = e.message ?: "发送失败，请重试") } }
        }
    }

    fun stop() {
        val current = state.value
        if (current.id == null || current.stopping || !current.running) return
        mutable.update { it.copy(stopping = true, error = null) }
        val epoch = generation
        viewModelScope.launch {
            try { withContext(io) { api.request("POST", "chat/${current.id}/stop") }; if (epoch == generation) startPolling(true) }
            catch (e: CancellationException) { throw e }
            catch (_: Exception) { if (epoch == generation) mutable.update { it.copy(stopping = false, error = "停止请求未送达，请重试") } }
        }
    }

    fun confirm(id: String, choice: String) {
        val cid = state.value.id ?: return
        val epoch = generation
        viewModelScope.launch {
            try {
                withContext(io) { api.request("POST", "chat/$cid/confirm", jsonBody("confirm_id" to id, "choice" to choice)) }
                if (epoch == generation) startPolling(true)
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { if (epoch == generation) error(e.message) }
        }
    }

    fun upload(read: suspend () -> Pair<ByteArray, String>) {
        if (state.value.uploading || state.value.sending || state.value.images.size >= 4) return
        mutable.update { it.copy(uploading = true, error = null) }
        val epoch = generation
        operation = viewModelScope.launch {
            try {
                val id = withContext(io) { val (bytes, mime) = read(); api.upload(bytes, mime) }
                if (epoch == generation) mutable.update { it.copy(images = it.images + id) }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { if (epoch == generation) error(e.message ?: "图片上传失败") }
            finally { if (epoch == generation) mutable.update { it.copy(uploading = false) } }
        }
    }

    /** 攻略下面的「预算明细 / 手账海报」：后台生成，结果是本对话里新的一条消息。 */
    fun requestExtra(kind: String, messageId: String) {
        val id = state.value.id ?: return
        if (state.value.running) return
        val epoch = generation
        viewModelScope.launch {
            try {
                withContext(io) { api.request("POST", "chat/$id/$kind", jsonBody("message_id" to messageId)) }
                if (epoch == generation) { mutable.update { it.copy(running = true, error = null) }; startPolling(immediate = true) }
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { if (epoch == generation) error(e.message ?: "请求失败，请重试") }
        }
    }

    /** 把攻略转成协同行程；成功后记在消息上，下次直接打开，不重复导入。 */
    suspend fun importTrip(messageId: String): String? {
        val id = state.value.id ?: return null
        return try {
            val trip = withContext(io) { api.request("POST", "trips/import", jsonBody("conversation_id" to id, "message_id" to messageId)).obj()["id"].string() }
            if (trip.isNotEmpty()) mutable.update { s -> s.copy(messages = s.messages.map { m ->
                if (m.id == messageId) m.copy(meta = JsonObject((m.meta ?: JsonObject(emptyMap())) + ("imported_trip_id" to JsonPrimitive(trip)))) else m
            }) }
            trip.ifEmpty { null }
        } catch (e: CancellationException) { throw e }
        catch (e: Exception) { error(e.message ?: "转成行程失败，请重试"); null }
    }

    private fun startPolling(immediate: Boolean = false) {
        poll?.cancel()
        val id = state.value.id ?: return
        if (!foreground) return
        val epoch = generation
        poll = viewModelScope.launch {
            var failures = 0
            if (!immediate) delay(800)
            while (isActive && foreground && epoch == generation) {
                try {
                    val reply = withContext(io) {
                        wireJson.decodeFromJsonElement<MessagesReply>(api.request("GET", "chat/$id/messages"))
                    }
                    if (epoch != generation) return@launch
                    mutable.update { it.copy(messages = reply.messages, running = reply.running, loading = false,
                        stopping = it.stopping && reply.running, error = if (failures > 0) null else it.error) }
                    failures = 0
                    if (!reply.running) return@launch
                } catch (e: CancellationException) { throw e }
                catch (e: Exception) {
                    failures++
                    mutable.update { it.copy(loading = false, error = "连接中断，内容已保留，正在重试…") }
                    if (e is ApiFailure && e.status in listOf(401, 403, 404)) { error(e.message); return@launch }
                }
                delay(if (failures == 0) 800 else (failures * 1600L).coerceAtMost(10000))
            }
        }
    }
}

fun wantsNearby(text: String) = listOf("附近", "周边", "周围", "离我", "我旁边", "就近", "我这边", "我这儿").any(text::contains)
