package com.tongyou.travel.ui

import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import coil.compose.AsyncImage
import com.tongyou.travel.data.*
import kotlinx.coroutines.*
import kotlinx.serialization.json.*
import java.time.LocalDate

@Composable fun HomeScreen(api: TravelService, account: JsonObject?, ask: (String) -> Unit,
                           go: (String, String?) -> Unit, external: (String) -> Unit) {
    var trips by remember { mutableStateOf<List<JsonObject>>(emptyList()) }
    var today by remember { mutableStateOf<JsonObject?>(null) }
    var cities by remember { mutableStateOf(listOf("杭州", "平潭岛", "武功山", "武汉")) }
    var covers by remember { mutableStateOf<JsonObject>(JsonObject(emptyMap())) }
    var unread by remember { mutableIntStateOf(0) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var refresh by remember { mutableIntStateOf(0) }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(refresh, lifecycle) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            launch {
                try { trips = withContext(Dispatchers.IO) { api.request("GET", "trips").array().map { it.obj() } }; error = null }
                catch (e: CancellationException) { throw e } catch (e: Exception) { error = e.message }
                finally { loading = false }
            }
            launch { try { today = withContext(Dispatchers.IO) { api.request("GET", "trips/today", query = listOf("date" to LocalDate.now().toString())).obj()["trip"] as? JsonObject } } catch (e: CancellationException) { throw e } catch (_: Exception) {} }
            launch {
                try {
                    val names = withContext(Dispatchers.IO) { api.request("GET", "onboarding").obj()["trending"].array().map { it.string() }.filter(String::isNotBlank).take(4) }
                    if (names.isNotEmpty()) cities = names
                    covers = withContext(Dispatchers.IO) { api.request("GET", "onboarding/covers", query = cities.map { "destinations" to it }).obj()["covers"]?.obj() ?: covers }
                } catch (e: CancellationException) { throw e } catch (_: Exception) { }
            }
            while (isActive) {
                try { unread = withContext(Dispatchers.IO) {
                    api.request("GET", "notifications/unread-count").obj()["unread"].int() + api.request("GET", "announcements/unread").obj()["unread"].int()
                } } catch (e: CancellationException) { throw e } catch (_: Exception) { }
                delay(30000)
            }
        }
    }
    val inset = LocalBottomInset.current
    LazyColumn(contentPadding = PaddingValues(start = 20.dp, top = 20.dp, end = 20.dp, bottom = 24.dp + inset), verticalArrangement = Arrangement.spacedBy(26.dp)) {
        item {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text("17同游", style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
                IconButton(onClick = { go("notifications", null) }, modifier = Modifier.clip(RoundedCornerShape(22.dp)).background(MaterialTheme.colorScheme.surface.copy(alpha = .8f))) {
                    BadgedBox(badge = { if (unread > 0) Badge { Text(unread.coerceAtMost(99).toString()) } }) { Icon(Icons.Outlined.Notifications, "通知") }
                }
            }
        }
        item {
            Text("${account?.get("display_name").string().ifBlank { "朋友" }}，下一站去哪儿？", color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyMedium)
            Spacer(Modifier.height(8.dp))
            Text("把期待，\n变成一段旅行。", style = MaterialTheme.typography.displaySmall)
        }
        today?.let { trip -> item {
            GlassCard(Modifier.fillMaxWidth()) {
                Text(when {
                    trip["day"].int() > 0 -> "今天 · 第 ${trip["day"].int()} / ${trip["days"].int().coerceAtLeast(trip["day"].int())} 天"
                    trip["starts_in"].int() == 1 -> "明天出发"
                    else -> "还有 ${trip["starts_in"].int()} 天出发"
                }, color = MaterialTheme.colorScheme.primary)
                if (trip["day"].int() > 0 && trip["stops"].array().isEmpty()) Text("今天还没有安排，打开行程加几个地点。", style = MaterialTheme.typography.bodySmall)
                Text(trip["day_title"].string().ifBlank { trip["title"].string() }, style = MaterialTheme.typography.titleLarge)
                trip["stops"].array().take(5).forEach { item ->
                    val stop = item.obj()
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(listOf(stop["start_time"].string(), stop["name"].string()).filter(String::isNotBlank).joinToString("  "), Modifier.weight(1f), maxLines = 1)
                        val nav = stop["nav"]?.obj()
                        val url = if (nav?.get("domestic").bool()) nav?.get("amap").string() else nav?.get("google").string().ifBlank { nav?.get("apple").string() }
                        if (url.isNotBlank()) TextButton(onClick = { external(url) }) { Text("导航") }
                    }
                }
                TextButton({ go("trips", trip["id"].string()) }) { Text("打开今天的行程 ↗") }
            }
        } }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Button({ go("createTrip", null) }, Modifier.height(48.dp), contentPadding = PaddingValues(horizontal = 22.dp)) { Text("＋ 新建旅行") }
                OutlinedButton({ ask("帮我把这篇攻略整理成行程：") }, Modifier.height(48.dp), contentPadding = PaddingValues(horizontal = 22.dp),
                    border = BorderStroke(1.dp, MaterialTheme.colorScheme.outline), colors = ButtonDefaults.outlinedButtonColors(containerColor = MaterialTheme.colorScheme.surface.copy(alpha = .7f), contentColor = MaterialTheme.colorScheme.onSurface)) { Text("↗ 导入攻略") }
            }
        }
        item {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text("我的旅行", style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
                TextButton({ go("trips", null) }) { Text("全部行程 ↗", style = MaterialTheme.typography.bodyMedium) }
            }
            Spacer(Modifier.height(6.dp))
            if (loading) LinearProgressIndicator(Modifier.fillMaxWidth())
            error?.let { ErrorNotice(it) { refresh++ } }
            if (!loading && error == null && trips.isEmpty()) GlassCard(Modifier.fillMaxWidth()) {
                Text("第一本旅行册，等你翻开", style = MaterialTheme.typography.titleMedium)
                Text("先选一个目的地，慢慢安排每一天。")
                TextButton({ ask("帮我规划一次轻松的周末旅行") }) { Text("一起想想去哪儿 ↗") }
            }
            LazyRow(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                itemsIndexed(trips.take(4), key = { _, it -> it["id"].string() }) { index, trip ->
                    // Four soft tones in rotation, like the travel-book covers on the web client.
                    val dark = LocalDarkTheme.current
                    val tone = (if (dark) listOf(Color(0xFF1B2A4A), Color(0xFF3A2A1E), Color(0xFF1C3530), Color(0xFF3A2430))
                                else listOf(Color(0xFFE6EEFF), Color(0xFFFFEFE2), Color(0xFFE5F5EE), Color(0xFFFDEBF0)))[index % 4]
                    val shape = RoundedCornerShape(24.dp)
                    Column(Modifier.width(264.dp).height(168.dp).clip(shape).background(tone, shape)
                        .border(1.dp, MaterialTheme.colorScheme.outlineVariant.copy(alpha = .6f), shape)
                        .clickable { go("trips", trip["id"].string()) }.padding(20.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(trip["destination"].string().ifBlank { "目的地待定" }, Modifier.weight(1f), style = MaterialTheme.typography.labelLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text("${trip["days"].int()} 天", style = MaterialTheme.typography.labelLarge)
                        }
                        Spacer(Modifier.weight(1f))
                        Text(trip["title"].string(), style = MaterialTheme.typography.titleLarge, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        Spacer(Modifier.height(10.dp))
                        Row {
                            Text(if (trip["role"].string() == "owner") "我的行程" else "一起规划", Modifier.weight(1f), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Text("打开 ↗", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
            }
        }
        item {
            Text("下一站灵感", style = MaterialTheme.typography.titleLarge)
            Spacer(Modifier.height(14.dp))
            LazyRow(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                items(cities.distinct()) { city ->
                    Box(Modifier.size(200.dp, 140.dp).clip(RoundedCornerShape(22.dp)).background(BrandBlue.copy(alpha = .7f))
                        .clickable { ask("我想去$city，帮我规划一次旅行") }, contentAlignment = Alignment.BottomStart) {
                        AsyncImage(TravelApi.media(covers[city].string()), null, Modifier.matchParentSize(), contentScale = ContentScale.Crop)
                        Box(Modifier.matchParentSize().background(Brush.verticalGradient(listOf(Color.Transparent, Color.Black.copy(alpha = .65f)))))
                        Column(Modifier.padding(18.dp)) { Text(city, color = Color.White, style = MaterialTheme.typography.titleLarge); Text("留一点时间，去看看", color = Color.White, style = MaterialTheme.typography.bodySmall) }
                    }
                }
            }
        }
    }
}
