package com.muzermat.muztools.ui.screens.tibo

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.OpenInNew
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TiboScreen(viewModel: TiboViewModel) {
    val state by viewModel.uiState.collectAsState()
    val uriHandler = LocalUriHandler.current
    val snackbarHostState = remember { SnackbarHostState() }
    LaunchedEffect(viewModel.messageFlow) {
        viewModel.messageFlow.collect { snackbarHostState.showSnackbar(it) }
    }
    LaunchedEffect(Unit) { viewModel.load() }

    if (state.showCookieDialog) {
        TiboCookieDialog(
            isSubmitting = state.isSubmittingCookie,
            onDismiss = viewModel::dismissCookieDialog,
            onSubmit = viewModel::submitXCookie
        )
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            TopAppBar(
                title = { Text("Tibo Reset 监测", fontWeight = FontWeight.Bold) },
                actions = { IconButton(onClick = viewModel::load) { Icon(Icons.Default.Refresh, "刷新缓存") } }
            )
        }
    ) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(padding),
            contentPadding = PaddingValues(16.dp, 8.dp, 16.dp, 88.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            item {
                Card(shape = RoundedCornerShape(18.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(16.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = androidx.compose.ui.Alignment.CenterVertically
                    ) {
                        Column(Modifier.weight(1f).padding(end = 12.dp)) {
                            Text("Tibo 系统推送", fontWeight = FontWeight.Bold)
                            Text(
                                if (state.enabled) "已开启：发现新的 reset 推特时发送通知" else "已关闭：历史仍可查看，但不会发送通知",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        Switch(checked = state.enabled, onCheckedChange = viewModel::setEnabled, enabled = !state.isUpdating)
                    }
                }
            }
            item {
                Card(shape = RoundedCornerShape(18.dp)) {
                    Column(Modifier.padding(16.dp)) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = androidx.compose.ui.Alignment.CenterVertically
                        ) {
                            Column(Modifier.weight(1f).padding(end = 12.dp)) {
                                Text("X 登录 Cookie", fontWeight = FontWeight.Bold)
                                Text(
                                    if (state.xConnected) {
                                        "已导入：监测将通过你的 Cookie 拉取 Tibo 的完整时间线，覆盖最近一周的全部推文。"
                                    } else {
                                        "未导入：仅能匿名监测最近几条推文，较早的 reset 推文可能被错过；导入自己的 X Cookie 后可覆盖完整一周。"
                                    },
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                            Button(onClick = viewModel::showCookieDialog, enabled = !state.isSubmittingCookie) {
                                Text(if (state.xConnected) "更换" else "导入")
                            }
                        }
                        if (state.xConnected) {
                            Spacer(Modifier.height(10.dp))
                            OutlinedButton(onClick = viewModel::removeXCookie, modifier = Modifier.fillMaxWidth()) {
                                Text("移除已保存的 Cookie")
                            }
                        }
                    }
                }
            }
            item {
                Card(shape = RoundedCornerShape(18.dp)) {
                    Column(Modifier.padding(16.dp)) {
                        Text("历史推特缓存", fontWeight = FontWeight.Bold)
                        Text("后端每小时检查过去一周的推文，优先使用已导入的 X Cookie 拉取完整时间线；仅标记并保留包含 reset 的记录，最多 100 条。", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Spacer(Modifier.height(8.dp))
                        Text("最近检查：${formatTiboTime(state.lastChecked).ifBlank { "尚未检查" }}", style = MaterialTheme.typography.labelSmall)
                    }
                }
            }
            if (state.isLoading && state.items.isEmpty()) {
                item { Box(Modifier.fillMaxWidth().padding(36.dp)) { CircularProgressIndicator() } }
            } else if (state.error.isNotBlank()) {
                item { Text(state.error, color = MaterialTheme.colorScheme.error) }
            } else if (state.items.isEmpty()) {
                item { Text("暂时没有与 reset 有关的历史推特缓存", color = MaterialTheme.colorScheme.onSurfaceVariant) }
            } else {
                items(state.items, key = { it.id }) { post ->
                    Card(
                        modifier = Modifier.fillMaxWidth().clickable(enabled = post.url.isNotBlank()) { uriHandler.openUri(post.url) },
                        shape = RoundedCornerShape(18.dp)
                    ) {
                        Column(Modifier.padding(16.dp)) {
                            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                                Text("@thsottiaux", fontWeight = FontWeight.Bold)
                                Text(formatTiboTime(post.createdAt), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            Spacer(Modifier.height(10.dp))
                            Text(post.text, style = MaterialTheme.typography.bodyMedium)
                            Spacer(Modifier.height(10.dp))
                            Row { Icon(Icons.Default.OpenInNew, null, Modifier.size(16.dp)); Spacer(Modifier.width(5.dp)); Text("查看原推特", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary) }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun TiboCookieDialog(
    isSubmitting: Boolean,
    onDismiss: () -> Unit,
    onSubmit: (String) -> Unit
) {
    var cookieText by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = { if (!isSubmitting) onDismiss() },
        title = { Text("导入 X Cookie") },
        text = {
            Column {
                Text(
                    "登录 x.com 后，用 Cookie-Editor 等浏览器扩展导出完整 Cookie（JSON 数组，或包含 auth_token 与 ct0 的 Cookie 字符串均可）。Cookie 等同登录凭证，仅会加密保存在服务器上，用于以你的身份读取 Tibo 的公开时间线。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    value = cookieText,
                    onValueChange = { cookieText = it },
                    modifier = Modifier.fillMaxWidth().heightIn(min = 140.dp),
                    placeholder = { Text("粘贴 Cookie JSON 数组或 auth_token=...; ct0=...") },
                    enabled = !isSubmitting
                )
            }
        },
        confirmButton = {
            Button(onClick = { onSubmit(cookieText) }, enabled = !isSubmitting && cookieText.isNotBlank()) {
                if (isSubmitting) {
                    CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                    Spacer(Modifier.width(6.dp))
                }
                Text("确认导入")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss, enabled = !isSubmitting) { Text("取消") }
        }
    )
}

private fun formatTiboTime(value: String): String = value.replace("T", " ").substringBefore("+")
