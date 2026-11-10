package com.tongyou.travel.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.widget.Toast
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import com.tongyou.travel.data.*
import kotlinx.coroutines.*
import kotlinx.serialization.json.*
import java.time.LocalDate
import java.util.UUID

val LedgerCurrencies = listOf("CNY", "MYR", "SGD", "USD", "EUR", "JPY", "HKD", "THB", "KRW", "GBP", "AUD", "TWD", "VND", "IDR")
private val CurrencyNames = mapOf("CNY" to "人民币", "MYR" to "马币", "SGD" to "新币", "USD" to "美元", "EUR" to "欧元", "JPY" to "日元", "HKD" to "港币",
    "THB" to "泰铢", "KRW" to "韩元", "GBP" to "英镑", "AUD" to "澳元", "TWD" to "台币", "VND" to "越南盾", "IDR" to "印尼盾")
private val LedgerCategories = listOf("餐饮", "交通", "住宿", "门票", "购物", "其他")
fun ledgerMoney(minor: Int, currency: String) = "$currency ${"%.2f".format(java.util.Locale.US, minor / 100.0)}"
fun ledgerRole(role: String) = when (role) { "owner" -> "创建者"; "editor" -> "可编辑"; else -> "只读" }
/** Same rule as the server and iOS: positive, at most 7 integer digits and 2 decimals. */
fun validLedgerAmount(text: String): String? {
    val clean = text.trim().replace(',', '.')
    if (!Regex("^\\d{1,7}(\\.\\d{1,2})?$").matches(clean)) return null
    return clean.takeIf { it.toBigDecimal() > java.math.BigDecimal.ZERO }
}

/** Runs `block` off the main thread and reports failures as a message; cancellation passes through. */
private suspend fun <T> attempt(error: (String?) -> Unit, block: suspend () -> T): T? = try {
    withContext(Dispatchers.IO) { block() }.also { error(null) }
} catch (e: CancellationException) { throw e } catch (e: Exception) { error(e.message ?: "操作失败，请重试"); null }

@Composable fun LedgerScreen(api: TravelService, open: (String) -> Unit) {
    var books by remember { mutableStateOf<List<JsonObject>?>(null) }
    var invites by remember { mutableStateOf<List<JsonObject>>(emptyList()) }
    var error by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    var creating by rememberSaveable { mutableStateOf(false) }
    var joining by rememberSaveable { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(reload, lifecycle) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            attempt({ error = it }) { api.request("GET", "ledger").array().map { it.obj() } }?.let { books = it }
            attempt({}) { api.request("GET", "ledger/invites/pending").array().map { it.obj() } }?.let { invites = it }
        }
    }
    LazyColumn(contentPadding = PaddingValues(start = 20.dp, top = 20.dp, end = 20.dp, bottom = 24.dp + LocalBottomInset.current),
        verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("旅行记账", style = MaterialTheme.typography.headlineMedium)
                    Text("旅行中的每一笔，都记在这里", color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyMedium)
                }
                IconButton({ joining = true }) { Icon(Icons.Outlined.Link, "用链接加入账本") }
                FilledIconButton({ creating = true }) { Icon(Icons.Outlined.Add, "新建账本") }
            }
        }
        error?.let { item { ErrorNotice(it) { reload++ } } }
        if (books == null && error == null) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
        items(invites, key = { "invite-" + it["id"].string() }) { invite ->
            GlassCard(Modifier.fillMaxWidth()) {
                Text(invite["title"].string(), style = MaterialTheme.typography.titleMedium)
                Text("${invite["inviter"].string()} 邀请你加入 · ${ledgerRole(invite["role"].string())}", style = MaterialTheme.typography.bodyMedium)
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    fun respond(accept: Boolean) { if (busy) return; busy = true; scope.launch {
                        val done = attempt({ error = it }) { api.request("POST", "ledger/${invite["id"].string()}/invites/respond", jsonBody("accept" to accept)) }
                        busy = false; reload++; if (done != null && accept) open(invite["id"].string())
                    } }
                    Button({ respond(true) }, enabled = !busy) { Text("接受邀请") }
                    OutlinedButton({ respond(false) }, enabled = !busy) { Text("拒绝") }
                }
            }
        }
        if (books?.isEmpty() == true) item {
            GlassCard(Modifier.fillMaxWidth()) {
                Text("记录第一趟旅行的花费", style = MaterialTheme.typography.titleMedium)
                Text("不用先建行程。新建账本后，就能记录餐饮、交通和住宿等支出。", color = MaterialTheme.colorScheme.onSurfaceVariant)
                Button({ creating = true }) { Text("＋ 新建账本") }
            }
        }
        items(books.orEmpty(), key = { it["id"].string() }) { book ->
            GlassCard(Modifier.fillMaxWidth().clip(RoundedCornerShape(24.dp)).clickable { open(book["id"].string()) }) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(book["title"].string(), Modifier.weight(1f), style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text("›", color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.titleLarge)
                }
                val totals = book["totals"]?.obj().orEmpty()
                if (totals.isEmpty()) Text("还没有支出", color = MaterialTheme.colorScheme.onSurfaceVariant)
                totals.keys.sorted().forEach { currency ->
                    Text(ledgerMoney(totals[currency].int(), currency), style = MaterialTheme.typography.titleLarge, color = MaterialTheme.colorScheme.primary)
                }
                Text((book["trip"] as? JsonObject)?.let { "关联行程：${it["title"].string()}" } ?: "独立账本", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text("${book["count"].int()} 笔支出 · ${ledgerRole(book["role"].string())}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
    if (creating) NameDialog("新建账本", "比如：马来西亚之行", "", "创建", { creating = false }) { title ->
        attempt({ error = it }) { api.request("POST", "ledger", jsonBody("title" to title, "trip_id" to null)).obj()["id"].string() }
            ?.let { creating = false; reload++; if (it.isNotEmpty()) open(it) }
    }
    if (joining) NameDialog("用链接加入账本", "粘贴朋友发来的账本链接", "", "加入", { joining = false }) { link ->
        val token = Regex("ledger_join=([A-Za-z0-9_-]{32,64})").find(link)?.groupValues?.get(1) ?: link.trim()
        attempt({ error = it }) { api.request("POST", "ledger/join", jsonBody("token" to token)).obj()["id"].string() }
            ?.let { joining = false; reload++; if (it.isNotEmpty()) open(it) }
    }
}

/** One text field and a confirm action that stays open (and shows the screen's error) until it succeeds. */
@Composable private fun NameDialog(title: String, hint: String, initial: String, confirm: String, dismiss: () -> Unit, submit: suspend (String) -> Unit) {
    var value by rememberSaveable { mutableStateOf(initial) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    SheetDialog(onDismissRequest = { if (!busy) dismiss() }, title = { Text(title) },
        text = { OutlinedTextField(value, { value = it }, Modifier.fillMaxWidth(), placeholder = { Text(hint) }, singleLine = true, enabled = !busy) },
        confirmButton = { TextButton({ busy = true; scope.launch { try { submit(value.trim()) } finally { busy = false } } }, enabled = !busy && value.isNotBlank()) { Text(if (busy) "请稍候…" else confirm) } },
        dismissButton = { TextButton(dismiss, enabled = !busy) { Text("取消") } })
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable fun LedgerDetailScreen(api: TravelService, id: String, back: () -> Unit) {
    var book by remember { mutableStateOf<JsonObject?>(null) }
    var fx by remember { mutableStateOf<JsonObject?>(null) }
    var fxBusy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    var editing by remember { mutableStateOf<JsonObject?>(null) }
    var adding by rememberSaveable { mutableStateOf(false) }
    var members by rememberSaveable { mutableStateOf(false) }
    var renaming by rememberSaveable { mutableStateOf(false) }
    var menu by remember { mutableStateOf(false) }
    var removing by remember { mutableStateOf<JsonObject?>(null) }
    var removingBook by rememberSaveable { mutableStateOf(false) }
    var details by rememberSaveable { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val role = book?.get("role").string()
    val owner = role == "owner"
    val canEdit = owner || role == "editor"
    suspend fun loadFx(refresh: Boolean) {
        fxBusy = true
        attempt({}) { api.request("GET", "ledger/$id/conversion", query = listOf("refresh" to refresh.toString())).obj() }?.let { fx = it }
        fxBusy = false
    }
    LaunchedEffect(reload) {
        attempt({ error = it }) { api.request("GET", "ledger/$id").obj() }?.let { book = it; loadFx(false) }
    }
    Scaffold(containerColor = androidx.compose.ui.graphics.Color.Transparent, contentWindowInsets = WindowInsets(0), topBar = {
        CenterAlignedTopAppBar(title = { Text(book?.get("title").string().ifBlank { "账本" }, maxLines = 1, overflow = TextOverflow.Ellipsis) },
            navigationIcon = { IconButton(back) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "返回记账") } },
            colors = TopAppBarDefaults.centerAlignedTopAppBarColors(containerColor = androidx.compose.ui.graphics.Color.Transparent), windowInsets = WindowInsets(0),
            actions = {
                IconButton({ members = true }) { Icon(Icons.Outlined.Group, "成员与分享") }
                Box {
                    IconButton({ menu = true }) { Icon(Icons.Outlined.MoreVert, "更多") }
                    DropdownMenu(menu, { menu = false }) {
                        if (owner) DropdownMenuItem({ Text("重命名账本") }, { menu = false; renaming = true })
                        DropdownMenuItem({ Text(if (owner) "删除账本" else "退出账本", color = MaterialTheme.colorScheme.error) }, { menu = false; removingBook = true })
                    }
                }
            })
    }, floatingActionButton = {
        if (canEdit) ExtendedFloatingActionButton(shape = androidx.compose.foundation.shape.CircleShape, elevation = FloatingActionButtonDefaults.elevation(2.dp, 2.dp, 2.dp, 2.dp), onClick = { adding = true }, containerColor = MaterialTheme.colorScheme.primary, contentColor = MaterialTheme.colorScheme.onPrimary,
            icon = { Icon(Icons.Outlined.Add, null) }, text = { Text("记一笔") })
    }) { padding ->
        val current = book
        LazyColumn(Modifier.padding(padding), contentPadding = PaddingValues(start = 20.dp, top = 8.dp, end = 20.dp, bottom = 96.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            error?.let { item { ErrorNotice(it) { reload++ } } }
            if (current == null) { if (error == null) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }; return@LazyColumn }
            val target = current["target_currency"].string().ifBlank { "CNY" }
            item {
                GlassCard(Modifier.fillMaxWidth()) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("累计支出 · ${current["count"].int()} 笔", Modifier.weight(1f), color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyMedium)
                        CurrencyPicker(target, enabled = owner && !fxBusy) { currency -> scope.launch {
                            attempt({ error = it }) { api.request("PATCH", "ledger/$id/currency", jsonBody("target_currency" to currency)) }; reload++
                        } }
                    }
                    val total = (fx?.get("total_minor") as? JsonPrimitive)?.intOrNull
                    when {
                        fxBusy && fx == null -> Text("正在换算…", color = MaterialTheme.colorScheme.onSurfaceVariant)
                        total != null -> Text(ledgerMoney(total, target), style = MaterialTheme.typography.displaySmall, color = MaterialTheme.colorScheme.primary, maxLines = 1)
                        else -> Text("暂无法完整换算", style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Text("按最新参考汇率估算", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    if (fx?.get("stale").bool()) Text("更新暂不可用，当前使用上次查询汇率。", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.tertiary)
                    fx?.get("missing").array().map { it.string() }.takeIf { it.isNotEmpty() }?.let {
                        Text("未获得 ${it.joinToString("、")} 汇率，暂不显示完整总额。", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.tertiary)
                    }
                    TextButton({ details = !details }, contentPadding = PaddingValues(0.dp)) { Text(if (details) "收起汇率与原币明细" else "汇率与原币明细") }
                    if (details) {
                        val totals = current["totals"]?.obj().orEmpty()
                        totals.keys.sorted().forEach { Text(ledgerMoney(totals[it].int(), it), fontWeight = FontWeight.Medium) }
                        fx?.get("items").array().forEach { item -> val quote = item.obj()
                            Text("1 ${quote["currency"].string()} ≈ ${quote["rate"].string().toDoubleOrNull()?.let { "%.6f".format(java.util.Locale.US, it) } ?: quote["rate"].string()} $target · 行情日期 ${quote["rate_date"].string()}",
                                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        Text("参考汇率按日更新，实际换汇或刷卡金额可能不同。", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        TextButton({ scope.launch { loadFx(true) } }, enabled = !fxBusy, contentPadding = PaddingValues(0.dp)) { Text(if (fxBusy) "正在刷新…" else "刷新汇率") }
                    }
                }
            }
            if (canEdit) item { QuickEntry(api, id) { reload++ } }
            item { Text("支出明细", style = MaterialTheme.typography.titleMedium) }
            val entries = current["entries"].array().map { it.obj() }
            if (entries.isEmpty()) item { Text("还没有账单，先记下今天的第一笔花费吧。", color = MaterialTheme.colorScheme.onSurfaceVariant) }
            entries.groupBy { it["spent_at"].string() }.toSortedMap(compareByDescending { it }).forEach { (day, rows) ->
                item(key = "day-$day") { Text(day, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                items(rows, key = { it["id"].string() }) { entry ->
                    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(MaterialTheme.colorScheme.surface.copy(alpha = .92f))
                        .border(1.dp, MaterialTheme.colorScheme.outlineVariant, RoundedCornerShape(18.dp))
                        .clickable(enabled = canEdit) { editing = entry }.padding(horizontal = 16.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(entry["title"].string().ifBlank { entry["category"].string() }, style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text(listOf(entry["category"].string(), entry["note"].string()).filter(String::isNotBlank).joinToString(" · "),
                                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                        Text(ledgerMoney(entry["amount_minor"].int(), entry["currency"].string()), fontWeight = FontWeight.SemiBold)
                    }
                }
            }
        }
    }
    val current = book
    if ((adding || editing != null) && current != null) EntryDialog(api, id, editing, current["target_currency"].string().ifBlank { "CNY" },
        { adding = false; editing = null }, { adding = false; editing = null; reload++ }) { removing = it; editing = null }
    removing?.let { entry ->
        AlertDialog(onDismissRequest = { removing = null }, title = { Text("删除这笔账单？") }, text = { Text(entry["title"].string().ifBlank { entry["category"].string() }) },
            confirmButton = { TextButton({ removing = null; scope.launch {
                attempt({ error = it }) { api.request("DELETE", "ledger/$id/entries/${entry["id"].string()}", query = listOfNotNull((entry["version"] as? JsonPrimitive)?.intOrNull?.let { "version" to it.toString() })) }
                reload++ } }) { Text("删除", color = MaterialTheme.colorScheme.error) } },
            dismissButton = { TextButton({ removing = null }) { Text("取消") } })
    }
    if (removingBook) AlertDialog(onDismissRequest = { removingBook = false }, title = { Text(if (owner) "删除这个账本？" else "退出这个账本？") },
        text = { Text(if (owner) "账本和其中的全部账单会对所有成员删除，无法恢复。" else "退出后看不到这个账本，已有账单不受影响。") },
        confirmButton = { TextButton({ removingBook = false; scope.launch {
            if (attempt({ error = it }) { api.request(if (owner) "DELETE" else "POST", "ledger/$id" + if (owner) "" else "/leave") } != null) back()
        } }) { Text(if (owner) "删除账本" else "退出账本", color = MaterialTheme.colorScheme.error) } },
        dismissButton = { TextButton({ removingBook = false }) { Text("取消") } })
    if (renaming && current != null) NameDialog("重命名账本", "账本名称", current["title"].string(), "保存", { renaming = false }) { title ->
        attempt({ error = it }) { api.request("PATCH", "ledger/$id", jsonBody("title" to title, "trip_id" to (current["trip"] as? JsonObject)?.get("id").string().ifBlank { null })) }
            ?.let { renaming = false; reload++ }
    }
    if (members) MembersDialog(api, id, owner) { members = false }
}

@Composable private fun CurrencyPicker(value: String, enabled: Boolean = true, pick: (String) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Box {
        TextButton({ open = true }, enabled = enabled) { Text("$value ▾") }
        DropdownMenu(open, { open = false }) {
            LedgerCurrencies.forEach { currency -> DropdownMenuItem({ Text("$currency · ${CurrencyNames[currency]}") }, { open = false; if (currency != value) pick(currency) }) }
        }
    }
}

/** 一句话记账：模型只出草稿，逐项可改可删，确认后一次入账。 */
@Composable private fun QuickEntry(api: TravelService, id: String, saved: () -> Unit) {
    var text by rememberSaveable { mutableStateOf("") }
    var drafts by remember { mutableStateOf<List<JsonObject>?>(null) }
    var notice by remember { mutableStateOf<String?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    GlassCard(Modifier.fillMaxWidth()) {
        Text("一句话记账", style = MaterialTheme.typography.titleMedium)
        Text("说今天花了什么，我来拆成账单，确认后才记上", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        val list = drafts
        if (list == null) Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(text, { text = it.take(500) }, Modifier.weight(1f), placeholder = { Text("拉面 1200 日元，打车 2800") }, enabled = !busy, maxLines = 3, shape = RoundedCornerShape(16.dp))
            FilledIconButton({ busy = true; notice = null; scope.launch {
                attempt({ error = it }) { api.request("POST", "ledger/$id/ai-draft", jsonBody("text" to text.trim(), "today" to LocalDate.now().toString())).obj() }?.let { reply ->
                    drafts = reply["drafts"].array().map { it.obj() }
                    if (reply["dropped"].int() > 0) notice = "有 ${reply["dropped"].int()} 处没认出金额，没有列进来。"
                }
                busy = false
            } }, enabled = !busy && text.isNotBlank()) { Icon(Icons.Outlined.AutoAwesome, if (busy) "正在识别" else "识别") }
        } else {
            if (list.isEmpty()) Text("都移除了，可以返回重新说一句。", style = MaterialTheme.typography.bodySmall)
            list.forEachIndexed { index, draft ->
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Column(Modifier.weight(1f)) {
                        Text(draft["title"].string(), maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text("${draft["category"].string()} · ${draft["spent_at"].string()}" + if (draft["currency_guessed"].bool()) " · 币种是推测的" else "",
                            style = MaterialTheme.typography.bodySmall, color = if (draft["currency_guessed"].bool()) MaterialTheme.colorScheme.tertiary else MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Text(draft["amount"].string(), fontWeight = FontWeight.SemiBold)
                    CurrencyPicker(draft["currency"].string()) { currency ->
                        drafts = list.toMutableList().also { it[index] = JsonObject(draft + ("currency" to JsonPrimitive(currency)) + ("currency_guessed" to JsonPrimitive(false))) }
                    }
                    IconButton({ drafts = list - draft }) { Icon(Icons.Outlined.Close, "移除这一笔") }
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedButton({ drafts = null; notice = null }, enabled = !busy) { Text("返回修改") }
                Button({ busy = true; scope.launch {
                    val entries = JsonArray(list.map { d -> jsonBody("id" to d["id"].string(), "title" to d["title"].string(), "amount" to d["amount"].string(),
                        "currency" to d["currency"].string(), "category" to d["category"].string(), "spent_at" to d["spent_at"].string(), "note" to d["note"].string()) })
                    if (attempt({ error = it }) { api.request("POST", "ledger/$id/entries/batch", jsonBody("entries" to entries)) } != null) {
                        notice = "已记上 ${list.size} 笔。"; drafts = null; text = ""; saved()
                    }
                    busy = false
                } }, enabled = !busy && list.isNotEmpty() && list.all { validLedgerAmount(it["amount"].string()) != null }) { Text(if (busy) "正在记账…" else "确认记上 ${list.size} 笔") }
            }
        }
        notice?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
        error?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) }
    }
}

@Composable private fun EntryDialog(api: TravelService, id: String, entry: JsonObject?, defaultCurrency: String,
                                    dismiss: () -> Unit, saved: () -> Unit, remove: (JsonObject) -> Unit) {
    var title by rememberSaveable { mutableStateOf(entry?.get("title").string()) }
    var amount by rememberSaveable { mutableStateOf(entry?.let { "%.2f".format(java.util.Locale.US, it["amount_minor"].int() / 100.0) }.orEmpty()) }
    var currency by rememberSaveable { mutableStateOf(entry?.get("currency").string().ifBlank { defaultCurrency }) }
    var category by rememberSaveable { mutableStateOf(entry?.get("category").string().ifBlank { "餐饮" }) }
    var day by rememberSaveable { mutableStateOf(entry?.get("spent_at").string().ifBlank { LocalDate.now().toString() }) }
    var note by rememberSaveable { mutableStateOf(entry?.get("note").string()) }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val requestId = rememberSaveable { UUID.randomUUID().toString() }     // 重试同一次提交不会记成两笔
    val scope = rememberCoroutineScope()
    SheetDialog(onDismissRequest = { if (!busy) dismiss() }, title = { Text(if (entry == null) "记一笔" else "修改账单") }, text = {
        Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(amount, { amount = it }, Modifier.weight(1f), label = { Text("金额") }, singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), enabled = !busy)
                CurrencyPicker(currency, !busy) { currency = it }
            }
            OutlinedTextField(title, { title = it.take(80) }, Modifier.fillMaxWidth(), label = { Text("花在什么上（可不填）") }, singleLine = true, enabled = !busy)
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                LedgerCategories.forEach { FilterChip(category == it, { category = it }, { Text(it) }, enabled = !busy) }
            }
            OutlinedTextField(day, { day = it.take(10) }, Modifier.fillMaxWidth(), label = { Text("日期（如 2026-11-10）") }, singleLine = true, enabled = !busy)
            OutlinedTextField(note, { note = it.take(500) }, Modifier.fillMaxWidth(), label = { Text("备注（可不填）") }, maxLines = 3, enabled = !busy)
            error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
            if (entry != null) TextButton({ remove(entry) }, enabled = !busy, contentPadding = PaddingValues(0.dp)) { Text("删除这笔账单", color = MaterialTheme.colorScheme.error) }
        }
    }, confirmButton = { TextButton({
        val clean = validLedgerAmount(amount)
        if (clean == null) { error = "请输入大于 0、最多两位小数的金额"; return@TextButton }
        if (runCatching { LocalDate.parse(day) }.isFailure) { error = "日期格式是 2026-11-10 这样"; return@TextButton }
        busy = true
        scope.launch {
            val done = attempt({ error = it }) { api.request(if (entry == null) "POST" else "PATCH", "ledger/$id/entries" + (entry?.let { "/${it["id"].string()}" } ?: ""),
                jsonBody("id" to requestId, "title" to title.trim(), "amount" to clean, "currency" to currency, "category" to category, "spent_at" to day,
                    "note" to note.trim(), "version" to (entry?.get("version") as? JsonPrimitive)?.intOrNull)) }
            busy = false; if (done != null) saved()
        }
    }, enabled = !busy) { Text(if (busy) "正在保存…" else "保存") } },
        dismissButton = { TextButton(dismiss, enabled = !busy) { Text("取消") } })
}

@Composable private fun MembersDialog(api: TravelService, id: String, owner: Boolean, dismiss: () -> Unit) {
    var rows by remember { mutableStateOf<List<JsonObject>?>(null) }
    var name by rememberSaveable { mutableStateOf("") }
    var editor by rememberSaveable { mutableStateOf(true) }
    var message by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var reload by remember { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    LaunchedEffect(reload) { attempt({ message = it }) { api.request("GET", "ledger/$id/members").array().map { it.obj() } }?.let { rows = it } }
    SheetDialog(onDismissRequest = dismiss, title = { Text("成员与分享") }, text = {
        Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (rows == null) LinearProgressIndicator(Modifier.fillMaxWidth())
            rows.orEmpty().forEach { member ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("@" + member["username"].string(), Modifier.weight(1f))
                    Text(ledgerRole(member["role"].string()) + if (member["status"].string() == "pending") " · 待接受" else "", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    if (owner && member["role"].string() != "owner") IconButton({ scope.launch {
                        attempt({ message = it }) { api.request("DELETE", "ledger/$id/members/${member["id"].string()}") }; reload++ } }) { Icon(Icons.Outlined.Close, "移除成员") }
                }
            }
            if (owner) {
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FilterChip(editor, { editor = true }, { Text("可编辑") }); FilterChip(!editor, { editor = false }, { Text("只读") })
                }
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(name, { name = it }, Modifier.weight(1f), label = { Text("对方的用户名") }, singleLine = true, enabled = !busy)
                    TextButton({ busy = true; scope.launch {
                        if (attempt({ message = it }) { api.request("POST", "ledger/$id/members", jsonBody("username" to name.trim(), "role" to if (editor) "editor" else "viewer")) } != null) { message = "邀请已发出，等对方接受。"; name = "" }
                        busy = false; reload++
                    } }, enabled = !busy && name.isNotBlank()) { Text("邀请") }
                }
                TextButton({ busy = true; scope.launch {
                    attempt({ message = it }) { api.request("POST", "ledger/$id/share", jsonBody("role" to if (editor) "editor" else "viewer")).obj()["token"].string() }?.takeIf { it.isNotEmpty() }?.let { token ->
                        val url = "https://17tongyou.com/travel/?ledger_join=$token"
                        context.getSystemService(ClipboardManager::class.java).setPrimaryClip(ClipData.newPlainText("账本邀请", url))
                        Toast.makeText(context, "链接已复制，7 天内有效", Toast.LENGTH_SHORT).show()
                        runCatching { context.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, "一起记这趟旅行的账：$url"), "分享账本")) }
                    }
                    busy = false
                } }, enabled = !busy, contentPadding = PaddingValues(0.dp)) { Text("生成邀请链接并分享") }
                Text("拿到链接的人可以按上面选的权限加入。", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            message?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
        }
    }, confirmButton = { TextButton(dismiss) { Text("完成") } })
}
