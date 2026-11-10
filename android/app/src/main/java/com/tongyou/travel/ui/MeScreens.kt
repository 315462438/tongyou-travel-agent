package com.tongyou.travel.ui

import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.tongyou.travel.data.*
import kotlinx.coroutines.*
import kotlinx.serialization.json.*

private suspend fun <T> load(error: (String?) -> Unit, block: suspend () -> T): T? = try {
    withContext(Dispatchers.IO) { block() }.also { error(null) }
} catch (e: CancellationException) { throw e } catch (e: Exception) { error(e.message ?: "加载失败，请重试"); null }

/** A pushed page: back arrow, title, and the page's own scrolling content on the shared backdrop. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable fun SubPage(title: String, back: () -> Unit, actions: @Composable RowScope.() -> Unit = {}, content: LazyListScope.() -> Unit) {
    Scaffold(containerColor = Color.Transparent, contentWindowInsets = WindowInsets(0), topBar = {
        CenterAlignedTopAppBar(title = { Text(title) }, navigationIcon = { IconButton(back) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "返回") } }, actions = actions,
            colors = TopAppBarDefaults.centerAlignedTopAppBarColors(containerColor = Color.Transparent), windowInsets = WindowInsets(0))
    }) { padding ->
        LazyColumn(Modifier.padding(padding), contentPadding = PaddingValues(start = 20.dp, top = 8.dp, end = 20.dp, bottom = 32.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp), content = content)
    }
}

@Composable private fun Avatar(user: JsonObject, size: Int = 40) {
    val name = user["display_name"].string().ifBlank { user["username"].string() }
    Box(Modifier.size(size.dp).clip(CircleShape).background(MaterialTheme.colorScheme.primary), contentAlignment = Alignment.Center) {
        Text(name.take(1), color = MaterialTheme.colorScheme.onPrimary, style = MaterialTheme.typography.titleMedium)
        TravelApi.media(user["avatar_url"].string())?.let { AsyncImage(it, null, Modifier.matchParentSize(), contentScale = ContentScale.Crop) }
    }
}

@Composable private fun PersonRow(user: JsonObject, trailing: @Composable RowScope.() -> Unit) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Avatar(user)
        Column(Modifier.weight(1f)) {
            Text(user["display_name"].string().ifBlank { user["username"].string() }, style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text("@" + user["username"].string() + user["home_city"].string().let { if (it.isBlank()) "" else " · $it" },
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
        }
        trailing()
    }
}

/** 好友：搜索加人、处理申请、看列表。好友不会自动看到私人行程，只是邀请同行时更好找人。 */
@Composable fun FriendsScreen(api: TravelService, back: () -> Unit) {
    var groups by remember { mutableStateOf<JsonObject?>(null) }
    var results by remember { mutableStateOf<List<JsonObject>>(emptyList()) }
    var query by rememberSaveable { mutableStateOf("") }
    var message by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var reload by remember { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(reload) { load({ message = it }) { api.request("GET", "social/friends").obj() }?.let { groups = it } }
    fun act(block: suspend () -> Unit) { if (busy) return; busy = true; scope.launch { try { load({ message = it }) { block() } } finally { busy = false; reload++ } } }
    fun search() { if (query.isBlank() || busy) return; busy = true; scope.launch {
        load({ message = it }) { api.request("GET", "social/users", query = listOf("q" to query.trim())).obj()["users"].array().map { it.obj() } }?.let {
            results = it; if (it.isEmpty()) message = "没有找到这个人，确认一下用户名。"
        }
        busy = false
    } }
    SubPage("好友", back) {
        item {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(query, { query = it }, Modifier.weight(1f), placeholder = { Text("搜索用户名或昵称") }, singleLine = true, shape = RoundedCornerShape(24.dp))
                Button({ search() }, enabled = !busy && query.isNotBlank()) { Text("搜索") }
            }
        }
        message?.let { item { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) } }
        if (results.isNotEmpty()) item {
            GlassCard(Modifier.fillMaxWidth()) {
                results.forEach { person -> PersonRow(person) {
                    when (person["friendship_status"].string()) {
                        "accepted" -> Text("已是好友", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        "pending" -> Text("申请处理中", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        else -> TextButton({ act { api.request("POST", "social/friends/request/${person["id"].string()}"); results = results.map {
                            if (it["id"].string() == person["id"].string()) JsonObject(it + ("friendship_status" to JsonPrimitive("pending"))) else it } } }, enabled = !busy) { Text("加好友") }
                    }
                } }
            }
        }
        val received = groups?.get("received").array().map { it.obj() }
        if (received.isNotEmpty()) item {
            Text("新的好友申请", style = MaterialTheme.typography.titleMedium); Spacer(Modifier.height(8.dp))
            GlassCard(Modifier.fillMaxWidth()) {
                received.forEach { person -> PersonRow(person) {
                    TextButton({ act { api.request("POST", "social/friends/${person["friendship_id"].string()}/respond", jsonBody("accept" to false)) } }, enabled = !busy) { Text("忽略") }
                    Button({ act { api.request("POST", "social/friends/${person["friendship_id"].string()}/respond", jsonBody("accept" to true)) } }, enabled = !busy) { Text("接受") }
                } }
            }
        }
        val friends = groups?.get("friends").array().map { it.obj() }
        item {
            Text("我的好友 · ${friends.size}", style = MaterialTheme.typography.titleMedium); Spacer(Modifier.height(8.dp))
            GlassCard(Modifier.fillMaxWidth()) {
                if (groups == null) LinearProgressIndicator(Modifier.fillMaxWidth())
                else if (friends.isEmpty()) Text("还没有好友。在上面搜索对方的用户名或昵称，发个申请。", color = MaterialTheme.colorScheme.onSurfaceVariant)
                friends.forEach { person -> PersonRow(person) {} }
            }
        }
        val sent = groups?.get("sent").array().map { it.obj() }
        if (sent.isNotEmpty()) item {
            Text("已发送的申请", style = MaterialTheme.typography.titleMedium); Spacer(Modifier.height(8.dp))
            GlassCard(Modifier.fillMaxWidth()) { sent.forEach { person -> PersonRow(person) { Text("等待对方确认", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) } } }
        }
    }
}

@Composable fun HistoryScreen(api: TravelService, back: () -> Unit, open: (String) -> Unit) {
    var rows by remember { mutableStateOf<List<JsonObject>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var query by rememberSaveable { mutableStateOf("") }
    var removing by remember { mutableStateOf<JsonObject?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(reload) { load({ error = it }) { api.request("GET", "chat/conversations").array().map { it.obj() } }?.let { rows = it } }
    val shown = rows.orEmpty().filter { query.isBlank() || it["title"].string().contains(query.trim(), ignoreCase = true) }
    SubPage("历史对话", back) {
        item { OutlinedTextField(query, { query = it }, Modifier.fillMaxWidth(), placeholder = { Text("搜索对话") }, singleLine = true, shape = RoundedCornerShape(24.dp)) }
        error?.let { item { ErrorNotice(it) { reload++ } } }
        if (rows == null && error == null) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
        if (rows != null && shown.isEmpty()) item { Text(if (query.isBlank()) "还没有对话，点「问 AI」说一个目的地开始吧。" else "没有找到相关对话，换个关键词试试。", color = MaterialTheme.colorScheme.onSurfaceVariant) }
        items(shown, key = { it["id"].string() }) { conversation ->
            Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(MaterialTheme.colorScheme.surface.copy(alpha = .92f))
                .border(1.dp, MaterialTheme.colorScheme.outlineVariant, RoundedCornerShape(18.dp)).clickable { open(conversation["id"].string()) }
                .padding(start = 16.dp, top = 6.dp, bottom = 6.dp, end = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(conversation["title"].string().ifBlank { "新对话" }, Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                IconButton({ removing = conversation }) { Icon(Icons.Outlined.DeleteOutline, "删除对话", tint = MaterialTheme.colorScheme.onSurfaceVariant) }
            }
        }
    }
    removing?.let { conversation ->
        AlertDialog(onDismissRequest = { removing = null }, title = { Text("删除这段对话？") }, text = { Text(conversation["title"].string()) },
            confirmButton = { TextButton({ removing = null; scope.launch { load({ error = it }) { api.request("DELETE", "chat/conversations/${conversation["id"].string()}") }; reload++ } }) { Text("删除", color = MaterialTheme.colorScheme.error) } },
            dismissButton = { TextButton({ removing = null }) { Text("取消") } })
    }
}

/** 通知 + 平台公告。点通知会标记已读并去到对应的地方。 */
@Composable fun NotificationsScreen(api: TravelService, back: () -> Unit, go: (kind: String, id: String, poll: TripNotification?) -> Unit) {
    var notices by remember { mutableStateOf<List<JsonObject>?>(null) }
    var announcements by remember { mutableStateOf<List<JsonObject>>(emptyList()) }
    var error by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    var reading by remember { mutableStateOf<JsonObject?>(null) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(reload) {
        load({ error = it }) { api.request("GET", "notifications").obj()["notifications"].array().map { it.obj() } }?.let { notices = it }
        load({}) { api.request("GET", "announcements").obj()["announcements"].array().map { it.obj() } }?.let { announcements = it }
    }
    SubPage("通知", back, actions = { TextButton({ scope.launch { load({ error = it }) { api.request("POST", "notifications/read-all") }; reload++ } }) { Text("全部已读") } }) {
        error?.let { item { ErrorNotice(it) { reload++ } } }
        if (notices == null && error == null) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
        if (notices?.isEmpty() == true && announcements.isEmpty()) item { Text("没有新通知。好友申请和行程消息会出现在这里。", color = MaterialTheme.colorScheme.onSurfaceVariant) }
        items(notices.orEmpty(), key = { it["id"].string() }) { notice ->
            val unread = !notice["read"].bool()
            Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(MaterialTheme.colorScheme.surface.copy(alpha = .92f))
                .border(1.dp, if (unread) MaterialTheme.colorScheme.primary.copy(alpha = .4f) else MaterialTheme.colorScheme.outlineVariant, RoundedCornerShape(18.dp))
                .clickable {
                    scope.launch { load({}) { api.request("POST", "notifications/${notice["id"].string()}/read") }; reload++ }
                    val meta = notice["meta"]?.obj().orEmpty()
                    go(if (notice["type"].string().startsWith("friend")) "friends" else notice["target_kind"].string(), meta["trip_id"].string().ifBlank { notice["target_id"].string() }, TripNotification.from(notice))
                }.padding(16.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Avatar(notice["actor"]?.obj() ?: JsonObject(emptyMap()), 36)
                Column(Modifier.weight(1f)) {
                    Text(notice["title"].string(), style = MaterialTheme.typography.bodyLarge, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    if (notice["body"].string().isNotBlank()) Text(notice["body"].string(), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2, overflow = TextOverflow.Ellipsis)
                }
                if (unread) Box(Modifier.padding(top = 6.dp).size(8.dp).clip(CircleShape).background(MaterialTheme.colorScheme.primary))
            }
        }
        if (announcements.isNotEmpty()) item { Text("平台公告", style = MaterialTheme.typography.titleMedium) }
        items(announcements, key = { "a-" + it["id"].string() }) { item ->
            GlassCard(Modifier.fillMaxWidth().clip(RoundedCornerShape(24.dp)).clickable {
                reading = item
                if (!item["read"].bool()) scope.launch { load({}) { api.request("POST", "announcements/${item["id"].string()}/read") }; reload++ }
            }) {
                Text((if (item["read"].bool()) "" else "● ") + item["title"].string(), style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(item["content"].string(), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
        }
    }
    reading?.let { item ->
        AlertDialog(onDismissRequest = { reading = null }, title = { Text(item["title"].string()) },
            text = { Text(item["content"].string(), Modifier.verticalScroll(rememberScrollState())) }, confirmButton = { TextButton({ reading = null }) { Text("知道了") } })
    }
}
