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
    LaunchedEffect(Unit) { viewModel.load() }

    Scaffold(
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
                        Text("历史推特缓存", fontWeight = FontWeight.Bold)
                        Text("后端每两小时检查一次，仅保留包含 reset 的推特，最多 100 条；历史查看不受推送开关影响。", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
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

private fun formatTiboTime(value: String): String = value.replace("T", " ").substringBefore("+")
