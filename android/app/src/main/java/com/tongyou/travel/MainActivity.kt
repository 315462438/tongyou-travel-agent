package com.tongyou.travel

import android.content.Intent
import android.content.res.Configuration
import android.net.Uri
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.animation.*
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import kotlinx.coroutines.withContext
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.animation.core.tween
import androidx.compose.foundation.layout.*
import dev.chrisbanes.haze.hazeSource
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.platform.UriHandler
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.createSavedStateHandle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import androidx.navigation.compose.*
import androidx.navigation.navArgument
import androidx.navigation.NavType
import com.tongyou.travel.chat.*
import com.tongyou.travel.data.*
import com.tongyou.travel.ui.*
import kotlinx.coroutines.launch

/** The old component name remains the exported entry, preserving installed shortcuts and App Links. */
class MainActivity : ComponentActivity() {
    private var pendingLink by mutableStateOf<String?>(null)
    private val appearancePrefs by lazy { getSharedPreferences("appearance", MODE_PRIVATE) }
    private var appearance by mutableStateOf(Appearance.SYSTEM)
    /** Replaced by the update instrumentation test with a fake source. */
    @androidx.annotation.VisibleForTesting lateinit var updates: AppUpdates
    private val app get() = application as TongyouApplication
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        appearance = readAppearance(appearancePrefs)
        pendingLink = savedInstanceState?.getString("pending_link") ?: incoming(intent)
        updates = AppUpdates(this, AppUpdates.Source { if (app.service is TravelApi) AppUpdates.fetchOfficial() else null },
            ::external, getSharedPreferences("app_updates", MODE_PRIVATE))
        if (app.session.state.value.checking) lifecycleScope.launch { app.session.restore(app.service) }
        setContent {
            TongyouTheme(appearance) {
                // Status / navigation bar icons follow the in-app choice, not only the system setting.
                val dark = LocalDarkTheme.current
                LaunchedEffect(dark) {
                    val transparent = android.graphics.Color.TRANSPARENT
                    val style = if (dark) androidx.activity.SystemBarStyle.dark(transparent) else androidx.activity.SystemBarStyle.light(transparent, transparent)
                    enableEdgeToEdge(style, style)
                }
                CompositionLocalProvider(LocalUriHandler provides object : UriHandler { override fun openUri(uri: String) = external(uri) }) {
                    Backdrop(Modifier.fillMaxSize()) {
                      CompositionLocalProvider(LocalContentColor provides MaterialTheme.colorScheme.onBackground) {
                        val state by app.session.state.collectAsStateWithLifecycle()
                        LaunchedEffect(state.checking) { if (!state.checking) updates.onReady() }
                        when {
                            state.checking -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
                            state.error != null -> Box(Modifier.fillMaxSize().safeDrawingPadding().padding(24.dp), contentAlignment = Alignment.Center) {
                                Column(verticalArrangement = Arrangement.spacedBy(8.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                                    ErrorNotice(state.error!!) { lifecycleScope.launch { app.session.restore(app.service) } }
                                    // 重试只会重复同样的读取；读不出来时必须有一条能回到登录页的路。
                                    TextButton({ lifecycleScope.launch { app.session.resetToLogin() } }, Modifier.testTag("reset-login")) { Text("重新登录") }
                                }
                            }
                            state.token == null -> LoginScreen(app.session, app.service)
                            else -> key(state.token) {
                                NativeShell(app, ::external, pendingLink, { pendingLink = null }, appearance) { choice ->
                                    appearance = choice; appearancePrefs.edit().putString("appearance", choice.name).apply()
                                }
                            }
                        }
                      }
                    }
                }
            }
        }
    }
    private fun external(url: String) {
        if (!UrlPolicy.external(url)) return
        try { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addCategory(Intent.CATEGORY_BROWSABLE)) }
        catch (_: android.content.ActivityNotFoundException) { Toast.makeText(this, "手机没有可用的浏览器", Toast.LENGTH_LONG).show() }
    }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent); setIntent(intent)
        incoming(intent)?.let { pendingLink = it }
    }
    override fun onSaveInstanceState(outState: Bundle) { outState.putString("pending_link", pendingLink); super.onSaveInstanceState(outState) }
    override fun onResume() {
        super.onResume()
        if (::updates.isInitialized) updates.onResume()
        if (!app.session.state.value.checking) lifecycleScope.launch { app.session.refresh(app.service) }
    }
    override fun onPause() { if (::updates.isInitialized) updates.onPause(); super.onPause() }
    override fun onConfigurationChanged(newConfig: Configuration) { super.onConfigurationChanged(newConfig); updates.onAppearanceChanged() }
    override fun onDestroy() { updates.close(); super.onDestroy() }

    companion object {
        fun incoming(intent: Intent): String? {
            val text = if (intent.action == Intent.ACTION_SEND) intent.getStringExtra(Intent.EXTRA_TEXT) else intent.dataString
            if (text == null) return null
            if (UrlPolicy.appPage(text)) return text
            return Regex("https://17tongyou\\.com/(?:travel/?|t/)[^\\s<>\"，。]*").findAll(text).map { it.value }.firstOrNull(UrlPolicy::appPage)
        }
    }
}

@Composable private fun NativeShell(app: TongyouApplication, external: (String) -> Unit, pendingLink: String?, consumeLink: () -> Unit,
                                    appearance: Appearance, setAppearance: (Appearance) -> Unit) {
    val session by app.session.state.collectAsStateWithLifecycle()
    val activeToken = session.token ?: return
    val navigation = rememberNavController()
    val entry by navigation.currentBackStackEntryAsState()
    val api = remember(activeToken) { app.scopedService(activeToken) }
    val chat: ChatModel = viewModel(key = "chat-${session.token.hashCode()}", factory = viewModelFactory {
        initializer { ChatModel(api, createSavedStateHandle(), prefs = StoredChatPrefs(app.getSharedPreferences("chat_prefs", android.content.Context.MODE_PRIVATE))) }
    })
    var logout by rememberSaveable { mutableStateOf(false) }
    var signingOut by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    // Full-screen pages own the whole display; the floating bar only belongs to the three tabs.
    val inChat = entry?.destination?.route.let { it != null && it !in setOf("home", "ledger", "me") }
    var changingPassword by rememberSaveable { mutableStateOf(false) }
    val forcedPassword = session.account?.get("must_change_password").bool()
    // 改密码后服务端签发新令牌、旧令牌全部作废：交回会话，界面以新令牌重建，不会被踢回登录页。
    if (forcedPassword || changingPassword) ChangePasswordSheet(api, forcedPassword, { changingPassword = false }) { token ->
        changingPassword = false; app.session.replaceToken(activeToken, token); scope.launch { app.session.refresh(app.service) }
    }
    // 收到的行程 / 账本邀请链接：先确认，再在原生里加入并打开。
    var joining by remember { mutableStateOf(false) }
    var linkError by remember { mutableStateOf<String?>(null) }
    val invite = remember(pendingLink) { pendingLink?.let(::parseInviteLink) }
    if (pendingLink != null && invite == InviteLink.Home) LaunchedEffect(pendingLink) { consumeLink() }
    if (invite != null && invite != InviteLink.Home) AlertDialog(onDismissRequest = { if (!joining) { consumeLink(); linkError = null } },
        title = { Text(if (invite is InviteLink.Ledger) "加入这个账本？" else "加入这个行程？") },
        text = { Text(linkError ?: "朋友邀请你一起${if (invite is InviteLink.Ledger) "记账" else "规划行程"}。请确认是认识的人发来的。") },
        dismissButton = { TextButton({ consumeLink(); linkError = null }, enabled = !joining) { Text("取消") } },
        confirmButton = { TextButton({ joining = true; scope.launch {
            try {
                val target = withContext(kotlinx.coroutines.Dispatchers.IO) { acceptInvite(api, invite) }
                consumeLink(); linkError = null
                navigation.navigate(target) { launchSingleTop = true }
            } catch (e: kotlinx.coroutines.CancellationException) { throw e }
            catch (e: Exception) { linkError = e.message ?: "加入失败，请重试" }
            finally { joining = false }
        } }, enabled = !joining) { Text(if (joining) "正在加入…" else "加入") } })
    val haze = remember { dev.chrisbanes.haze.HazeState() }
    val motion = LocalMotion.current
    val route = entry?.destination?.route
    val pill = androidx.compose.foundation.shape.RoundedCornerShape(32.dp)
    fun go(target: String, id: String?) {
        navigation.navigate(when (target) {
            "createTrip" -> "trips/new"
            "trips" -> if (id.isNullOrBlank()) "trips" else "trip/$id"
            else -> target
        }) { launchSingleTop = true }
    }
    Scaffold(modifier = Modifier.safeDrawingPadding(), containerColor = androidx.compose.ui.graphics.Color.Transparent,
        // One floating row, as on the web client: a three-item pill and the AI entry beside it.
        bottomBar = { if (!inChat) Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
            Row(Modifier.weight(1f).height(64.dp).clip(pill).glassBar(haze).border(1.dp, MaterialTheme.colorScheme.outlineVariant, pill).padding(6.dp)) {
                TabItem("旅行", Icons.Outlined.Map, route == "home") { navigation.popBackStack("home", false) }
                TabItem("记账", Icons.Outlined.CreditCard, route == "ledger") { navigation.navigate("ledger") { popUpTo("home"); launchSingleTop = true } }
                TabItem("我的", Icons.Outlined.PersonOutline, route == "me") { navigation.navigate("me") { popUpTo("home"); launchSingleTop = true } }
            }
            Row(Modifier.height(64.dp).clip(pill).background(MaterialTheme.colorScheme.primary)
                .clickable { navigation.navigate("chat") { launchSingleTop = true } }.padding(horizontal = 20.dp).testTag("open-ai"),
                horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Outlined.AutoAwesome, null, tint = MaterialTheme.colorScheme.onPrimary)
                Text("问 AI", color = MaterialTheme.colorScheme.onPrimary, style = MaterialTheme.typography.titleMedium)
            }
        } }, contentWindowInsets = WindowInsets(0)) { padding ->
        // The page is the blur source and runs under the bar; lists pad themselves with LocalBottomInset.
        CompositionLocalProvider(LocalBottomInset provides padding.calculateBottomPadding()) {
        NavHost(navigation, startDestination = "home",
            modifier = Modifier.padding(top = padding.calculateTopPadding()).then(if (glassAvailable()) Modifier.hazeSource(haze) else Modifier),
            enterTransition = { if (motion) fadeIn(tween(220)) + slideInHorizontally(tween(260)) { it / 10 } else androidx.compose.animation.EnterTransition.None },
            exitTransition = { if (motion) fadeOut(tween(160)) else androidx.compose.animation.ExitTransition.None },
            popEnterTransition = { if (motion) fadeIn(tween(220)) else androidx.compose.animation.EnterTransition.None },
            popExitTransition = { if (motion) fadeOut(tween(160)) + slideOutHorizontally(tween(260)) { it / 10 } else androidx.compose.animation.ExitTransition.None }) {
            composable("home") {
                HomeScreen(api, session.account, { prompt -> chat.open(prompt = prompt); navigation.navigate("chat") { launchSingleTop = true } },
                    ::go, external)
            }
            composable("chat") { ChatScreen(chat, api, { navigation.popBackStack() }, external,
                { navigation.navigate("history") { launchSingleTop = true } }) { id -> navigation.navigate("trip/$id") { launchSingleTop = true } } }
            composable("trips") { TripsScreen(api, false, { navigation.popBackStack() }) { id -> navigation.navigate("trip/$id") { launchSingleTop = true } } }
            composable("trips/new") { TripsScreen(api, true, { navigation.popBackStack() }) { id -> navigation.navigate("trip/$id") { popUpTo("home"); launchSingleTop = true } } }
            composable("trip/{id}?notification={notification}&day={day}&poll={poll}", arguments = listOf(
                navArgument("notification") { defaultValue = "" }, navArgument("day") { type = NavType.IntType; defaultValue = 0 }, navArgument("poll") { defaultValue = "" }
            )) { stack -> TripDetailScreen(api, stack.arguments?.getString("id").orEmpty(), session.account?.get("username").string(),
                { navigation.popBackStack() }, external, notification = if (stack.arguments?.getString("notification") == "poll") TripNotification(
                    stack.arguments?.getString("id").orEmpty(), stack.arguments?.getInt("day")?.takeIf { it > 0 }, stack.arguments?.getString("poll")?.ifBlank { null }) else null) { navigation.navigate("ledger") { launchSingleTop = true } } }
            composable("friends") { FriendsScreen(api) { navigation.popBackStack() } }
            composable("history") { HistoryScreen(api, { navigation.popBackStack() }) { id -> chat.open(id); navigation.navigate("chat") { popUpTo("home"); launchSingleTop = true } } }
            composable("notifications") { NotificationsScreen(api, { navigation.popBackStack() }) { kind, id, poll ->
                when (kind) {
                    "friends" -> navigation.navigate("friends") { launchSingleTop = true }
                    "trip" -> if (id.isNotBlank()) navigation.navigate(poll?.route() ?: "trip/$id") { launchSingleTop = true }
                }
            } }
            composable("profile") { ProfileScreen(api, { navigation.popBackStack() }, { changingPassword = true }) { scope.launch { app.session.refresh(app.service) } } }
            composable("memory") { MemoryScreen(api) { navigation.popBackStack() } }
            composable("skills") { SkillsScreen(api) { navigation.popBackStack() } }
            composable("connectors") { ConnectorsScreen(api) { navigation.popBackStack() } }
            composable("support") { SupportScreen(api, { navigation.popBackStack() }) }
            composable("admin") { AdminScreen(api, { navigation.popBackStack() }) { uid, name -> navigation.navigate("support/$uid/$name") { launchSingleTop = true } } }
            composable("support/{uid}/{name}") { stack -> SupportScreen(api, { navigation.popBackStack() }, "@" + stack.arguments?.getString("name").orEmpty(),
                "admin/support/${stack.arguments?.getString("uid").orEmpty()}/messages") }
            composable("ledger") { LedgerScreen(api) { id -> navigation.navigate("ledger/$id") { launchSingleTop = true } } }
            composable("ledger/{id}") { stack -> LedgerDetailScreen(api, stack.arguments?.getString("id").orEmpty()) { navigation.popBackStack() } }
            composable("me") {
                Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp).padding(bottom = LocalBottomInset.current), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                    Text("我的", style = MaterialTheme.typography.headlineMedium)
                    GlassCard(Modifier.fillMaxWidth()) {
                        val name = session.account?.get("display_name").string().ifBlank { session.account?.get("username").string().ifBlank { "旅行朋友" } }
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                            Box(Modifier.size(56.dp).clip(androidx.compose.foundation.shape.CircleShape).background(MaterialTheme.colorScheme.primary), contentAlignment = Alignment.Center) {
                                Text(name.take(1), color = MaterialTheme.colorScheme.onPrimary, style = MaterialTheme.typography.titleLarge)
                                TravelApi.media(session.account?.get("avatar_url").string().orEmpty())?.let {
                                    coil.compose.AsyncImage(it, null, Modifier.matchParentSize(), contentScale = androidx.compose.ui.layout.ContentScale.Crop)
                                }
                            }
                            Column {
                                Text(name, style = MaterialTheme.typography.titleLarge)
                                Text("@" + session.account?.get("username").string() + if (session.account?.get("is_admin").bool() == true) " · 管理员" else "",
                                    color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyMedium)
                            }
                        }
                    }
                    GlassCard(Modifier.fillMaxWidth()) {
                        listOf("好友" to "friends", "历史对话" to "history", "通知与公告" to "notifications", "帮助与反馈" to "support").forEachIndexed { i, (label, to) ->
                            if (i > 0) HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                            MenuRow(label) { go(to, null) }
                        }
                    }
                    Text("外观", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    GlassCard(Modifier.fillMaxWidth()) {
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Appearance.entries.forEach { option ->
                                FilterChip(appearance == option, { setAppearance(option) }, { Text(option.label) }, Modifier.weight(1f))
                            }
                        }
                    }
                    Text("更多工具与设置", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    GlassCard(Modifier.fillMaxWidth()) {
                        (listOf("个人资料" to "profile", "旅行偏好与记忆" to "memory", "技能" to "skills", "连接" to "connectors") +
                            if (session.account?.get("is_admin").bool()) listOf("管理" to "admin") else emptyList()).forEachIndexed { i, (label, to) ->
                            if (i > 0) HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                            MenuRow(label) { go(to, null) }
                        }
                    }
                    TextButton({ logout = true }, enabled = !signingOut, colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error)) { Text(if (signingOut) "正在退出…" else "退出登录") }
                    Text("17同游 ${BuildConfig.VERSION_NAME}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
        }
    }
    if (logout) AlertDialog(onDismissRequest = { logout = false }, title = { Text("退出当前账号？") },
        confirmButton = { TextButton({ logout = false; signingOut = true; scope.launch { try { app.session.logout(app.service) } finally { signingOut = false } } }) { Text("退出登录") } },
        dismissButton = { TextButton({ logout = false }) { Text("取消") } })
}

@Composable private fun RowScope.TabItem(label: String, icon: ImageVector, selected: Boolean, onClick: () -> Unit) {
    val tint = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant
    Column(Modifier.weight(1f).fillMaxHeight().clip(androidx.compose.foundation.shape.RoundedCornerShape(26.dp))
        .background(if (selected) MaterialTheme.colorScheme.primary.copy(alpha = .10f) else androidx.compose.ui.graphics.Color.Transparent)
        .clickable(onClick = onClick), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        Icon(icon, null, tint = tint, modifier = Modifier.size(22.dp))
        Text(label, color = tint, style = MaterialTheme.typography.labelMedium)
    }
}

@Composable private fun MenuRow(label: String, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(label, Modifier.weight(1f), style = MaterialTheme.typography.bodyLarge)
        Text("›", color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.titleLarge)
    }
}
