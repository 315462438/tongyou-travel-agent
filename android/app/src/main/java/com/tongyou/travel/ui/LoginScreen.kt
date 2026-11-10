package com.tongyou.travel.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.tongyou.travel.data.TravelService
import com.tongyou.travel.session.Session
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

@Composable fun LoginScreen(session: Session, api: TravelService) {
    var register by rememberSaveable { mutableStateOf(false) }
    var name by rememberSaveable { mutableStateOf("") }
    // Password is intentionally not serialized into the Activity saved state.
    var password by remember { mutableStateOf("") }
    var invite by rememberSaveable { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    Box(Modifier.fillMaxSize().safeDrawingPadding().imePadding(), contentAlignment = Alignment.Center) {
        Column(Modifier.widthIn(max = 480.dp).fillMaxWidth().verticalScroll(rememberScrollState()).padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(24.dp)) {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("17同游", style = MaterialTheme.typography.displaySmall)
                Text("一起规划，一起出发", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            GlassCard {
                Row {
                    FilterChip(!register, { register = false }, { Text("登录") }, enabled = !busy)
                    Spacer(Modifier.width(12.dp))
                    FilterChip(register, { register = true }, { Text("邀请码注册") }, enabled = !busy)
                }
                OutlinedTextField(name, { name = it }, Modifier.fillMaxWidth(), label = { Text("用户名") }, singleLine = true, enabled = !busy)
                OutlinedTextField(password, { password = it }, Modifier.fillMaxWidth(), label = { Text("密码") }, singleLine = true,
                    visualTransformation = PasswordVisualTransformation(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password), enabled = !busy)
                if (register) {
                    OutlinedTextField(invite, { invite = it }, Modifier.fillMaxWidth(), label = { Text("邀请码") }, singleLine = true, enabled = !busy)
                    Text("向邀请你的朋友获取邀请码。", style = MaterialTheme.typography.bodySmall)
                }
                error?.let { ErrorNotice(it) }
                Button(onClick = {
                    busy = true; error = null
                    scope.launch {
                        try { session.authenticate(api, name, password, if (register) invite.trim() else null); password = "" }
                        catch (e: CancellationException) { throw e }
                        catch (e: Exception) { error = e.message ?: "登录失败，请重试" }
                        finally { busy = false }
                    }
                }, enabled = !busy && name.isNotBlank() && password.isNotEmpty() && (!register || invite.isNotBlank()), modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp)) {
                    Text(if (busy) "正在连接…" else if (register) "注册并登录" else "登录 17同游")
                }
            }
        }
    }
}
