package com.tongyou.travel.ui

import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.tongyou.travel.chat.Markdown
import com.tongyou.travel.data.*
import kotlinx.coroutines.*
import kotlinx.serialization.json.*

private suspend fun <T> call(error: (String?) -> Unit, block: suspend () -> T): T? = try {
    withContext(Dispatchers.IO) { block() }.also { error(null) }
} catch (e: CancellationException) { throw e } catch (e: Exception) { error(e.message ?: "操作失败，请重试"); null }

@Composable private fun Note(text: String) = Text(text, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)

/** The day's route as a static map (signed server-side; no map key in the app). Hidden when no stop has coordinates. */
@Composable fun DayMap(stops: List<JsonObject>) {
    val points = stops.mapIndexedNotNull { i, s -> s["location"].string().takeIf { Regex("^-?\\d+(\\.\\d+)?,-?\\d+(\\.\\d+)?$").matches(it) }?.let { it to (i + 1) } }
    if (points.isEmpty()) return
    val url = "/api/staticmap?pts=" + points.joinToString(";") { it.first } + "&labels=" + points.joinToString(",") { it.second.toString() } + "&size=750*450"
    AsyncImage(TravelApi.media(url), "当天路线地图", Modifier.fillMaxWidth().aspectRatio(750f / 450f).clip(RoundedCornerShape(20.dp))
        .background(MaterialTheme.colorScheme.surfaceVariant), contentScale = ContentScale.Crop)
}

/** 让 AI 改行程：说一句，AI 给出改动清单，采纳后才生效，可撤销。 */
@Composable fun CopilotSheet(api: TravelService, tripId: String, dismiss: () -> Unit, changed: () -> Unit) {
    var rows by remember { mutableStateOf<List<JsonObject>>(emptyList()) }
    var prompt by rememberSaveable { mutableStateOf("") }
    var working by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    suspend fun load() { call({}) { api.request("GET", "trips/$tripId/suggestions").array().map { it.obj() } }?.let { rows = it } }
    LaunchedEffect(Unit) { load() }
    // AI 在后台处理：等到最新一条出结果为止
    LaunchedEffect(working) { while (working && isActive) { delay(2500); load(); val trip = call({}) { api.request("GET", "trips/$tripId").obj() }
        if (trip != null && trip["ai_status"].string() != "copilot") { working = false; load() } } }
    SheetDialog(onDismissRequest = dismiss, title = { Text("让 AI 改行程") }, confirmButton = { TextButton(dismiss) { Text("完成") } }, text = {
        Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(prompt, { prompt = it.take(500) }, Modifier.weight(1f), placeholder = { Text("想怎么改？如「Day2 少走路」") }, maxLines = 4, shape = RoundedCornerShape(22.dp), enabled = !working)
                FilledIconButton({ val text = prompt.trim(); working = true; error = null; scope.launch {
                    if (call({ error = it }) { api.request("POST", "trips/$tripId/ai/copilot", jsonBody("prompt" to text)) } == null) working = false else prompt = ""
                } }, enabled = !working && prompt.isNotBlank(), modifier = Modifier.size(48.dp)) { Icon(Icons.Outlined.ArrowUpward, "发送") }
            }
            if (working) Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) { CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp); Note("AI 正在看行程，稍等片刻…") }
            error?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) }
            if (rows.isEmpty() && !working) Note("例如「Day2 少走路」「预算降到 3000」「加一个亲子景点」。改动会先给你确认。")
            rows.forEach { s ->
                GlassCard(Modifier.fillMaxWidth()) {
                    Text(s["prompt"].string(), style = MaterialTheme.typography.titleMedium)
                    s["reply"].string().takeIf { it.isNotBlank() }?.let { Markdown(it) }
                    s["changes"].array().forEach { item -> val c = item.obj()
                        val op = c["op"].string()
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Icon(when (op) { "add" -> Icons.Outlined.AddCircle; "delete" -> Icons.Outlined.RemoveCircle; else -> Icons.Outlined.Edit }, null, Modifier.size(18.dp),
                                tint = when (op) { "add" -> Color(0xFF16A34A); "delete" -> MaterialTheme.colorScheme.error; else -> MaterialTheme.colorScheme.primary })
                            Column {
                                Text(listOf(c["day"].int().takeIf { it > 0 }?.let { "Day $it" }, c["start_time"].string().ifBlank { null }, c["name"].string().ifBlank { null }).filterNotNull().joinToString(" · "),
                                    style = MaterialTheme.typography.bodyMedium)
                                c["reason"].string().takeIf { it.isNotBlank() }?.let { Note(it) }
                            }
                        }
                    }
                    fun act(action: String) { scope.launch { call({ error = it }) { api.request("POST", "trips/$tripId/suggestions/${s["id"].string()}/$action") }; load(); changed() } }
                    when (s["status"].string()) {
                        "pending" -> Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) { Button({ act("apply") }) { Text("采纳改动") }; OutlinedButton({ act("reject") }) { Text("不要") } }
                        "applied" -> Row(verticalAlignment = Alignment.CenterVertically) { Text("已采纳", Modifier.weight(1f), color = Color(0xFF16A34A), style = MaterialTheme.typography.labelLarge); TextButton({ act("revert") }) { Text("撤销") } }
                        "rejected" -> Note("已忽略")
                        "reverted" -> Note("已撤销")
                    }
                }
            }
        }
    })
}

/** 美食：想吃的店、哪顿、打卡。 */
@Composable fun FoodsSheet(api: TravelService, tripId: String, dismiss: () -> Unit) {
    var rows by remember { mutableStateOf<List<JsonObject>?>(null) }
    var name by rememberSaveable { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(reload) { call({ error = it }) { api.request("GET", "trips/$tripId/foods").array().map { it.obj() } }?.let { rows = it } }
    fun act(block: suspend () -> Unit) { scope.launch { call({ error = it }) { block() }; reload++ } }
    SheetDialog(onDismissRequest = dismiss, title = { Text("美食") }, confirmButton = { TextButton(dismiss) { Text("完成") } }, text = {
        Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(name, { name = it.take(80) }, Modifier.weight(1f), placeholder = { Text("想吃的店，如「第一楼灌汤包」") }, singleLine = true, shape = RoundedCornerShape(22.dp))
                Button({ val n = name.trim(); act { api.request("POST", "trips/$tripId/foods", jsonBody("name" to n)); name = "" } }, enabled = name.isNotBlank()) { Text("添加") }
            }
            error?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) }
            if (rows?.isEmpty() == true) Note("还没有美食。想吃的店记在这里，同行的人都能看到。")
            rows.orEmpty().forEach { f ->
                Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(MaterialTheme.colorScheme.surface).padding(start = 12.dp, top = 8.dp, bottom = 8.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text((if (f["is_top"].bool()) "📌 " else "") + f["name"].string(), style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Note(listOfNotNull(f["day"].int().takeIf { it > 0 }?.let { "第 $it 天" }, f["meal_type"].string().takeIf { it != "待定" }, f["category"].string(),
                            f["created_by"].string().ifBlank { null }).joinToString(" · "))
                    }
                    IconButton({ act { api.request("PATCH", "trips/$tripId/foods/${f["id"].string()}", JsonObject(f.filterKeys { it != "id" && it != "created_by" } + ("checked_in" to JsonPrimitive(!f["checked_in"].bool())) + ("status" to JsonPrimitive(if (f["checked_in"].bool()) "planned" else "checked_in")))) } }) {
                        Icon(if (f["checked_in"].bool()) Icons.Outlined.CheckCircle else Icons.Outlined.RadioButtonUnchecked, if (f["checked_in"].bool()) "取消打卡" else "打卡",
                            tint = if (f["checked_in"].bool()) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    IconButton({ act { api.request("DELETE", "trips/$tripId/foods/${f["id"].string()}") } }) { Icon(Icons.Outlined.Close, "删除", tint = MaterialTheme.colorScheme.onSurfaceVariant) }
                }
            }
        }
    })
}

/** 行李：每人一列，三态（带了 / 没带 / 不需要），可以替同伴勾。 */
@Composable fun PackingSheet(api: TravelService, tripId: String, me: String, dismiss: () -> Unit) {
    var data by remember { mutableStateOf<JsonObject?>(null) }
    var name by rememberSaveable { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(reload) { call({ error = it }) { api.request("GET", "trips/$tripId/packing").obj() }?.let { data = it } }
    fun act(block: suspend () -> Unit) { scope.launch { call({ error = it }) { block() }; reload++ } }
    SheetDialog(onDismissRequest = dismiss, title = { Text("行李清单") }, confirmButton = { TextButton(dismiss) { Text("完成") } }, text = {
        Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(name, { name = it.take(80) }, Modifier.weight(1f), placeholder = { Text("加一样东西") }, singleLine = true, shape = RoundedCornerShape(22.dp))
                Button({ val n = name.trim(); act { api.request("POST", "trips/$tripId/packing", jsonBody("name" to n)); name = "" } }, enabled = name.isNotBlank()) { Text("添加") }
            }
            val items = data?.get("items").array().map { it.obj() }
            val names = items.map { it["name"].string() }.toSet()
            val templates = data?.get("templates").array().map { it.string() }.filter { it !in names }
            if (templates.isNotEmpty()) Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                templates.forEach { t -> AssistChip({ act { api.request("POST", "trips/$tripId/packing", jsonBody("name" to t)) } }, { Text("＋ $t") }) }
            }
            error?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) }
            val members = data?.get("members").array().map { it.string() }.orEmpty()
            items.forEach { item ->
                Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(MaterialTheme.colorScheme.surface).padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(item["name"].string(), Modifier.weight(1f), style = MaterialTheme.typography.bodyLarge)
                        IconButton({ act { api.request("DELETE", "trips/$tripId/packing/${item["id"].string()}") } }, Modifier.size(32.dp)) { Icon(Icons.Outlined.Close, "删除", Modifier.size(18.dp), tint = MaterialTheme.colorScheme.onSurfaceVariant) }
                    }
                    Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        members.forEach { member ->
                            val state = item["states"]?.obj()?.get(member).string().ifBlank { "unpacked" }
                            val next = when (state) { "unpacked" -> "packed"; "packed" -> "na"; else -> "unpacked" }
                            FilterChip(state == "packed", { act { api.request("PUT", "trips/$tripId/packing/${item["id"].string()}/state", jsonBody("state" to next, "member" to if (member == me) "" else member)) } },
                                { Text(member + when (state) { "packed" -> " ✓"; "na" -> " · 不用带"; else -> "" }) })
                        }
                    }
                }
            }
            if (items.isEmpty() && data != null) Note("点上面的常用物品快速添加。每个人各自打勾，也可以替同伴勾。")
        }
    })
}

/** 避坑提醒：重要的排前面。 */
@Composable fun TipsSheet(api: TravelService, tripId: String, dismiss: () -> Unit) {
    var rows by remember { mutableStateOf<List<JsonObject>?>(null) }
    var content by rememberSaveable { mutableStateOf("") }
    var important by rememberSaveable { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(reload) { call({ error = it }) { api.request("GET", "trips/$tripId/tips").array().map { it.obj() } }?.let { rows = it } }
    fun act(block: suspend () -> Unit) { scope.launch { call({ error = it }) { block() }; reload++ } }
    SheetDialog(onDismissRequest = dismiss, title = { Text("避坑提醒") }, confirmButton = { TextButton(dismiss) { Text("完成") } }, text = {
        Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedTextField(content, { content = it.take(300) }, Modifier.fillMaxWidth(), placeholder = { Text("如「清明上河园周一闭园」") }, maxLines = 3, shape = RoundedCornerShape(18.dp))
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(!important, { important = false }, { Text("提醒") }); FilterChip(important, { important = true }, { Text("重要") })
                Spacer(Modifier.weight(1f))
                Button({ val c = content.trim(); act { api.request("POST", "trips/$tripId/tips", jsonBody("content" to c, "level" to if (important) "important" else "notice")); content = "" } }, enabled = content.isNotBlank()) { Text("添加") }
            }
            error?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) }
            if (rows?.isEmpty() == true) Note("还没有提醒。踩过的坑记下来，同行的人就不用再踩。")
            rows.orEmpty().forEach { t ->
                val red = t["level"].string() == "important"
                Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(if (red) MaterialTheme.colorScheme.errorContainer else MaterialTheme.colorScheme.surface).padding(start = 12.dp, top = 8.dp, bottom = 8.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text((if (red) "重要 · " else "") + t["content"].string(), style = MaterialTheme.typography.bodyMedium)
                        t["created_by"].string().takeIf { it.isNotBlank() }?.let { Note(it) }
                    }
                    IconButton({ act { api.request("DELETE", "trips/$tripId/tips/${t["id"].string()}") } }) { Icon(Icons.Outlined.Close, "删除", tint = MaterialTheme.colorScheme.onSurfaceVariant) }
                }
            }
        }
    })
}

/** 调整当天顺序：上移 / 下移，完成时一次保存。 */
@Composable fun ReorderSheet(api: TravelService, tripId: String, day: Int, stops: List<JsonObject>, dismiss: () -> Unit, saved: () -> Unit) {
    var order by remember { mutableStateOf(stops) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    fun move(i: Int, delta: Int) { val j = i + delta; if (j in order.indices) order = order.toMutableList().also { val x = it[i]; it[i] = it[j]; it[j] = x } }
    SheetDialog(onDismissRequest = { if (!busy) dismiss() }, title = { Text("调整第 $day 天顺序") },
        dismissButton = { TextButton(dismiss, enabled = !busy) { Text("取消") } },
        confirmButton = { TextButton({ busy = true; scope.launch {
            if (call({ error = it }) { api.request("POST", "trips/$tripId/stops/reorder", jsonBody("day" to day, "ordered_ids" to JsonArray(order.map { JsonPrimitive(it["id"].string()) }))) } != null) saved()
            busy = false
        } }, enabled = !busy && order != stops) { Text("保存") } },
        text = { Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            order.forEachIndexed { i, s ->
                Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(MaterialTheme.colorScheme.surface).padding(start = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(24.dp).clip(CircleShape).background(MaterialTheme.colorScheme.primary), contentAlignment = Alignment.Center) {
                        Text("${i + 1}", color = MaterialTheme.colorScheme.onPrimary, style = MaterialTheme.typography.labelMedium)
                    }
                    Text(s["name"].string(), Modifier.weight(1f).padding(horizontal = 10.dp), maxLines = 1, overflow = TextOverflow.Ellipsis, fontWeight = FontWeight.Medium)
                    IconButton({ move(i, -1) }, enabled = i > 0) { Icon(Icons.Outlined.KeyboardArrowUp, "上移") }
                    IconButton({ move(i, 1) }, enabled = i < order.lastIndex) { Icon(Icons.Outlined.KeyboardArrowDown, "下移") }
                }
            }
            error?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) }
        } })
}
