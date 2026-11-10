package com.tongyou.travel.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.automirrored.outlined.Send
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.tongyou.travel.data.*
import kotlinx.coroutines.*
import kotlinx.serialization.json.*

private suspend fun <T> run(error: (String?) -> Unit, block: suspend () -> T): T? = try {
    withContext(Dispatchers.IO) { block() }.also { error(null) }
} catch (e: CancellationException) { throw e } catch (e: Exception) { error(e.message ?: "操作失败，请重试"); null }

@Composable private fun Muted(text: String) = Text(text, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)

@Composable private fun Row2(title: String, subtitle: String = "", onClick: (() -> Unit)? = null, trailing: @Composable RowScope.() -> Unit = {}) {
    Row(Modifier.fillMaxWidth().then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier).padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge, maxLines = 2, overflow = TextOverflow.Ellipsis)
            if (subtitle.isNotBlank()) Muted(subtitle)
        }
        trailing()
    }
}

// ---------- 个人资料 ----------

@Composable fun ProfileScreen(api: TravelService, back: () -> Unit, changePassword: () -> Unit, saved: () -> Unit) {
    var name by rememberSaveable { mutableStateOf("") }
    var bio by rememberSaveable { mutableStateOf("") }
    var city by rememberSaveable { mutableStateOf("") }
    var avatar by rememberSaveable { mutableStateOf("") }          // upload id
    var loaded by remember { mutableStateOf<JsonObject?>(null) }
    var message by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    LaunchedEffect(Unit) {
        run({ message = it }) { api.request("GET", "social/me").obj() }?.let { me ->
            loaded = me; name = me["display_name"].string(); bio = me["bio"].string(); city = me["home_city"].string()
            avatar = me["avatar_url"].string().substringAfterLast("/uploads/", "")
        }
    }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) scope.launch {
            busy = true
            run({ message = it }) {
                val mime = context.contentResolver.getType(uri).orEmpty()
                val bytes = context.contentResolver.openInputStream(uri)?.use { it.readBytes() } ?: error("无法读取图片")
                api.upload(bytes, mime)
            }?.let { avatar = it }
            busy = false
        }
    }
    SubPage("个人资料", back, actions = { TextButton({ busy = true; scope.launch {
        val me = loaded
        val done = run({ message = it }) { api.request("PATCH", "social/me", jsonBody("display_name" to name.trim(), "bio" to bio.trim(), "home_city" to city.trim(),
            "travel_styles" to (me?.get("travel_styles") ?: JsonArray(emptyList())), "profile_public" to (me?.get("profile_public").bool()),
            "avatar_upload_id" to avatar.ifBlank { null })) }
        busy = false
        if (done != null) { message = "已保存"; saved() }
    } }, enabled = !busy && loaded != null) { Text("保存", fontWeight = FontWeight.SemiBold) } }) {
        item {
            Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Box(Modifier.size(84.dp).clip(CircleShape).background(MaterialTheme.colorScheme.primary).clickable(enabled = !busy) {
                    picker.launch(arrayOf("image/jpeg", "image/png", "image/webp", "image/gif")) }, contentAlignment = Alignment.Center) {
                    Text(name.ifBlank { "我" }.take(1), color = MaterialTheme.colorScheme.onPrimary, style = MaterialTheme.typography.headlineMedium)
                    if (avatar.isNotBlank()) AsyncImage(TravelApi.media("/api/uploads/$avatar"), null, Modifier.matchParentSize(), contentScale = ContentScale.Crop)
                }
                TextButton({ picker.launch(arrayOf("image/jpeg", "image/png", "image/webp", "image/gif")) }, enabled = !busy) { Text("更换头像") }
            }
        }
        item {
            GlassCard(Modifier.fillMaxWidth()) {
                OutlinedTextField(name, { name = it.take(40) }, Modifier.fillMaxWidth(), label = { Text("显示名称") }, singleLine = true)
                OutlinedTextField(city, { city = it.take(64) }, Modifier.fillMaxWidth(), label = { Text("常驻城市") }, singleLine = true)
                OutlinedTextField(bio, { bio = it.take(240) }, Modifier.fillMaxWidth(), label = { Text("个人简介") }, maxLines = 4)
            }
        }
        message?.let { item { Muted(it) } }
        item { GlassCard(Modifier.fillMaxWidth()) { Row2("修改密码", onClick = changePassword) { Text("›", color = MaterialTheme.colorScheme.onSurfaceVariant) } } }
    }
}

/** 改密码后服务端会签发新令牌，旧令牌全部作废：必须把新令牌交回会话，否则下一个请求就被登出。 */
@Composable fun ChangePasswordSheet(api: TravelService, forced: Boolean, dismiss: () -> Unit, newToken: (String) -> Unit) {
    var old by remember { mutableStateOf("") }
    var fresh by remember { mutableStateOf("") }
    var again by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    SheetDialog(onDismissRequest = { if (!busy && !forced) dismiss() }, title = { Text("修改密码") },
        dismissButton = { if (!forced) TextButton(dismiss, enabled = !busy) { Text("取消") } },
        confirmButton = { TextButton({
            if (fresh.length < 6) { error = "新密码至少 6 位"; return@TextButton }
            if (fresh != again) { error = "两次输入的新密码不一样"; return@TextButton }
            busy = true
            scope.launch {
                run({ error = it }) { api.request("POST", "auth/change-password", jsonBody("old_password" to old, "new_password" to fresh)).obj()["token"].string() }
                    ?.takeIf { it.isNotEmpty() }?.let { newToken(it) }
                busy = false
            }
        }, enabled = !busy && old.isNotEmpty() && fresh.isNotEmpty()) { Text(if (busy) "保存中…" else "保存") } },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                if (forced) Muted("为了账号安全，请先把初始密码改掉。")
                listOf(Triple("原密码", old) { v: String -> old = v }, Triple("新密码（至少 6 位）", fresh) { v: String -> fresh = v }, Triple("再输一次新密码", again) { v: String -> again = v })
                    .forEach { (label, value, set) ->
                        OutlinedTextField(value, set, Modifier.fillMaxWidth(), label = { Text(label) }, singleLine = true, enabled = !busy,
                            visualTransformation = PasswordVisualTransformation(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password))
                    }
                error?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) }
            }
        })
}

// ---------- 旅行偏好与记忆 ----------

@Composable fun MemoryScreen(api: TravelService, back: () -> Unit) {
    var rows by remember { mutableStateOf<List<JsonObject>?>(null) }
    var message by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var reload by remember { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(reload) { run({ message = it }) { api.request("GET", "memory").array().map { it.obj() } }?.let { rows = it } }
    SubPage("旅行偏好与记忆", back, actions = { TextButton({ busy = true; message = "正在整理，大约十几秒…"; scope.launch {
        if (run({ message = it }) { api.request("POST", "memory/consolidate") } != null) message = "已整理"
        busy = false; reload++
    } }, enabled = !busy && !rows.isNullOrEmpty()) { Text("整理") } }) {
        item { Muted("聊天时记下的偏好会用在之后的规划里。不对的可以删掉。") }
        message?.let { item { Muted(it) } }
        if (rows == null) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
        if (rows?.isEmpty() == true) item { Muted("还没有记忆。多聊几次，我会记住你的口味和节奏。") }
        items(rows.orEmpty(), key = { it["id"].string() }) { memory ->
            GlassCard(Modifier.fillMaxWidth()) {
                Row2(memory["content"].string(), listOfNotNull(memory["key"].string().ifBlank { null }, if (memory["explicit"].bool()) "你亲口说的" else null,
                    memory["updated_at"].string().take(10).ifBlank { null }?.let { "更新于 $it" }).joinToString(" · ")) {
                    IconButton({ scope.launch { run({ message = it }) { api.request("DELETE", "memory/${memory["id"].string()}") }; reload++ } }) {
                        Icon(Icons.Outlined.DeleteOutline, "删除这条记忆", tint = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
    }
}

// ---------- 技能 ----------

@Composable fun SkillsScreen(api: TravelService, back: () -> Unit) {
    var rows by remember { mutableStateOf<List<JsonObject>?>(null) }
    var message by remember { mutableStateOf<String?>(null) }
    var adding by remember { mutableStateOf(false) }
    var reload by remember { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(reload) { run({ message = it }) { api.request("GET", "skills").array().map { it.obj() } }?.let { rows = it } }
    SubPage("技能", back, actions = { IconButton({ adding = true }) { Icon(Icons.Outlined.Add, "添加技能") } }) {
        item { Muted("技能是一段写给 AI 的说明（SKILL.md），深度推理时会按需取用。") }
        message?.let { item { Muted(it) } }
        if (rows == null) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
        if (rows?.isEmpty() == true) item { Muted("还没有技能。点右上角添加。") }
        items(rows.orEmpty(), key = { it["id"].string() }) { skill ->
            GlassCard(Modifier.fillMaxWidth()) {
                Row2(skill["name"].string(), skill["description"].string()) {
                    IconButton({ scope.launch { run({ message = it }) { api.request("DELETE", "skills/${skill["id"].string()}") }; reload++ } }) {
                        Icon(Icons.Outlined.DeleteOutline, "删除技能", tint = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
    }
    if (adding) {
        var content by rememberSaveable { mutableStateOf("---\nname: \ndescription: \n---\n\n") }
        var busy by remember { mutableStateOf(false) }
        var error by remember { mutableStateOf<String?>(null) }
        SheetDialog(onDismissRequest = { if (!busy) adding = false }, title = { Text("添加技能") },
            dismissButton = { TextButton({ adding = false }, enabled = !busy) { Text("取消") } },
            confirmButton = { TextButton({ busy = true; scope.launch {
                if (run({ error = it }) { api.request("POST", "skills", jsonBody("content" to content)) } != null) { adding = false; reload++ }
                busy = false
            } }, enabled = !busy && content.isNotBlank()) { Text("保存") } },
            text = { Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(content, { content = it }, Modifier.fillMaxWidth().heightIn(min = 220.dp), label = { Text("SKILL.md") })
                error?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) }
            } })
    }
}

// ---------- 连接（扫码） ----------

@Composable fun ConnectorsScreen(api: TravelService, back: () -> Unit) {
    var rows by remember { mutableStateOf<List<JsonObject>?>(null) }
    var session by remember { mutableStateOf<JsonObject?>(null) }
    var message by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(reload) { run({ message = it }) { api.request("GET", "connectors").obj()["connectors"].array().map { it.obj() } }?.let { rows = it } }
    // 扫码进行中：每 2 秒取一次状态，截图跟着刷新；结束后刷新列表
    LaunchedEffect(session?.get("token").string()) {
        while (isActive && session != null && session?.get("state").string() !in setOf("connected", "failed", "timeout", "cancelled", "idle")) {
            delay(2000)
            run({}) { api.request("GET", "connectors/connect/status").obj() }?.let { session = it }
        }
        if (session != null) reload++
    }
    SubPage("连接", back) {
        item { Muted("连接后，AI 可以用你的账号读取这些网站上属于你的内容。断开会清掉登录状态。") }
        message?.let { item { Muted(it) } }
        if (rows == null) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
        items(rows.orEmpty(), key = { it["key"].string() }) { c ->
            GlassCard(Modifier.fillMaxWidth()) {
                Row2(c["name"].string(), c["summary"].string()) {
                    when {
                        !c["connectable"].bool() -> Muted("内置")
                        c["connected"].bool() -> TextButton({ scope.launch { run({ message = it }) { api.request("DELETE", "connectors/${c["key"].string()}") }; reload++ } }) { Text("断开") }
                        else -> Button({ scope.launch { run({ message = it }) { api.request("POST", "connectors/${c["key"].string()}/connect").obj() }?.let { session = it } } },
                            enabled = session == null) { Text("连接") }
                    }
                }
                c["note"].string().takeIf { it.isNotBlank() }?.let { Muted(it) }
            }
        }
    }
    session?.let { current ->
        val state = current["state"].string()
        SheetDialog(onDismissRequest = {}, title = { Text("扫码连接") },
            dismissButton = { TextButton({ scope.launch { run({}) { api.request("DELETE", "connectors/connect") }; session = null; reload++ } }) { Text(if (state == "waiting" || state == "starting") "取消" else "关闭") } },
            confirmButton = {},
            text = { Column(verticalArrangement = Arrangement.spacedBy(10.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                Text(current["message"].string().ifBlank { if (state == "connected") "已连接" else "正在打开登录页…" }, style = MaterialTheme.typography.bodyMedium)
                val shot = current["screenshot_token"].string()
                if (shot.isNotBlank()) {
                    var tick by remember { mutableIntStateOf(0) }
                    LaunchedEffect(tick) { delay(3000); tick++ }
                    AsyncImage(TravelApi.media("/api/connectors/connect/$shot/screenshot?t=$tick"), "登录二维码", Modifier.fillMaxWidth().height(320.dp).clip(RoundedCornerShape(14.dp)), contentScale = ContentScale.Fit)
                    Muted("用对应 App 扫上面的二维码登录")
                } else if (state != "connected" && state != "failed") CircularProgressIndicator()
            } })
    }
}

// ---------- 帮助与反馈（客服） ----------

@Composable fun SupportScreen(api: TravelService, back: () -> Unit, title: String = "帮助与反馈", path: String = "support/messages") {
    var rows by remember { mutableStateOf<List<JsonObject>>(emptyList()) }
    var draft by rememberSaveable { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val list = rememberLazyListState()
    val mine = if (path.startsWith("admin")) "admin" else "user"
    LaunchedEffect(path) {
        while (isActive) {
            run({ error = it }) { api.request("GET", path).let { (it as? JsonArray) ?: it.obj()["messages"].array() }.map { it.obj() } }?.let { rows = it }
            delay(5000)
        }
    }
    LaunchedEffect(rows.size) { if (rows.isNotEmpty()) list.scrollToItem(rows.size - 1) }
    androidx.compose.material3.Scaffold(containerColor = androidx.compose.ui.graphics.Color.Transparent, contentWindowInsets = WindowInsets(0), topBar = {
        @OptIn(ExperimentalMaterial3Api::class) CenterAlignedTopAppBar(title = { Text(title) }, navigationIcon = { IconButton(back) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "返回") } },
            colors = TopAppBarDefaults.centerAlignedTopAppBarColors(containerColor = androidx.compose.ui.graphics.Color.Transparent), windowInsets = WindowInsets(0))
    }, bottomBar = {
        Row(Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedTextField(draft, { draft = it.take(2000) }, Modifier.weight(1f), placeholder = { Text("说说遇到的问题或建议…") }, maxLines = 4, shape = RoundedCornerShape(22.dp))
            FilledIconButton({ busy = true; val text = draft.trim(); scope.launch {
                if (run({ error = it }) { api.request("POST", path, jsonBody("content" to text)) } != null) {
                    draft = ""; run({}) { api.request("GET", path).let { (it as? JsonArray) ?: it.obj()["messages"].array() }.map { it.obj() } }?.let { rows = it }
                }
                busy = false
            } }, enabled = !busy && draft.isNotBlank(), modifier = Modifier.size(48.dp)) { Icon(Icons.AutoMirrored.Outlined.Send, "发送") }
        }
    }) { padding ->
        LazyColumn(Modifier.padding(padding), state = list, contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (rows.isEmpty()) item { Muted(if (mine == "user") "有问题、建议或者想要的功能，直接发在这里，我们会尽快回复。" else "还没有消息。") }
            items(rows, key = { it["id"].string() }) { m ->
                val own = m["sender"].string() == mine
                Column(Modifier.fillMaxWidth(), horizontalAlignment = if (own) Alignment.End else Alignment.Start) {
                    Text(m["content"].string(), Modifier.padding(start = if (own) 48.dp else 0.dp, end = if (own) 0.dp else 48.dp).clip(RoundedCornerShape(18.dp))
                        .background(if (own) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surface).padding(horizontal = 14.dp, vertical = 10.dp),
                        color = if (own) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurface, style = MaterialTheme.typography.bodyMedium)
                    Muted(m["created_at"].string().replace('T', ' ').take(16))
                }
            }
            error?.let { item { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) } }
        }
    }
}

// ---------- 管理（仅管理员） ----------

@Composable fun AdminScreen(api: TravelService, back: () -> Unit, openThread: (String, String) -> Unit) {
    var tab by rememberSaveable { mutableIntStateOf(0) }
    var users by remember { mutableStateOf<List<JsonObject>?>(null) }
    var invites by remember { mutableStateOf<List<JsonObject>>(emptyList()) }
    var threads by remember { mutableStateOf<List<JsonObject>>(emptyList()) }
    var message by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    var title by rememberSaveable { mutableStateOf("") }
    var content by rememberSaveable { mutableStateOf("") }
    val scope = rememberCoroutineScope()
    fun act(block: suspend () -> Unit) { scope.launch { run({ message = it }) { block() }; reload++ } }
    LaunchedEffect(reload, tab) {
        when (tab) {
            0 -> run({ message = it }) { api.request("GET", "admin/users").obj()["users"].array().map { it.obj() } }?.let { users = it }
            1 -> run({ message = it }) { api.request("GET", "admin/invites").obj()["invites"].array().map { it.obj() } }?.let { invites = it }
            3 -> run({ message = it }) { api.request("GET", "admin/support/threads").obj()["threads"].array().map { it.obj() } }?.let { threads = it }
        }
    }
    SubPage("管理", back) {
        item {
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("用户", "邀请码", "发公告", "客服").forEachIndexed { i, label -> FilterChip(tab == i, { tab = i; message = null }, { Text(label) }) }
            }
        }
        message?.let { item { Muted(it) } }
        when (tab) {
            0 -> items(users.orEmpty(), key = { it["id"].string() }) { u ->
                GlassCard(Modifier.fillMaxWidth()) {
                    Row2("@" + u["username"].string() + if (u["is_admin"].bool()) " · 管理员" else "",
                        "${u["conversations"].int()} 个对话 · ${u["memories"].int()} 条记忆 · 注册于 ${u["created_at"].string().take(10)}") {
                        TextButton({ act { api.request("PATCH", "admin/users/${u["id"].string()}/role", jsonBody("is_admin" to !u["is_admin"].bool())) } }) {
                            Text(if (u["is_admin"].bool()) "取消管理员" else "设为管理员")
                        }
                    }
                    TextButton({ openThread(u["id"].string(), u["username"].string()) }, contentPadding = PaddingValues(0.dp)) { Text("发消息") }
                }
            }
            1 -> {
                item { Button({ act { val row = api.request("POST", "admin/invites", jsonBody("max_uses" to null)).obj(); message = "新邀请码：${row["code"].string()}" } }) { Text("生成邀请码") } }
                items(invites, key = { it["code"].string() }) { code ->
                    GlassCard(Modifier.fillMaxWidth()) {
                        Row2(code["code"].string(), "已用 ${code["used_count"].int()} / ${code["max_uses"].int()}" + if (code["usable"].bool()) "" else " · 已失效") {
                            if (code["usable"].bool()) TextButton({ act { api.request("DELETE", "admin/invites/${code["code"].string()}") } }) { Text("停用") }
                        }
                    }
                }
            }
            2 -> item {
                GlassCard(Modifier.fillMaxWidth()) {
                    OutlinedTextField(title, { title = it }, Modifier.fillMaxWidth(), label = { Text("公告标题") }, singleLine = true)
                    OutlinedTextField(content, { content = it }, Modifier.fillMaxWidth().heightIn(min = 140.dp), label = { Text("公告内容") })
                    Button({ act { api.request("POST", "admin/announcements", jsonBody("title" to title.trim(), "content" to content.trim())); title = ""; content = ""; message = "已发布" } },
                        enabled = title.isNotBlank() && content.isNotBlank()) { Text("发布") }
                }
            }
            else -> {
                if (threads.isEmpty()) item { Muted("还没有用户来找客服。") }
                items(threads, key = { it["user_id"].string() }) { t ->
                    GlassCard(Modifier.fillMaxWidth().clip(RoundedCornerShape(24.dp)).clickable { openThread(t["user_id"].string(), t["username"].string()) }) {
                        Row2("@" + t["username"].string(), t["last_excerpt"].string()) {
                            if (t["unread"].int() > 0) Badge { Text(t["unread"].int().toString()) }
                        }
                    }
                }
            }
        }
    }
}
