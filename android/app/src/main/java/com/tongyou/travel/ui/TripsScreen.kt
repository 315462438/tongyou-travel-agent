package com.tongyou.travel.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.widget.Toast
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import com.tongyou.travel.data.*
import kotlinx.coroutines.*
import kotlinx.serialization.json.*
import java.time.LocalDate

private suspend fun <T> call(error: (String?) -> Unit, block: suspend () -> T): T? = try {
    withContext(Dispatchers.IO) { block() }.also { error(null) }
} catch (e: CancellationException) { throw e } catch (e: Exception) { error(e.message ?: "操作失败，请重试"); null }

/** "2026-11-10" or null. Accepts what people actually type: 11.10, 11/10, 11月10日, 2026-11-10. */
fun parseTripDate(text: String, today: LocalDate = LocalDate.now()): String? {
    val parts = Regex("\\d+").findAll(text).map { it.value.toInt() }.toList()
    val (year, month, day) = when (parts.size) { 3 -> Triple(parts[0], parts[1], parts[2]); 2 -> Triple(today.year, parts[0], parts[1]); else -> return null }
    return runCatching { LocalDate.of(if (year < 100) 2000 + year else year, month, day).toString() }.getOrNull()
}

@Composable fun TripsScreen(api: TravelService, startCreating: Boolean, back: () -> Unit, open: (String) -> Unit) {
    var trips by remember { mutableStateOf<List<JsonObject>?>(null) }
    var invites by remember { mutableStateOf<List<JsonObject>>(emptyList()) }
    var error by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    var creating by rememberSaveable { mutableStateOf(startCreating) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(reload, lifecycle) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            call({ error = it }) { api.request("GET", "trips").array().map { it.obj() } }?.let { trips = it }
            call({}) { api.request("GET", "trips/invites/pending").array().map { it.obj() } }?.let { invites = it }
        }
    }
    SubPage("全部行程", back, actions = { IconButton({ creating = true }) { Icon(Icons.Outlined.Add, "新建行程") } }) {
        error?.let { item { ErrorNotice(it) { reload++ } } }
        if (trips == null && error == null) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
        items(invites, key = { "invite-" + it["trip_id"].string() }) { invite ->
            GlassCard(Modifier.fillMaxWidth()) {
                Text(invite["title"].string(), style = MaterialTheme.typography.titleMedium)
                Text("${invite["inviter"].string()} 邀请你一起规划", style = MaterialTheme.typography.bodyMedium)
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    fun respond(accept: Boolean) { if (busy) return; busy = true; scope.launch {
                        val done = call({ error = it }) { api.request("POST", "trips/${invite["trip_id"].string()}/invites/respond", jsonBody("accept" to accept)) }
                        busy = false; reload++; if (done != null && accept) open(invite["trip_id"].string())
                    } }
                    Button({ respond(true) }, enabled = !busy) { Text("接受") }
                    OutlinedButton({ respond(false) }, enabled = !busy) { Text("拒绝") }
                }
            }
        }
        if (trips?.isEmpty() == true) item { Text("还没有行程。点右上角新建一个，或者让 AI 帮你规划后转成行程。", color = MaterialTheme.colorScheme.onSurfaceVariant) }
        items(trips.orEmpty(), key = { it["id"].string() }) { trip ->
            Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(20.dp)).background(MaterialTheme.colorScheme.surface.copy(alpha = .92f))
                .border(1.dp, MaterialTheme.colorScheme.outlineVariant, RoundedCornerShape(20.dp)).clickable { open(trip["id"].string()) }.padding(16.dp),
                verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                Column(Modifier.size(48.dp).clip(RoundedCornerShape(14.dp)).background(MaterialTheme.colorScheme.primaryContainer), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
                    Text(trip["days"].int().toString(), style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.onPrimaryContainer)
                    Text("天", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onPrimaryContainer)
                }
                Column(Modifier.weight(1f)) {
                    Text(trip["title"].string(), style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(listOf(trip["destination"].string().ifBlank { "目的地待定" }, if (trip["role"].string() == "owner") "我的行程" else "一起规划").joinToString(" · "),
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                }
                Text("›", color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.titleLarge)
            }
        }
    }
    if (creating) {
        var title by rememberSaveable { mutableStateOf("") }
        var date by rememberSaveable { mutableStateOf("") }
        var note by remember { mutableStateOf<String?>(null) }
        SheetDialog(onDismissRequest = { if (!busy) creating = false }, title = { Text("新建旅行") }, text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedTextField(title, { title = it }, Modifier.fillMaxWidth(), label = { Text("给这次旅行起个名字") }, placeholder = { Text("比如：杭州的慢周末") }, singleLine = true, enabled = !busy)
                OutlinedTextField(date, { date = it }, Modifier.fillMaxWidth(), label = { Text("出发日期（可不填）") }, placeholder = { Text("如 11.20 或 2026-11-20") }, singleLine = true, enabled = !busy)
                Text("填了日期，出行当天首页会直接显示今天的安排。", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                (note ?: error)?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) }
            }
        }, confirmButton = { TextButton({
            val parsed = if (date.isBlank()) "" else parseTripDate(date)
            if (parsed == null) { note = "日期没看懂，试试 11.20 这样的写法"; return@TextButton }
            busy = true; note = null
            scope.launch {
                val id = call({ error = it }) { api.request("POST", "trips", jsonBody("title" to title.trim(), "days" to 2, "start_date" to parsed)).obj()["id"].string() }
                busy = false
                if (!id.isNullOrEmpty()) { creating = false; reload++; open(id) }
            }
        }, enabled = !busy && title.isNotBlank()) { Text(if (busy) "正在创建…" else "创建") } },
            dismissButton = { TextButton({ creating = false }, enabled = !busy) { Text("取消") } })
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun TripDetailScreen(api: TravelService, id: String, username: String, back: () -> Unit, external: (String) -> Unit, notification: TripNotification? = null, openLedger: () -> Unit) {
    var trip by remember { mutableStateOf<JsonObject?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    var day by rememberSaveable { mutableIntStateOf(1) }
    var editing by remember { mutableStateOf<JsonObject?>(null) }
    var adding by rememberSaveable { mutableStateOf(false) }
    var sheet by rememberSaveable { mutableStateOf("") }          // members / polls / chat / settings
    var menu by remember { mutableStateOf(false) }
    var removing by rememberSaveable { mutableStateOf(false) }
    var askedDate by rememberSaveable { mutableStateOf(false) }
    var polls by remember { mutableStateOf<List<JsonObject>>(emptyList()) }
    var notificationConsumed by rememberSaveable { mutableStateOf(false) }
    var focusPoll by rememberSaveable { mutableStateOf<String?>(null) }
    var notificationScrolled by rememberSaveable { mutableStateOf(false) }
    val listState = rememberLazyListState()
    var pollBusy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(reload, lifecycle) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            // 同伴的改动 5 秒内能看到；有弹窗开着时不刷新，免得打断输入
            while (isActive) {
                if (trip == null || (sheet.isEmpty() && !adding && editing == null)) {
                    call({ error = it }) { api.request("GET", "trips/$id").obj() }?.let { trip = it }
                    call({}) { api.request("GET", "trips/$id/polls").array().map { it.obj() } }?.let { polls = it }
                    if (!notificationConsumed && notification != null && trip != null) {
                        val resolved = notification.resolve(trip?.get("days").int().coerceAtLeast(1), polls, day)
                        day = resolved.first; focusPoll = resolved.second
                        askedDate = true
                        notificationConsumed = true
                    }
                }
                delay(5000)
            }
        }
    }
    val current = trip
    val owner = current?.get("members").array().any { it.obj()["username"].string() == username && it.obj()["role"].string() == "owner" }
    val days = (current?.get("days").int()).coerceAtLeast(1)
    LaunchedEffect(days) { if (current != null && day > days) day = 1 }
    LaunchedEffect(focusPoll, day) {
        if (!notificationScrolled && focusPoll != null && current != null) {
            val index = notificationPollIndex(polls, day, focusPoll!!, error != null,
                current["start_date"].string().isBlank() && !askedDate,
                (current["day_titles"] as? JsonObject)?.get(day.toString()).string().isNotBlank())
            if (index != null) { listState.scrollToItem(index); notificationScrolled = true }
        }
    }
    Scaffold(containerColor = Color.Transparent, contentWindowInsets = WindowInsets(0), topBar = {
        CenterAlignedTopAppBar(title = { Text(current?.get("title").string().ifBlank { "行程" }, maxLines = 1, overflow = TextOverflow.Ellipsis) },
            navigationIcon = { IconButton(back) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "返回") } },
            colors = TopAppBarDefaults.centerAlignedTopAppBarColors(containerColor = Color.Transparent), windowInsets = WindowInsets(0),
            actions = {
                IconButton({ sheet = "chat" }) { Icon(Icons.Outlined.Forum, "行程群聊") }
                Box {
                    IconButton({ menu = true }) { Icon(Icons.Outlined.MoreVert, "更多") }
                    DropdownMenu(menu, { menu = false }) {
                        DropdownMenuItem({ Text("让 AI 改行程") }, { menu = false; sheet = "copilot" })
                        DropdownMenuItem({ Text("调整当天顺序") }, { menu = false; sheet = "reorder" })
                        HorizontalDivider()
                        DropdownMenuItem({ Text("美食") }, { menu = false; sheet = "foods" })
                        DropdownMenuItem({ Text("行李清单") }, { menu = false; sheet = "packing" })
                        DropdownMenuItem({ Text("避坑提醒") }, { menu = false; sheet = "tips" })
                        HorizontalDivider()
                        DropdownMenuItem({ Text("成员与邀请") }, { menu = false; sheet = "members" })
                        DropdownMenuItem({ Text("旅行账本") }, { menu = false; openLedger() })
                        DropdownMenuItem({ Text("行程设置") }, { menu = false; sheet = "settings" })
                        DropdownMenuItem({ Text(if (owner) "删除行程" else "退出行程", color = MaterialTheme.colorScheme.error) }, { menu = false; removing = true })
                    }
                }
            })
    }, floatingActionButton = {
        if (current != null) ExtendedFloatingActionButton(shape = androidx.compose.foundation.shape.CircleShape, elevation = FloatingActionButtonDefaults.elevation(2.dp, 2.dp, 2.dp, 2.dp), onClick = { adding = true }, containerColor = MaterialTheme.colorScheme.primary, contentColor = MaterialTheme.colorScheme.onPrimary,
            icon = { Icon(Icons.Outlined.Add, null) }, text = { Text("加地点") })
    }) { padding ->
        LazyColumn(Modifier.padding(padding), state = listState, contentPadding = PaddingValues(start = 20.dp, top = 4.dp, end = 20.dp, bottom = 96.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            error?.let { item { ErrorNotice(it) { reload++ } } }
            if (current == null) { if (error == null) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }; return@LazyColumn }
            val startDate = current["start_date"].string()
            item {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(listOf(current["destination"].string(), "$days 天", startDate.ifBlank { null }?.let { "$it 出发" }).filterNotNull().filter(String::isNotBlank).joinToString(" · "),
                        Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    TextButton({ sheet = "members" }) { Text("${current["members"].array().size} 人同行") }
                }
            }
            if (startDate.isBlank() && !askedDate) item {
                GlassCard(Modifier.fillMaxWidth()) {
                    Text("哪天出发？", style = MaterialTheme.typography.titleMedium)
                    Text("定了日期，出行当天首页会直接显示今天的安排。", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        Button({ sheet = "settings" }) { Text("设置日期") }
                        TextButton({ askedDate = true }) { Text("还没定") }
                    }
                }
            }
            // 等我投票的：没结束、我还没投。每天的标签上带个点，顶部一句话提示，点了直接跳到那天。
            val waiting = polls.filter { !it["closed"].bool() && it["my_vote"] is JsonNull }
            val waitingDays = waiting.mapNotNull { (it["day"] as? JsonPrimitive)?.intOrNull }.toSet()
            if (waiting.isNotEmpty()) item {
                Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(MaterialTheme.colorScheme.primaryContainer)
                    .clickable { waitingDays.minOrNull()?.let { day = it } }.padding(horizontal = 14.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Outlined.HowToVote, null, Modifier.size(18.dp), tint = MaterialTheme.colorScheme.onPrimaryContainer); Spacer(Modifier.width(8.dp))
                    Text("有 ${waiting.size} 个投票等你选" + (waitingDays.sorted().takeIf { it.isNotEmpty() }?.joinToString("、", prefix = "（第 ", postfix = " 天）") ?: ""),
                        Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onPrimaryContainer)
                    if (waitingDays.isNotEmpty()) Text("去投票", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
                }
            }
            // 关于整趟行程的投票（不属于某一天），每天都看得到
            polls.filter { it["day"] is JsonNull || it["day"] == null }.forEach { poll ->
                item(key = "poll-" + poll["id"].string()) { PollCard(api, id, poll, pollBusy, { pollBusy = it }, focused = poll["id"].string() == focusPoll) { updated -> polls = polls.map { if (it["id"] == updated["id"]) updated else it } ; if (updated.isEmpty()) reload++ } }
            }
            item {
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    (1..days).forEach { n ->
                        val label = startDate.takeIf { it.isNotBlank() }?.let { runCatching { LocalDate.parse(it).plusDays(n - 1L) }.getOrNull() }?.let { "${it.monthValue}/${it.dayOfMonth}" }
                        FilterChip(day == n, { day = n }, { Text("第 $n 天" + (label?.let { " · $it" } ?: "")) },
                            trailingIcon = if (n in waitingDays) { { Box(Modifier.size(7.dp).clip(CircleShape).background(MaterialTheme.colorScheme.error)) } } else null)
                    }
                }
            }
            val title = (current["day_titles"] as? JsonObject)?.get(day.toString()).string()
            if (title.isNotBlank()) item { Text(title, style = MaterialTheme.typography.titleMedium) }
            val stops = current["stops"].array().map { it.obj() }.filter { it["day"].int() == day }
            if (stops.isNotEmpty()) item { DayMap(stops) }
            if (stops.isEmpty()) item { Text("这一天还没有安排。点右下角「加地点」开始。", color = MaterialTheme.colorScheme.onSurfaceVariant) }
            // 这一天的投票紧跟在当天安排上面：住哪家、去哪个景点，在要决定的那天里决定
            polls.filter { (it["day"] as? JsonPrimitive)?.intOrNull == day }.forEach { poll ->
                item(key = "poll-" + poll["id"].string()) { PollCard(api, id, poll, pollBusy, { pollBusy = it }, focused = poll["id"].string() == focusPoll) { updated -> polls = polls.map { if (it["id"] == updated["id"]) updated else it }; if (updated.isEmpty()) reload++ } }
            }
            itemsIndexed(stops, key = { _, stop -> stop["id"].string() }) { index, stop ->
                Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(20.dp)).background(MaterialTheme.colorScheme.surface.copy(alpha = .92f))
                    .border(1.dp, MaterialTheme.colorScheme.outlineVariant, RoundedCornerShape(20.dp)).clickable { editing = stop }.padding(start = 14.dp, top = 12.dp, bottom = 12.dp, end = 6.dp),
                    verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Box(Modifier.size(28.dp).clip(CircleShape).background(MaterialTheme.colorScheme.primary), contentAlignment = Alignment.Center) {
                        Text("${index + 1}", color = MaterialTheme.colorScheme.onPrimary, style = MaterialTheme.typography.labelLarge)
                    }
                    Column(Modifier.weight(1f)) {
                        Text(stop["name"].string(), style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.Medium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        val meta = listOf(stop["start_time"].string(), stop["stay_min"].int().takeIf { it > 0 }?.let { "停留 $it 分钟" }.orEmpty(), stop["note"].string()).filter(String::isNotBlank).joinToString(" · ")
                        if (meta.isNotBlank()) Text(meta, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    }
                    val nav = stop["nav"] as? JsonObject
                    val url = if (nav?.get("domestic").bool()) nav?.get("amap").string() else nav?.get("google").string().ifBlank { nav?.get("apple").string() }
                    if (url.isNotBlank()) TextButton({ external(url) }) { Text("导航") }
                }
            }
            item { TextButton({ sheet = "newPoll" }, contentPadding = PaddingValues(0.dp)) { Icon(Icons.Outlined.HowToVote, null, Modifier.size(16.dp)); Spacer(Modifier.width(4.dp)); Text("第 $day 天有拿不准的？发起投票") } }
        }
    }
    if ((adding || editing != null) && current != null) StopDialog(api, id, editing, day, days, { adding = false; editing = null }) { adding = false; editing = null; reload++ }
    if (removing) AlertDialog(onDismissRequest = { removing = false }, title = { Text(if (owner) "删除这份行程？" else "退出这份行程？") },
        text = { Text(if (owner) "行程会对所有成员删除，无法恢复。" else "退出不影响其他成员。") },
        confirmButton = { TextButton({ removing = false; scope.launch {
            if (call({ error = it }) { api.request(if (owner) "DELETE" else "POST", "trips/$id" + if (owner) "" else "/leave") } != null) back()
        } }) { Text(if (owner) "删除行程" else "退出行程", color = MaterialTheme.colorScheme.error) } },
        dismissButton = { TextButton({ removing = false }) { Text("取消") } })
    if (current != null) when (sheet) {
        "settings" -> TripSettingsDialog(api, current, { sheet = "" }) { sheet = ""; askedDate = true; reload++ }
        "members" -> TripMembersDialog(api, current, context) { sheet = "" }
        "newPoll" -> NewPollSheet(api, id, day, days, { sheet = "" }) { created -> sheet = ""; polls = listOf(created) + polls }
        "chat" -> TripChatDialog(api, id) { sheet = "" }
        "copilot" -> CopilotSheet(api, id, { sheet = ""; reload++ }) { reload++ }
        "reorder" -> ReorderSheet(api, id, day, current["stops"].array().map { it.obj() }.filter { it["day"].int() == day }, { sheet = "" }) { sheet = ""; reload++ }
        "foods" -> FoodsSheet(api, id) { sheet = "" }
        "packing" -> PackingSheet(api, id, username) { sheet = "" }
        "tips" -> TipsSheet(api, id) { sheet = "" }
    }
}

@Composable private fun StopDialog(api: TravelService, tripId: String, stop: JsonObject?, defaultDay: Int, days: Int, dismiss: () -> Unit, saved: () -> Unit) {
    var name by rememberSaveable { mutableStateOf(stop?.get("name").string()) }
    var note by rememberSaveable { mutableStateOf(stop?.get("note").string()) }
    var time by rememberSaveable { mutableStateOf(stop?.get("start_time").string()) }
    var day by rememberSaveable { mutableIntStateOf(stop?.get("day").int().takeIf { it > 0 } ?: defaultDay) }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    SheetDialog(onDismissRequest = { if (!busy) dismiss() }, title = { Text(if (stop == null) "加一个地点" else "修改地点") }, text = {
        Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedTextField(name, { name = it }, Modifier.fillMaxWidth(), label = { Text("地点名称") }, singleLine = true, enabled = !busy)
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                (1..days).forEach { n -> FilterChip(day == n, { day = n }, { Text("第 $n 天") }, enabled = !busy) }
            }
            OutlinedTextField(time, { time = it.take(5) }, Modifier.fillMaxWidth(), label = { Text("到达时间（可不填，如 09:30）") }, singleLine = true, enabled = !busy)
            OutlinedTextField(note, { note = it }, Modifier.fillMaxWidth(), label = { Text("备注（可不填）") }, maxLines = 3, enabled = !busy)
            error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
            if (stop != null) TextButton({ busy = true; scope.launch {
                val done = call({ error = it }) { api.request("DELETE", "trips/$tripId/stops/${stop["id"].string()}") }; busy = false; if (done != null) saved()
            } }, enabled = !busy, contentPadding = PaddingValues(0.dp)) { Text("删除这个地点", color = MaterialTheme.colorScheme.error) }
        }
    }, confirmButton = { TextButton({
        if (time.isNotBlank() && !Regex("^([01]?\\d|2[0-3]):[0-5]\\d$").matches(time.trim())) { error = "时间写成 09:30 这样"; return@TextButton }
        busy = true
        scope.launch {
            val body = jsonBody("name" to name.trim(), "note" to note.trim(), "day" to day, "start_time" to time.trim())
            val done = call({ error = it }) { api.request(if (stop == null) "POST" else "PATCH", "trips/$tripId/stops" + (stop?.let { "/${it["id"].string()}" } ?: ""), body) }
            busy = false; if (done != null) saved()
        }
    }, enabled = !busy && name.isNotBlank()) { Text(if (busy) "正在保存…" else "保存") } },
        dismissButton = { TextButton(dismiss, enabled = !busy) { Text("取消") } })
}

@Composable private fun TripSettingsDialog(api: TravelService, trip: JsonObject, dismiss: () -> Unit, saved: () -> Unit) {
    var title by rememberSaveable { mutableStateOf(trip["title"].string()) }
    var destination by rememberSaveable { mutableStateOf(trip["destination"].string()) }
    var days by rememberSaveable { mutableStateOf(trip["days"].int().toString()) }
    var date by rememberSaveable { mutableStateOf(trip["start_date"].string()) }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    SheetDialog(onDismissRequest = { if (!busy) dismiss() }, title = { Text("行程设置") }, text = {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedTextField(title, { title = it }, Modifier.fillMaxWidth(), label = { Text("名称") }, singleLine = true, enabled = !busy)
            OutlinedTextField(destination, { destination = it }, Modifier.fillMaxWidth(), label = { Text("目的地") }, singleLine = true, enabled = !busy)
            OutlinedTextField(days, { days = it.filter(Char::isDigit).take(2) }, Modifier.fillMaxWidth(), label = { Text("天数") }, singleLine = true, enabled = !busy)
            OutlinedTextField(date, { date = it }, Modifier.fillMaxWidth(), label = { Text("出发日期（留空表示还没定）") }, placeholder = { Text("如 11.20 或 2026-11-20") }, singleLine = true, enabled = !busy)
            error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
        }
    }, confirmButton = { TextButton({
        val parsed = if (date.isBlank()) "" else parseTripDate(date)
        if (parsed == null) { error = "日期没看懂，试试 11.20 这样的写法"; return@TextButton }
        busy = true
        scope.launch {
            val done = call({ error = it }) { api.request("PATCH", "trips/${trip["id"].string()}", jsonBody("title" to title.trim(), "destination" to destination.trim(),
                "days" to (days.toIntOrNull() ?: trip["days"].int()).coerceAtLeast(1), "start_date" to parsed)) }
            busy = false; if (done != null) saved()
        }
    }, enabled = !busy && title.isNotBlank()) { Text(if (busy) "正在保存…" else "保存") } },
        dismissButton = { TextButton(dismiss, enabled = !busy) { Text("取消") } })
}

@Composable private fun TripMembersDialog(api: TravelService, trip: JsonObject, context: android.content.Context, dismiss: () -> Unit) {
    var name by rememberSaveable { mutableStateOf("") }
    var message by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val id = trip["id"].string()
    SheetDialog(onDismissRequest = dismiss, title = { Text("成员与邀请") }, text = {
        Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            trip["members"].array().forEach { item -> val member = item.obj()
                Row { Text("@" + member["username"].string(), Modifier.weight(1f))
                    Text(if (member["role"].string() == "owner") "创建者" else "同行", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
            }
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(name, { name = it }, Modifier.weight(1f), label = { Text("对方的用户名") }, singleLine = true, enabled = !busy)
                TextButton({ busy = true; scope.launch {
                    if (call({ message = it }) { api.request("POST", "trips/$id/invite", jsonBody("username" to name.trim())) } != null) { message = "邀请已发出，等对方接受。"; name = "" }
                    busy = false
                } }, enabled = !busy && name.isNotBlank()) { Text("邀请") }
            }
            TextButton({ busy = true; scope.launch {
                call({ message = it }) { api.request("POST", "trips/$id/share", jsonBody("reset" to false)).obj()["short_code"].string() }?.takeIf { it.isNotEmpty() }?.let { code ->
                    val url = "https://17tongyou.com/t/$code"
                    context.getSystemService(ClipboardManager::class.java).setPrimaryClip(ClipData.newPlainText("行程邀请", url))
                    Toast.makeText(context, "邀请链接已复制", Toast.LENGTH_SHORT).show()
                    runCatching { context.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, "一起规划「${trip["title"].string()}」：$url"), "分享行程")) }
                }
                busy = false
            } }, enabled = !busy, contentPadding = PaddingValues(0.dp)) { Text("复制邀请链接并分享") }
            Text("持有链接的人可以加入并编辑行程，请只发给同行的人。", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            message?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
        }
    }, confirmButton = { TextButton(dismiss) { Text("完成") } })
}

/** 一个投票：直接在行程里点选项投票，每人一票可以改；发起人可以结束或删除。update(空对象) 表示已删除。 */
@Composable private fun PollCard(api: TravelService, tripId: String, poll: JsonObject, busy: Boolean, setBusy: (Boolean) -> Unit, focused: Boolean = false, update: (JsonObject) -> Unit) {
    val scope = rememberCoroutineScope()
    var error by remember { mutableStateOf<String?>(null) }
    val pid = poll["id"].string(); val closed = poll["closed"].bool(); val total = poll["total"].int()
    val myVote = (poll["my_vote"] as? JsonPrimitive)?.intOrNull
    fun act(method: String, path: String, body: JsonObject? = null) { setBusy(true); scope.launch {
        call({ error = it }) { api.request(method, "trips/$tripId/polls/$pid$path", body).obj() }?.let { update(if (method == "DELETE") JsonObject(emptyMap()) else it) }
        setBusy(false)
    } }
    GlassCard(Modifier.fillMaxWidth().then(if (focused) Modifier.border(2.dp, MaterialTheme.colorScheme.primary, RoundedCornerShape(20.dp)) else Modifier)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Icon(Icons.Outlined.HowToVote, null, Modifier.size(18.dp), tint = MaterialTheme.colorScheme.primary)
            Text(poll["question"].string(), Modifier.weight(1f), style = MaterialTheme.typography.titleMedium)
            if (!closed && myVote == null) Text("等你投票", Modifier.clip(CircleShape).background(MaterialTheme.colorScheme.errorContainer).padding(horizontal = 8.dp, vertical = 2.dp),
                style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onErrorContainer)
        }
        Text((if (closed) "已结束" else "$total/${poll["members"].int()} 人已投 · 每人一票，可以改") + poll["created_by"].string().let { if (it.isBlank()) "" else " · $it 发起" },
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        val top = poll["options"].array().maxOfOrNull { it.obj()["votes"].int() } ?: 0
        poll["options"].array().forEachIndexed { index, item -> val option = item.obj()
            val mine = myVote == index
            val share = if (total > 0) option["votes"].int() / total.toFloat() else 0f
            Box(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).border(1.dp, if (mine) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outlineVariant, RoundedCornerShape(12.dp))
                .clickable(enabled = !closed && !busy && !mine) { act("POST", "/vote", jsonBody("option" to index)) }) {
                Box(Modifier.matchParentSize().fillMaxWidth(share).background(MaterialTheme.colorScheme.primary.copy(alpha = .12f)))
                Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text((if (mine) "✓ " else "") + option["text"].string(), Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium,
                        fontWeight = if (closed && option["votes"].int() == top && top > 0) FontWeight.SemiBold else FontWeight.Normal)
                    Text("${option["votes"].int()} 票" + option["voters"].array().map { it.string() }.takeIf { it.isNotEmpty() }?.joinToString("、", prefix = " · ").orEmpty(),
                        style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
        }
        if (poll["mine"].bool()) Row {
            if (!closed) TextButton({ act("POST", "/close") }, enabled = !busy, contentPadding = PaddingValues(horizontal = 0.dp)) { Text("结束投票") }
            Spacer(Modifier.width(12.dp))
            TextButton({ act("DELETE", "") }, enabled = !busy, contentPadding = PaddingValues(horizontal = 0.dp)) { Text("删除", color = MaterialTheme.colorScheme.error) }
        }
        error?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) }
    }
}

/** 发起投票：默认归到当前这一天，也可以选「整趟行程」。 */
@Composable private fun NewPollSheet(api: TravelService, tripId: String, defaultDay: Int, days: Int, dismiss: () -> Unit, created: (JsonObject) -> Unit) {
    var question by rememberSaveable { mutableStateOf("") }
    var options by rememberSaveable { mutableStateOf(listOf("", "")) }
    var day by rememberSaveable { mutableIntStateOf(defaultDay) }          // 0 = 整趟行程
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val filled = options.map(String::trim).filter(String::isNotEmpty)
    SheetDialog(onDismissRequest = { if (!busy) dismiss() }, title = { Text("发起投票") },
        dismissButton = { TextButton(dismiss, enabled = !busy) { Text("取消") } },
        confirmButton = { TextButton({ busy = true; scope.launch {
            call({ error = it }) { api.request("POST", "trips/$tripId/polls", jsonBody("question" to question.trim(), "options" to JsonArray(filled.map(::JsonPrimitive)),
                "day" to day.takeIf { it > 0 })).obj() }?.let(created)
            busy = false
        } }, enabled = !busy && question.isNotBlank() && filled.size >= 2) { Text("发起") } },
        text = { Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                (1..days).forEach { n -> FilterChip(day == n, { day = n }, { Text("第 $n 天") }) }
                FilterChip(day == 0, { day = 0 }, { Text("整趟行程") })
            }
            OutlinedTextField(question, { question = it.take(120) }, Modifier.fillMaxWidth(), label = { Text("要大家决定什么") }, placeholder = { Text("如「晚上住哪家」") }, singleLine = true, enabled = !busy)
            options.forEachIndexed { index, value ->
                OutlinedTextField(value, { text -> options = options.toMutableList().also { it[index] = text.take(60) } }, Modifier.fillMaxWidth(), label = { Text("选项 ${index + 1}") }, singleLine = true, enabled = !busy)
            }
            if (options.size < 4) TextButton({ options = options + "" }, contentPadding = PaddingValues(0.dp)) { Text("＋ 再加一个选项") }
            Text("发起后同行的人会收到通知，在这一天的行程里直接点选。", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            error?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) }
        } })
}

/** 行程群聊：打开时每 3 秒取新消息。 */
@Composable private fun TripChatDialog(api: TravelService, tripId: String, dismiss: () -> Unit) {
    var messages by remember { mutableStateOf<List<JsonObject>>(emptyList()) }
    var draft by rememberSaveable { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val list = rememberLazyListState()
    LaunchedEffect(Unit) {
        call({}) { api.request("POST", "trips/$tripId/chat/read") }
        while (isActive) {
            val after = messages.lastOrNull()?.get("id").string()
            call({ error = it }) { api.request("GET", "trips/$tripId/chat", query = if (after.isBlank()) emptyList() else listOf("after" to after)).array().map { it.obj() } }
                ?.let { fresh -> if (fresh.isNotEmpty()) messages = (messages + fresh).distinctBy { it["id"].string() } }
            delay(3000)
        }
    }
    LaunchedEffect(messages.size) { if (messages.isNotEmpty()) list.scrollToItem(messages.size - 1) }
    SheetDialog(onDismissRequest = dismiss, title = { Text("行程群聊") }, text = {
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            LazyColumn(Modifier.fillMaxWidth().heightIn(min = 240.dp, max = 520.dp), state = list, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (messages.isEmpty()) item { Text("还没有人说话。商量行程、约时间都可以发在这里。", color = MaterialTheme.colorScheme.onSurfaceVariant) }
                items(messages, key = { it["id"].string() }) { message ->
                    val mine = message["mine"].bool()
                    Column(Modifier.fillMaxWidth(), horizontalAlignment = if (mine) Alignment.End else Alignment.Start) {
                        if (!mine) Text(message["username"].string(), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Text(message["content"].string(), Modifier.clip(RoundedCornerShape(16.dp))
                            .background(if (mine) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surfaceVariant).padding(horizontal = 12.dp, vertical = 8.dp),
                            color = if (mine) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurface)
                    }
                }
            }
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(draft, { draft = it.take(1000) }, Modifier.weight(1f), placeholder = { Text("说点什么…") }, maxLines = 3, shape = RoundedCornerShape(20.dp))
                FilledIconButton({ busy = true; val text = draft.trim(); scope.launch {
                    call({ error = it }) { api.request("POST", "trips/$tripId/chat", jsonBody("content" to text)).obj() }?.let { sent ->
                        draft = ""; if (sent["id"].string().isNotEmpty()) messages = (messages + sent).distinctBy { it["id"].string() }
                    }
                    busy = false
                } }, enabled = !busy && draft.isNotBlank()) { Icon(Icons.AutoMirrored.Outlined.Send, "发送") }
            }
            error?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) }
        }
    }, confirmButton = { TextButton(dismiss) { Text("关闭") } })
}
