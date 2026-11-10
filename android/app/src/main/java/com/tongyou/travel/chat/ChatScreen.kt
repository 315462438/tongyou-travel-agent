package com.tongyou.travel.chat

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.animateContentSize
import androidx.compose.animation.core.*
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.*
import androidx.lifecycle.repeatOnLifecycle
import coil.compose.AsyncImage
import com.tongyou.travel.data.*
import com.tongyou.travel.ui.*
import kotlinx.coroutines.*
import kotlinx.serialization.json.*

/** Hairline-bordered translucent surface: the Android stand-in for iOS's glass. */
@Composable private fun Modifier.glass(shape: Shape, tint: Color = MaterialTheme.colorScheme.surface): Modifier =
    clip(shape).background(tint.copy(alpha = .9f), shape).border(1.dp, MaterialTheme.colorScheme.outlineVariant, shape)

private val TASKS = listOf(
    "规划旅行" to "帮我规划一次旅行，目的地是", "找美食" to "帮我推荐当地值得体验的美食，目的地是",
    "整理攻略" to "帮我把这篇攻略整理成行程：", "检查路线" to "帮我检查这份行程的路线和时间安排：")

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun ChatScreen(model: ChatModel, api: TravelService, back: () -> Unit,
                           external: (String) -> Unit, openHistory: () -> Unit, openTrip: (String) -> Unit) {
    val state by model.state.collectAsStateWithLifecycle()
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val haptic = LocalHapticFeedback.current
    val list = rememberLazyListState()
    var preparing by remember { mutableStateOf(false) }
    var pendingText by remember { mutableStateOf("") }
    var addingPlace by remember { mutableStateOf<JsonObject?>(null) }
    val sendWithLocation: (String) -> Unit = { text ->
        preparing = true
        scope.launch {
            try { val location = if (wantsNearby(text)) nearbyLocation(context) else ""; model.send(text, location); haptic.performHapticFeedback(HapticFeedbackType.TextHandleMove) }
            finally { preparing = false }
        }
    }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { sendWithLocation(pendingText) }
    val send: (String) -> Unit = { text ->
        if (!preparing && !state.running && !state.sending) {
            if (wantsNearby(text) && context.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
                pendingText = text; preparing = true; permission.launch(Manifest.permission.ACCESS_COARSE_LOCATION)
            } else sendWithLocation(text)
        }
    }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) model.upload {
            val mime = context.contentResolver.getType(uri).orEmpty()
            val bytes = context.contentResolver.openInputStream(uri)?.use { input ->
                val output = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(16384)
                while (true) { val n = input.read(buffer); if (n < 0) break; require(output.size() + n <= 10 * 1024 * 1024) { "图片不能超过 10 MB" }; output.write(buffer, 0, n) }
                output.toByteArray()
            } ?: error("无法读取图片，请重新选择")
            bytes to mime
        }
    }
    LaunchedEffect(lifecycle, model) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            model.activate()
            try { awaitCancellation() } finally { model.deactivate() }
        }
    }
    val visible = state.messages.filter { it.role != "action" && it.role != "summary" && (it.role != "progress" || !it.meta.isNullOrEmpty()) }
    val landing = state.id == null && visible.isEmpty() && !state.sending && !preparing
    val title = state.messages.firstOrNull { it.role == "user" }?.content?.trim()?.take(16)?.ifBlank { null } ?: "同游 AI"
    val following by remember { derivedStateOf { !list.canScrollForward || list.layoutInfo.visibleItemsInfo.lastOrNull()?.index == list.layoutInfo.totalItemsCount - 1 } }
    LaunchedEffect(visible.size, visible.lastOrNull()?.content?.length, state.running) {
        if (following && list.layoutInfo.totalItemsCount > 0) list.scrollToItem(list.layoutInfo.totalItemsCount - 1)
    }
    Scaffold(containerColor = Color.Transparent, contentWindowInsets = WindowInsets(0), topBar = {
        CenterAlignedTopAppBar(title = { Text(title, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis) },
            navigationIcon = { TextButton(back) { Icon(Icons.Outlined.KeyboardArrowDown, null, Modifier.size(20.dp)); Spacer(Modifier.width(2.dp)); Text("收起") } },
            actions = {
                TextButton(openHistory) { Text("历史") }
                if (!landing) IconButton({ model.open() }, enabled = !state.sending && !preparing) { Icon(Icons.Outlined.EditNote, "新对话") }
            },
            colors = TopAppBarDefaults.centerAlignedTopAppBarColors(containerColor = Color.Transparent), windowInsets = WindowInsets(0))
    }, bottomBar = {
        if (!landing) Column(Modifier.fillMaxWidth().padding(horizontal = 12.dp).padding(top = 6.dp, bottom = 8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            state.error?.let { ErrorNotice(it) { model.activate() } }
            Composer(state, model, preparing, { send(state.draft) }, { picker.launch(arrayOf("image/jpeg", "image/png", "image/gif", "image/webp")) })
        }
    }) { padding ->
        Box(Modifier.padding(padding).fillMaxSize()) {
            LazyColumn(state = list, contentPadding = PaddingValues(start = 20.dp, top = 8.dp, end = 20.dp, bottom = 16.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
                if (landing) item { Landing(state, model, { send(it) }) }
                if (state.loading) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
                val lastAnswer = visible.lastOrNull()?.takeIf { it.role == "assistant" }?.id
                items(visible, key = { it.id }) { message ->
                    when (message.role) {
                        "user" -> UserBubble(message)
                        "progress" -> ProgressRow(message, state, model, message.id == visible.lastOrNull()?.id)
                        else -> AssistantRow(message, state, model, send, external, openTrip, message.id == lastAnswer) { addingPlace = it }
                    }
                }
                if (state.running || state.sending || preparing) item { ThinkingPanel(state, preparing) }
            }
            if (!following && visible.isNotEmpty()) SmallFloatingActionButton({ scope.launch { list.animateScrollToItem(list.layoutInfo.totalItemsCount - 1) } },
                Modifier.align(Alignment.BottomEnd).padding(12.dp), containerColor = MaterialTheme.colorScheme.surface, shape = CircleShape) { Icon(Icons.Outlined.ArrowDownward, "跳到最新消息") }
        }
    }
    addingPlace?.let { place -> AddPlaceDialog(api, place) { addingPlace = null } }
}

// ---------- Landing (same as the iOS AI page) ----------

@Composable private fun Landing(state: ChatState, model: ChatModel, start: (String) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(26.dp), modifier = Modifier.padding(top = 12.dp)) {
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("旅行里的小事，交给我", style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.primary)
            Text("想去哪儿，\n一起想想。", style = MaterialTheme.typography.displaySmall, fontWeight = FontWeight.Bold)
            Text("说一个目的地、贴一篇攻略，或者直接问旅行问题。", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Column(Modifier.fillMaxWidth().glass(RoundedCornerShape(28.dp)).padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            BasicTextField(state.draft, model::draft, Modifier.fillMaxWidth().heightIn(min = 64.dp).testTag("assistant-draft"),
                textStyle = MaterialTheme.typography.bodyLarge.copy(color = MaterialTheme.colorScheme.onSurface), cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
                decorationBox = { inner -> Box { if (state.draft.isEmpty()) Text("输入目的地、粘贴攻略链接，或者问“第一次去日本怎么准备？”", style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurfaceVariant); inner() } })
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ToggleChip("深度推理", if (state.deep) Icons.Outlined.Psychology else Icons.Outlined.Psychology, state.deep) { model.deep(!state.deep) }
                ToggleChip("联网搜索", Icons.Outlined.Public, state.webSearch) { model.search(!state.webSearch) }
                Spacer(Modifier.weight(1f))
                Button({ start(state.draft) }, enabled = state.draft.isNotBlank(), contentPadding = PaddingValues(horizontal = 14.dp), modifier = Modifier.height(36.dp)) {
                    Icon(Icons.Outlined.ArrowUpward, null, Modifier.size(16.dp)); Spacer(Modifier.width(2.dp)); Text("开始", maxLines = 1, softWrap = false)
                }
            }
        }
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            TASKS.chunked(2).forEach { row ->
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    row.forEach { (label, prompt) ->
                        Row(Modifier.weight(1f).glass(RoundedCornerShape(22.dp)).clickable { model.draft(prompt) }.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                            Text(label, Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
                            Icon(Icons.Outlined.NorthEast, null, Modifier.size(16.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
            }
        }
    }
}

@Composable private fun ToggleChip(label: String, icon: androidx.compose.ui.graphics.vector.ImageVector, on: Boolean, toggle: () -> Unit) {
    val tint = if (on) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant
    Row(Modifier.glass(CircleShape, if (on) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surface).clickable(onClick = toggle)
        .padding(horizontal = 10.dp, vertical = 7.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        Icon(icon, null, Modifier.size(15.dp), tint = tint); Text(label, style = MaterialTheme.typography.labelLarge, color = tint, maxLines = 1, softWrap = false)
    }
}

// ---------- Composer: options circle + capsule field + round send (same as iOS) ----------

@Composable private fun Composer(state: ChatState, model: ChatModel, preparing: Boolean, send: () -> Unit, pick: () -> Unit) {
    var options by remember { mutableStateOf(false) }
    val canSend = !preparing && !state.sending && !state.uploading && (state.draft.isNotBlank() || state.images.isNotEmpty())
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (state.images.isNotEmpty() || state.uploading) Row(Modifier.padding(horizontal = 6.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            state.images.forEach { id ->
                Box {
                    AsyncImage(TravelApi.media("/api/uploads/$id"), null, Modifier.size(52.dp).clip(RoundedCornerShape(12.dp)), contentScale = ContentScale.Crop)
                    Icon(Icons.Outlined.Cancel, "移除图片", Modifier.align(Alignment.TopEnd).offset(5.dp, (-5).dp).size(20.dp).clip(CircleShape)
                        .background(Color.Black.copy(alpha = .55f)).clickable { model.removeImage(id) }, tint = Color.White)
                }
            }
            if (state.uploading) Box(Modifier.size(52.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp) }
        }
        Row(verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Box {
                val on = state.deep || state.webSearch
                Box(Modifier.size(44.dp).glass(CircleShape).clickable { options = true }, contentAlignment = Alignment.Center) {
                    Icon(if (state.deep) Icons.Outlined.Psychology else if (state.webSearch) Icons.Outlined.Public else Icons.Outlined.Tune, "回答方式",
                        tint = if (on) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface)
                }
                DropdownMenu(options, { options = false }) {
                    DropdownMenuItem({ Text("联网搜索（查最新信息）") }, { model.search(!state.webSearch) }, leadingIcon = { Icon(Icons.Outlined.Public, null) },
                        trailingIcon = { if (state.webSearch) Icon(Icons.Outlined.Check, null, tint = MaterialTheme.colorScheme.primary) })
                    DropdownMenuItem({ Text("深度推理（更慢更全面）") }, { model.deep(!state.deep) }, leadingIcon = { Icon(Icons.Outlined.Psychology, null) },
                        trailingIcon = { if (state.deep) Icon(Icons.Outlined.Check, null, tint = MaterialTheme.colorScheme.primary) })
                }
            }
            Row(Modifier.weight(1f).heightIn(min = 44.dp).glass(RoundedCornerShape(22.dp)).padding(start = 6.dp, end = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                IconButton(pick, Modifier.size(36.dp), enabled = !state.uploading && !state.sending && state.images.size < 4) {
                    Icon(Icons.Outlined.Image, "添加图片", tint = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.size(20.dp))
                }
                BasicTextField(state.draft, model::draft, Modifier.weight(1f).padding(vertical = 10.dp), enabled = !preparing, maxLines = 6,
                    textStyle = MaterialTheme.typography.bodyLarge.copy(color = MaterialTheme.colorScheme.onSurface), cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
                    decorationBox = { inner -> Box { if (state.draft.isEmpty()) Text("继续问，或补充预算和节奏…", style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1); inner() } })
            }
            val active = state.running || canSend
            Box(Modifier.size(44.dp).clip(CircleShape).background(if (active) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outline.copy(alpha = .5f))
                .clickable(enabled = active && !state.stopping) { if (state.running) model.stop() else send() }, contentAlignment = Alignment.Center) {
                Icon(if (state.running) Icons.Outlined.Stop else Icons.Outlined.ArrowUpward, if (state.running) "停止生成" else "发送", tint = Color.White)
            }
        }
    }
}

// ---------- Rows ----------

@Composable private fun UserBubble(message: ChatMessage) {
    Column(Modifier.fillMaxWidth().padding(start = 48.dp), horizontalAlignment = Alignment.End, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        val images = message.values("images").map { it.string() }
        if (images.isNotEmpty()) Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            images.forEach { AsyncImage(TravelApi.media("/api/uploads/$it"), "上传的图片", Modifier.size(84.dp).clip(RoundedCornerShape(14.dp)), contentScale = ContentScale.Crop) }
        }
        if (message.content.isNotBlank()) Text(message.content, Modifier.clip(RoundedCornerShape(22.dp)).background(MaterialTheme.colorScheme.primary.copy(alpha = .92f))
            .padding(horizontal = 15.dp, vertical = 11.dp), color = Color.White, style = MaterialTheme.typography.bodyLarge)
    }
}

@Composable private fun Card(content: @Composable ColumnScope.() -> Unit) =
    Column(Modifier.fillMaxWidth().glass(RoundedCornerShape(20.dp)).padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp), content = content)

@Composable private fun ProgressRow(message: ChatMessage, state: ChatState, model: ChatModel, isLast: Boolean) {
    val confirm = message.data("confirm")
    val handoff = message.data("handoff")
    when {
        confirm.isNotEmpty() -> Card {
            val id = confirm["id"].string()
            val reply = state.messages.lastOrNull { it.role == "action" && it.data("confirm_reply")["confirm_id"].string() == id }?.data("confirm_reply")?.get("choice").string()
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Icon(Icons.Outlined.VpnKey, null, Modifier.size(18.dp)); Text("需要登录的来源", style = MaterialTheme.typography.titleMedium)
            }
            Text(confirm["question"].string().ifBlank { message.content }, style = MaterialTheme.typography.bodyMedium)
            confirm["source"]?.obj()?.get("title").string().takeIf { it.isNotBlank() }?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
            when {
                reply.isNotBlank() -> Text("已选择：${if (reply == "login") "登录读取" else "跳过"}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                isLast && state.running -> Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Button({ model.confirm(id, "login") }) { Text("登录读取") }; OutlinedButton({ model.confirm(id, "skip") }) { Text("跳过") }
                }
                else -> Text("已超时自动跳过", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        handoff.isNotEmpty() -> Card {
            val site = handoff["site_name"].string().ifBlank { "网站" }
            val remote = handoff["mode"].string() == "remote"
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Icon(Icons.Outlined.QrCodeScanner, null, Modifier.size(18.dp)); Text(if (remote) "用 $site App 扫码登录" else "请在浏览器中登录$site", style = MaterialTheme.typography.titleMedium)
            }
            Text(message.content, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (remote && handoff["screenshot"].bool() && isLast && state.running && state.id != null) {
                var tick by remember { mutableIntStateOf(0) }
                LaunchedEffect(tick) { delay(4000); tick++ }
                AsyncImage(TravelApi.media("/api/chat/${state.id}/handoff-screenshot?t=$tick"), "登录二维码", Modifier.fillMaxWidth().height(300.dp).clip(RoundedCornerShape(14.dp)), contentScale = ContentScale.Fit)
            }
        }
        message.meta?.get("hint").string() == "deep_reasoning" -> Card {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { Icon(Icons.Outlined.Psychology, null, Modifier.size(18.dp)); Text(message.content, style = MaterialTheme.typography.bodyMedium) }
            val prompt = message.meta?.get("hint_prompt").string()
            when {
                prompt.isNotBlank() && !state.running -> OutlinedButton({ model.send(prompt, forceDeep = true) }) { Text("用深度模式重新回答（约 2-6 分钟）") }
                !state.deep -> OutlinedButton({ model.deep(true) }) { Text("打开深度推理") }
                else -> Text("已开启深度推理，重新发送问题即可", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        message.content.isNotBlank() -> Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Icon(Icons.Outlined.Info, null, Modifier.size(16.dp).padding(top = 2.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(message.content, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable private fun AssistantRow(message: ChatMessage, state: ChatState, model: ChatModel, send: (String) -> Unit,
                                     external: (String) -> Unit, openTrip: (String) -> Unit, last: Boolean, addPlace: (JsonObject) -> Unit) {
    var reasoning by remember(message.id) { mutableStateOf(false) }
    var sources by remember(message.id) { mutableStateOf(false) }
    val canSend = !state.running && !state.sending && !state.uploading
    val scope = rememberCoroutineScope()
    val muted = MaterialTheme.colorScheme.onSurfaceVariant
    Column(Modifier.fillMaxWidth().animateContentSize(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        val candidates = message.values("candidates")
        if (candidates.isNotEmpty()) {
            Markdown(message.content)
            candidates.forEach { item -> val c = item.obj()
                Row(Modifier.fillMaxWidth().glass(RoundedCornerShape(18.dp)).clickable(enabled = canSend) { send("去${c["name"].string()}") }.padding(14.dp), verticalAlignment = Alignment.Top) {
                    Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text(c["name"].string(), style = MaterialTheme.typography.titleMedium)
                            c["tag"].string().takeIf { it.isNotBlank() }?.let { Text(it, Modifier.glass(CircleShape).padding(horizontal = 9.dp, vertical = 3.dp), style = MaterialTheme.typography.labelSmall, color = muted) }
                        }
                        Text(c["reason"].string(), style = MaterialTheme.typography.bodyMedium, color = muted)
                    }
                    Icon(Icons.Outlined.NorthEast, null, Modifier.size(18.dp), tint = MaterialTheme.colorScheme.primary)
                }
            }
            Text("都不合适？直接说个地名，或者让我来定。", style = MaterialTheme.typography.bodySmall, color = muted)
            return@Column
        }
        (message.meta?.get("poster") as? JsonObject)?.let { poster -> PosterCard(poster); return@Column }
        (message.meta?.get("budget") as? JsonObject)?.let { budget -> BudgetCard(budget); return@Column }
        if (message.meta?.get("preliminary").bool()) Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            Icon(Icons.Outlined.Lightbulb, null, Modifier.size(16.dp), tint = MaterialTheme.colorScheme.tertiary)
            Text("初步判断 · 正在查证实时资料，完整分析稍后送到", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.tertiary)
        }
        message.reasoning?.takeIf { it.isNotBlank() }?.let { text ->
            Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).clickable { reasoning = !reasoning }.padding(vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Outlined.AutoAwesome, null, Modifier.size(16.dp), tint = muted); Spacer(Modifier.width(6.dp))
                Text("思考过程", Modifier.weight(1f), style = MaterialTheme.typography.labelLarge, color = muted)
                Icon(if (reasoning) Icons.Outlined.ExpandLess else Icons.Outlined.ChevronRight, null, Modifier.size(18.dp), tint = muted)
            }
            if (reasoning) Text(text, style = MaterialTheme.typography.bodySmall, color = muted)
        }
        if (message.content.isBlank() && message.streaming) Text("正在生成…", style = MaterialTheme.typography.bodyMedium, color = muted)
        else if (message.content.isNotBlank()) StreamingBody(message)
        if (message.streaming && message.content.isNotEmpty()) Text("已生成 ${message.content.length} 字", style = MaterialTheme.typography.labelSmall, color = muted)
        if (!message.streaming) {
            val places = message.values("places").map { it.obj() }
            if (places.isNotEmpty()) LazyRow(horizontalArrangement = Arrangement.spacedBy(10.dp), contentPadding = PaddingValues(end = 4.dp)) {
                items(places, key = { it["name"].string() }) { place -> PlaceCard(place, external) { addPlace(place) } }
            }
        }
        val sourceList = message.values("sources").map { it.obj() }
        if (sourceList.isNotEmpty()) Column(Modifier.fillMaxWidth().glass(RoundedCornerShape(16.dp)).clickable { sources = !sources }.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Outlined.Language, null, Modifier.size(16.dp), tint = muted); Spacer(Modifier.width(6.dp))
                val hosts = sourceList.take(3).mapNotNull { runCatching { java.net.URI(it["url"].string()).host?.removePrefix("www.") }.getOrNull() }.joinToString("、")
                Text("参考了 ${sourceList.size} 个网站 · $hosts", Modifier.weight(1f), style = MaterialTheme.typography.labelLarge, color = muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Icon(if (sources) Icons.Outlined.ExpandLess else Icons.Outlined.ChevronRight, null, Modifier.size(18.dp), tint = muted)
            }
            if (sources) sourceList.forEach { source ->
                Column(Modifier.fillMaxWidth().clickable { external(source["url"].string()) }.padding(vertical = 2.dp)) {
                    Text(source["title"].string().ifBlank { source["url"].string() }, style = MaterialTheme.typography.bodyMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    Text(runCatching { java.net.URI(source["url"].string()).host?.removePrefix("www.") }.getOrNull().orEmpty(), style = MaterialTheme.typography.labelSmall, color = muted)
                }
            }
        }
        message.values("memories_saved").map { it.obj() }.filter { it["op"].string() != "delete" }.takeIf { it.isNotEmpty() }?.let { saved ->
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Icon(Icons.Outlined.Psychology, null, Modifier.size(14.dp), tint = muted)
                Text("已记住：" + saved.joinToString("；") { it["content"].string() }, style = MaterialTheme.typography.labelMedium, color = muted)
            }
        }
        if (message.guide) {
            var importing by remember(message.id) { mutableStateOf(false) }
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                val context = LocalContext.current
                Pill("分享计划单", Icons.Outlined.IosShare, true) { shareGuide(context, message.content, state.messages.firstOrNull { it.role == "user" }?.content.orEmpty()) }
                Pill("预算明细", Icons.Outlined.Payments, canSend) { model.requestExtra("budget", message.id) }
                Pill("手账海报", Icons.Outlined.Collections, canSend) { model.requestExtra("poster", message.id) }
                val imported = message.meta?.get("imported_trip_id").string()
                Pill(if (imported.isBlank()) (if (importing) "正在转换…" else "转成协同行程") else "打开协同行程", Icons.Outlined.Map, !importing) {
                    if (imported.isNotBlank()) openTrip(imported)
                    else { importing = true; scope.launch { model.importTrip(message.id)?.let(openTrip); importing = false } }
                }
            }
        }
        // 追问只跟在最后一条回答后面：历史回答下面的旧按钮只会越堆越多。
        if (last && !state.running && !message.streaming && message.values("suggestions").isNotEmpty())
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                message.values("suggestions").forEach { s ->
                    Text(s.string(), Modifier.glass(CircleShape).clickable(enabled = canSend) { send(s.string()) }.padding(horizontal = 14.dp, vertical = 9.dp),
                        style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.primary)
                }
            }
    }
}

@Composable private fun Pill(label: String, icon: androidx.compose.ui.graphics.vector.ImageVector, enabled: Boolean, onClick: () -> Unit) {
    Row(Modifier.glass(CircleShape).clickable(enabled = enabled, onClick = onClick).alpha(if (enabled) 1f else .5f).padding(horizontal = 14.dp, vertical = 9.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        Icon(icon, null, Modifier.size(16.dp)); Text(label, style = MaterialTheme.typography.labelLarge)
    }
}

@Composable private fun PlaceCard(place: JsonObject, external: (String) -> Unit, add: () -> Unit) {
    Column(Modifier.width(208.dp).glass(RoundedCornerShape(18.dp))) {
        Box(Modifier.fillMaxWidth().height(112.dp).background(MaterialTheme.colorScheme.surfaceVariant), contentAlignment = Alignment.Center) {
            val photo = TravelApi.media(place["photo"].string())
            if (photo == null) Icon(Icons.Outlined.Place, null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
            else AsyncImage(photo, place["name"].string(), Modifier.matchParentSize(), contentScale = ContentScale.Crop)
        }
        Column(Modifier.padding(horizontal = 12.dp, vertical = 10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(place["name"].string(), style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (place["address"].string().isNotBlank()) Text(place["address"].string(), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Row(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                val nav = place["nav"] as? JsonObject
                val link = if (nav?.get("domestic").bool()) nav?.get("amap").string() else nav?.get("google").string().ifBlank { nav?.get("apple").string() }
                if (link.isNotBlank()) Text("导航", Modifier.weight(1f).clip(CircleShape).background(MaterialTheme.colorScheme.primary).clickable { external(link) }.padding(vertical = 7.dp),
                    color = MaterialTheme.colorScheme.onPrimary, style = MaterialTheme.typography.labelLarge, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
                Text("加入行程", Modifier.weight(1f).glass(CircleShape).clickable(onClick = add).padding(vertical = 7.dp),
                    style = MaterialTheme.typography.labelLarge, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
            }
        }
    }
}

// ---------- Thinking ----------

@Composable private fun ThinkingPanel(state: ChatState, preparing: Boolean) {
    val lastUser = state.messages.indexOfLast { it.role == "user" }
    val trail = state.messages.drop(lastUser + 1).filter { it.role == "progress" && it.meta.isNullOrEmpty() && it.content.isNotBlank() }.map { it.content }.takeLast(6)
    val streaming = state.messages.any { it.role == "assistant" && it.streaming }
    val status = when { preparing -> "正在获取附近位置…"; trail.isNotEmpty() -> trail.last(); streaming -> "正在生成你的旅行方案…"; else -> "正在理解你的旅行需求…" }
    val pulse = if (LocalMotion.current) rememberInfiniteTransition(label = "think").animateFloat(.35f, 1f, infiniteRepeatable(tween(900), RepeatMode.Reverse), label = "a").value else 1f
    Column(Modifier.fillMaxWidth().glass(RoundedCornerShape(22.dp)).padding(16.dp).animateContentSize(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Icon(Icons.Outlined.AutoAwesome, null, Modifier.size(18.dp).alpha(pulse), tint = MaterialTheme.colorScheme.primary)
            Text(status, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
        trail.dropLast(1).forEach { line ->
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Icon(Icons.Outlined.Check, null, Modifier.size(14.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(line, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

@Composable private fun StreamingBody(message: ChatMessage) {
    val motion = LocalMotion.current
    var displayed by remember(message.id) { mutableStateOf(message.content) }
    LaunchedEffect(message.content, message.streaming, motion) {
        val target = message.content
        if (!motion || !message.streaming || !target.startsWith(displayed)) displayed = target
        else while (displayed.length < target.length) {
            var end = (displayed.length + ((target.length - displayed.length) / 6).coerceAtLeast(8)).coerceAtMost(target.length)
            if (end < target.length && end > 0 && target[end - 1].isHighSurrogate()) end++
            displayed = target.take(end); delay(48)
        }
    }
    Markdown(displayed)
}

/** 把回答里提到的地点加进行程：选已有行程或当场新建，不离开对话。 */
@Composable private fun AddPlaceDialog(api: TravelService, place: JsonObject, dismiss: () -> Unit) {
    var trips by remember { mutableStateOf<List<JsonObject>?>(null) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val name = place["name"].string()
    LaunchedEffect(Unit) {
        trips = try { withContext(Dispatchers.IO) { api.request("GET", "trips").array().map { it.obj() }.filter { it["role"].string() != "viewer" } } }
        catch (e: CancellationException) { throw e } catch (_: Exception) { emptyList() }
    }
    fun add(trip: JsonObject?) {
        if (busy) return
        busy = true; error = null
        scope.launch {
            try {
                val title = trip?.get("title").string().ifBlank { "${name}之行" }
                withContext(Dispatchers.IO) {
                    val id = trip?.get("id").string().ifBlank {
                        api.request("POST", "trips", jsonBody("title" to title, "destination" to "", "days" to 1)).obj()["id"].string()
                    }
                    check(id.isNotEmpty()) { "创建行程失败，请重试" }
                    api.request("POST", "trips/$id/stops", jsonBody("day" to 1, "name" to name,
                        "location" to place["location"].string(), "note" to place["address"].string()))
                }
                android.widget.Toast.makeText(context, "已加入「$title」，可在行程里调整到哪一天", android.widget.Toast.LENGTH_LONG).show()
                dismiss()
            } catch (e: CancellationException) { throw e }
            catch (e: Exception) { error = e.message ?: "加入行程失败，请重试" }
            finally { busy = false }
        }
    }
    SheetDialog(onDismissRequest = { if (!busy) dismiss() }, title = { Text("把「$name」加入") }, text = {
        LazyColumn(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            if (trips == null) item { CircularProgressIndicator() }
            items(trips.orEmpty()) { trip -> TextButton({ add(trip) }, enabled = !busy) { Text(trip["title"].string()) } }
            if (trips != null) item { TextButton({ add(null) }, enabled = !busy) { Text("＋ 新建一个行程") } }
            error?.let { item { ErrorNotice(it) } }
        }
    }, confirmButton = { TextButton(dismiss, enabled = !busy) { Text("取消") } })
}


/** 分享计划单：标题 + 去掉 Markdown 符号的正文，交给系统分享（微信、备忘录等都能收）。 */
private fun shareGuide(context: android.content.Context, markdown: String, question: String) {
    val text = markdown.lines().joinToString("\n") { line ->
        line.replace(Regex("!\\[[^\\]]*]\\([^)]*\\)"), "").replace(Regex("\\[([^\\]]+)]\\([^)]*\\)"), "$1")
            .replace(Regex("^#{1,6}\\s*"), "").replace("**", "").replace(Regex("^\\|?[-:| ]+\\|?$"), "").trimEnd()
    }.replace(Regex("\\n{3,}"), "\n\n").trim()
    val title = question.trim().take(30).ifBlank { "旅行计划" }
    runCatching { context.startActivity(android.content.Intent.createChooser(android.content.Intent(android.content.Intent.ACTION_SEND).setType("text/plain")
        .putExtra(android.content.Intent.EXTRA_SUBJECT, title).putExtra(android.content.Intent.EXTRA_TEXT, "$title\n\n$text\n\n—— 来自 17同游"), "分享计划单")) }
}

/** 手账海报：卡片入口，点开是逐天路线、住宿、美食、贴士（同 iOS PosterCard / PosterSheet）。 */
@Composable private fun PosterCard(poster: JsonObject) {
    var open by remember { mutableStateOf(false) }
    val days = poster["days"].array().map { it.obj() }
    Column(Modifier.fillMaxWidth().glass(RoundedCornerShape(24.dp)).clickable { open = true }) {
        val cover = poster["overall_map"].string().ifBlank { days.firstOrNull()?.get("map").string() }
        TravelApi.media(cover)?.let { AsyncImage(it, null, Modifier.fillMaxWidth().height(160.dp), contentScale = ContentScale.Crop) }
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(poster["title"].string().ifBlank { "旅行手账" }, style = MaterialTheme.typography.titleLarge)
            poster["subtitle"].string().takeIf { it.isNotBlank() }?.let { Text(it, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant) }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("${days.size} 天 · ${poster["foods"].array().size} 美食", Modifier.weight(1f), style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text("查看手账", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
            }
        }
    }
    if (open) SheetDialog(onDismissRequest = { open = false }, title = { Text("旅行手账") }, confirmButton = { TextButton({ open = false }) { Text("完成") } }, text = {
        Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(18.dp)) {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                poster["destination"].string().takeIf { it.isNotBlank() }?.let { Text(it, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary) }
                Text(poster["title"].string().ifBlank { "旅行手账" }, style = MaterialTheme.typography.headlineSmall)
                poster["subtitle"].string().takeIf { it.isNotBlank() }?.let { Text(it, color = MaterialTheme.colorScheme.onSurfaceVariant) }
            }
            days.forEach { day ->
                Column(Modifier.fillMaxWidth().glass(RoundedCornerShape(22.dp)).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("Day ${day["day"].string().ifBlank { day["day"].int().toString() }}", style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.primary)
                        Text(day["title"].string(), style = MaterialTheme.typography.titleMedium)
                    }
                    TravelApi.media(day["map"].string())?.let { AsyncImage(it, null, Modifier.fillMaxWidth().height(170.dp).clip(RoundedCornerShape(16.dp)), contentScale = ContentScale.Crop) }
                    day["stops"].array().map { it.obj() }.forEachIndexed { i, stop ->
                        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                            val photo = TravelApi.media(stop["photo"].string())
                            if (photo != null) AsyncImage(photo, null, Modifier.size(56.dp).clip(RoundedCornerShape(12.dp)), contentScale = ContentScale.Crop)
                            else Box(Modifier.size(56.dp).glass(RoundedCornerShape(12.dp)), contentAlignment = Alignment.Center) { Text("${i + 1}", style = MaterialTheme.typography.titleMedium) }
                            Column {
                                Text(stop["name"].string(), style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
                                stop["note"].string().takeIf { it.isNotBlank() }?.let { Text(it, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                            }
                        }
                    }
                }
            }
            listOf("住宿" to "hotels", "美食" to "foods").forEach { (label, key) ->
                val items = poster[key].array().map { it.obj() }
                if (items.isNotEmpty()) Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(label, style = MaterialTheme.typography.titleLarge)
                    Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        items.forEach { item ->
                            Column(Modifier.width(170.dp).glass(RoundedCornerShape(18.dp)).padding(10.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                TravelApi.media(item["photo"].string())?.let { AsyncImage(it, null, Modifier.fillMaxWidth().height(110.dp).clip(RoundedCornerShape(14.dp)), contentScale = ContentScale.Crop) }
                                Text(item["name"].string(), style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                Text(if (key == "hotels") "${item["area"].string()} ${item["price"].string()}".trim() else item["note"].string(),
                                    style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2, overflow = TextOverflow.Ellipsis)
                            }
                        }
                    }
                }
            }
            val tips = poster["tips"].array().map { it.string() }.filter(String::isNotBlank)
            if (tips.isNotEmpty()) Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("小贴士", style = MaterialTheme.typography.titleLarge)
                tips.forEach { tip -> Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) { Icon(Icons.Outlined.Lightbulb, null, Modifier.size(16.dp)); Text(tip, style = MaterialTheme.typography.bodyMedium) } }
            }
        }
    })
}

/** 预算明细：人均总额、分类占比条、备注（同 iOS BudgetCard）。金额全部是服务端算好的。 */
@Composable private fun BudgetCard(budget: JsonObject) {
    fun yuan(value: JsonElement?) = (value as? JsonPrimitive)?.doubleOrNull?.let { "¥" + "%,d".format(java.util.Locale.US, Math.round(it)) } ?: "—"
    Column(Modifier.fillMaxWidth().glass(RoundedCornerShape(24.dp)).padding(18.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Outlined.Payments, null, Modifier.size(18.dp)); Spacer(Modifier.width(6.dp))
            Text("预算明细", Modifier.weight(1f), style = MaterialTheme.typography.titleMedium)
            Text("人均 " + yuan(budget["total"]), style = MaterialTheme.typography.titleLarge)
        }
        val headcount = budget["headcount"].int()
        if (headcount > 1) Text("$headcount 人合计 ${yuan(budget["group_total"])}", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        budget["by_category"].array().map { it.obj() }.forEach { row ->
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Row { Text(row["category"].string(), Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium); Text(yuan(row["amount"]), style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium) }
                val pct = ((row["pct"] as? JsonPrimitive)?.doubleOrNull ?: 0.0).coerceIn(0.0, 100.0) / 100
                Box(Modifier.fillMaxWidth().height(6.dp).clip(CircleShape).background(MaterialTheme.colorScheme.primary.copy(alpha = .15f))) {
                    Box(Modifier.fillMaxWidth(pct.toFloat()).fillMaxHeight().clip(CircleShape).background(MaterialTheme.colorScheme.primary))
                }
            }
        }
        val reservations = budget["reservations"].array().map { it.obj() }
        if (reservations.isNotEmpty()) Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("需要提前预约", style = MaterialTheme.typography.labelLarge)
            reservations.forEach { r -> Text("· ${r["name"].string()}" + listOf(r["advance"].string(), r["channel"].string()).filter(String::isNotBlank).joinToString(" · ", prefix = "  "),
                style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant) }
        }
        budget["notes"].array().map { it.string() }.filter(String::isNotBlank).forEach { Text("· $it", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant) }
    }
}
