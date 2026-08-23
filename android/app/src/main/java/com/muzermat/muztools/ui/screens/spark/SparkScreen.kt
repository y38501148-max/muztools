package com.muzermat.muztools.ui.screens.spark

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.muzermat.muztools.data.model.DouyinFriend
import com.muzermat.muztools.data.model.SparkTarget
import com.muzermat.muztools.ui.components.SectionHeader
import com.muzermat.muztools.ui.components.StatusBadge

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SparkScreen(viewModel: SparkViewModel) {
    val uiState by viewModel.uiState.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }
    val uriHandler = LocalUriHandler.current

    var showCookieDialog by remember { mutableStateOf(false) }
    var showCookieGuideDialog by remember { mutableStateOf(false) }
    var cookieInput by remember { mutableStateOf("") }
    var showAddFriendDialog by remember { mutableStateOf(false) }
    var editingTarget by remember { mutableStateOf<SparkTarget?>(null) }

    LaunchedEffect(Unit) { viewModel.loadData() }
    LaunchedEffect(viewModel.messageFlow) {
        viewModel.messageFlow.collect { snackbarHostState.showSnackbar(it) }
    }


    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            TopAppBar(
                title = { Text("抖音火花自动化", fontWeight = FontWeight.Bold, fontSize = 20.sp) },
                actions = {
                    StatusBadge(
                        status = if (uiState.session.valid) "已登录" else "未登录",
                        modifier = Modifier.padding(end = 16.dp)
                    )
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background)
            )
        },
        floatingActionButton = {
            FloatingActionButton(
                onClick = { viewModel.loadData(isRefresh = true) },
                shape = RoundedCornerShape(16.dp)
            ) { Icon(Icons.Default.Refresh, contentDescription = "刷新状态") }
        }
    ) { paddingValues ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(paddingValues),
            contentPadding = PaddingValues(top = 4.dp, bottom = 88.dp)
        ) {
            item {
                SectionHeader(title = "抖音账号与会话")
                Card(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
                    shape = RoundedCornerShape(20.dp),
                    elevation = CardDefaults.cardElevation(defaultElevation = 1.5.dp)
                ) {
                    Column(modifier = Modifier.padding(18.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Box(
                                modifier = Modifier.size(44.dp).clip(CircleShape).background(
                                    if (uiState.session.valid) Color(0xFFE65100).copy(alpha = 0.12f)
                                    else MaterialTheme.colorScheme.surfaceVariant
                                ),
                                contentAlignment = Alignment.Center
                            ) {
                                Icon(
                                    Icons.Default.ElectricBolt,
                                    contentDescription = null,
                                    tint = if (uiState.session.valid) Color(0xFFE65100) else MaterialTheme.colorScheme.outline
                                )
                            }
                            Spacer(Modifier.width(12.dp))
                            Column(Modifier.weight(1f)) {
                                Text(
                                    if (uiState.session.valid) "已绑定: ${uiState.session.nickname ?: "抖音用户"}" else "未导入抖音 Cookie",
                                    fontWeight = FontWeight.Bold
                                )
                                Text(
                                    if (uiState.session.valid) "账号会话可用于读取好友与自动续火花" else "请从已登录的抖音网页版导出 Cookie",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                        }
                        Spacer(Modifier.height(16.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            Button(
                                onClick = { cookieInput = ""; showCookieDialog = true },
                                enabled = true,
                                modifier = Modifier.weight(1f)
                            ) {
                                Icon(Icons.Default.FileUpload, null, Modifier.size(18.dp))
                                Spacer(Modifier.width(6.dp))
                                Text("导入 Cookie")
                            }
                            OutlinedButton(
                                onClick = { showCookieGuideDialog = true },
                                modifier = Modifier.weight(1f)
                            ) {
                                Icon(Icons.Default.HelpOutline, null, Modifier.size(18.dp))
                                Spacer(Modifier.width(6.dp))
                                Text("获取教程")
                            }
                        }
                    }
                }
            }

            item {
                Spacer(Modifier.height(14.dp))
                SectionHeader(title = "自动化任务设置")
                Card(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
                    shape = RoundedCornerShape(20.dp),
                    elevation = CardDefaults.cardElevation(defaultElevation = 1.5.dp)
                ) {
                    Column(Modifier.padding(18.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text("自动续火花", fontWeight = FontWeight.SemiBold)
                                Text(
                                    "到达设定时间后自动执行，服务短暂重启也会补执行",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                            Switch(
                                checked = uiState.config.enabled,
                                onCheckedChange = viewModel::toggleAutoSpark,
                                enabled = uiState.session.valid && !uiState.isSavingConfig
                            )
                        }
                        HorizontalDivider(Modifier.padding(vertical = 12.dp))
                        val lastAutoRun = uiState.session.douyin?.lastAutoRun.orEmpty()
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text("最近自动执行", fontWeight = FontWeight.Medium)
                                Text(
                                    if (lastAutoRun.isBlank()) "尚无自动执行记录" else formatSparkTimestamp(lastAutoRun),
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                            StatusBadge(status = if (lastAutoRun.isBlank()) "等待执行" else "已执行")
                        }
                        HorizontalDivider(Modifier.padding(vertical = 12.dp))
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text("执行时间", fontWeight = FontWeight.Medium)
                                Text("每天 ${String.format("%02d:00", uiState.config.hour)}", style = MaterialTheme.typography.bodySmall)
                            }
                            Text(String.format("%02d:00", uiState.config.hour), fontWeight = FontWeight.Bold)
                        }
                        Slider(
                            value = uiState.config.hour.toFloat(),
                            onValueChange = { viewModel.setRunHour(it.toInt()) },
                            valueRange = 0f..23f,
                            steps = 22,
                            enabled = uiState.session.valid
                        )
                        OutlinedTextField(
                            value = uiState.config.defaultMessage,
                            onValueChange = viewModel::setDefaultMessage,
                            label = { Text("标准模式默认文案") },
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth()
                        )
                        Spacer(Modifier.height(12.dp))
                        Button(
                            onClick = { viewModel.updateConfig() },
                            enabled = uiState.session.valid && !uiState.isSavingConfig,
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            if (uiState.isSavingConfig) {
                                CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp, color = MaterialTheme.colorScheme.onPrimary)
                                Spacer(Modifier.width(8.dp))
                            }
                            Text(if (uiState.isSavingConfig) "正在保存..." else "保存自动化配置")
                        }
                    }
                }
            }

            item {
                Spacer(Modifier.height(14.dp))
                SectionHeader(
                    title = "续火花好友名单",
                    action = {
                        TextButton(
                            onClick = { showAddFriendDialog = true },
                            enabled = uiState.session.valid
                        ) {
                            Icon(Icons.Default.PersonAdd, null, Modifier.size(18.dp))
                            Spacer(Modifier.width(4.dp))
                            Text("从好友添加")
                        }
                    }
                )
            }

            if (uiState.config.targets.isEmpty()) {
                item {
                    Card(
                        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
                        shape = RoundedCornerShape(18.dp)
                    ) {
                        Text(
                            if (uiState.session.valid) "暂无续火花好友，请从好友列表中添加" else "请先导入有效的抖音 Cookie",
                            modifier = Modifier.fillMaxWidth().padding(28.dp),
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
            } else {
                items(uiState.config.targets, key = { it.identityKey() }) { target ->
                    SparkTargetCard(
                        target = target,
                        defaultMessage = uiState.config.defaultMessage,
                        onEdit = { editingTarget = target },
                        onDelete = { viewModel.removeTarget(target) }
                    )
                }
            }

            item {
                Spacer(Modifier.height(20.dp))
                FilledTonalButton(
                    onClick = viewModel::runSparkNow,
                    enabled = !uiState.isRunningSpark && uiState.session.valid && uiState.config.targets.isNotEmpty(),
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp).height(48.dp)
                ) {
                    if (uiState.isRunningSpark) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                    else Icon(Icons.Default.FlashOn, null, Modifier.size(20.dp))
                    Spacer(Modifier.width(8.dp))
                    Text(if (uiState.isRunningSpark) "正在执行续火花..." else "立即执行续火花", fontWeight = FontWeight.Bold)
                }
            }
        }
    }

    if (showAddFriendDialog) {
        AddFriendDialog(
            uiState = uiState,
            onQueryChange = viewModel::setFriendSearchQuery,
            onRefresh = { viewModel.loadFriends(refresh = true) },
            onAdd = viewModel::addTarget,
            onDismiss = { showAddFriendDialog = false; viewModel.setFriendSearchQuery("") }
        )
    }

    editingTarget?.let { target ->
        EditTargetDialog(
            target = target,
            defaultMessage = uiState.config.defaultMessage,
            onSave = { mode, message -> viewModel.updateTarget(target, mode, message); editingTarget = null },
            onDismiss = { editingTarget = null }
        )
    }

    if (showCookieGuideDialog) {
        AlertDialog(
            onDismissRequest = { showCookieGuideDialog = false },
            title = { Text("获取抖音 Cookie 教程") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("1. 在电脑 Chrome 或 Edge 中安装 Cookie-Editor 扩展。")
                    Text("2. 打开 www.douyin.com/chat，完成登录及安全验证。")
                    Text("3. 点击 Cookie-Editor，选择 Export → JSON。")
                    Text("4. 复制完整 JSON 数组，回到 MuzTool 导入。")
                    Text("Cookie 等同于登录凭证，请勿截图或转发给其他人。", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                }
            },
            confirmButton = {
                TextButton(onClick = { uriHandler.openUri("https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm") }) {
                    Text("安装 Cookie-Editor")
                }
            },
            dismissButton = {
                TextButton(onClick = { showCookieGuideDialog = false; cookieInput = ""; showCookieDialog = true }) { Text("我已获取，去导入") }
            }
        )
    }

    if (showCookieDialog) {
        AlertDialog(
            onDismissRequest = { if (!uiState.isSubmittingCookie) showCookieDialog = false },
            title = { Text("导入抖音 Cookie") },
            text = {
                OutlinedTextField(
                    value = cookieInput,
                    onValueChange = { cookieInput = it },
                    label = { Text("Cookie JSON 内容") },
                    minLines = 4,
                    maxLines = 8,
                    modifier = Modifier.fillMaxWidth()
                )
            },
            confirmButton = {
                Button(
                    onClick = { viewModel.submitCookies(cookieInput); showCookieDialog = false },
                    enabled = !uiState.isSubmittingCookie && cookieInput.isNotBlank()
                ) { Text("导入") }
            },
            dismissButton = { TextButton(onClick = { showCookieDialog = false }) { Text("取消") } }
        )
    }
}

@Composable
private fun AddFriendDialog(
    uiState: SparkUiState,
    onQueryChange: (String) -> Unit,
    onRefresh: () -> Unit,
    onAdd: (DouyinFriend) -> Unit,
    onDismiss: () -> Unit
) {
    val addedConversations = uiState.config.targets.map { it.identityKey() }.toSet()
    val filtered = uiState.friends.filter { it.name.contains(uiState.friendSearchQuery, ignoreCase = true) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("从抖音好友中添加") },
        text = {
            Column(Modifier.fillMaxWidth()) {
                OutlinedTextField(
                    value = uiState.friendSearchQuery,
                    onValueChange = onQueryChange,
                    label = { Text("搜索好友") },
                    leadingIcon = { Icon(Icons.Default.Search, null) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )
                Row(
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Text(
                        when {
                            uiState.isLoadingFriends -> "正在读取好友列表..."
                            uiState.friendError.isNotBlank() -> uiState.friendError
                            else -> "已缓存 ${uiState.friends.size} 位好友"
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = if (uiState.friendError.isNotBlank()) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    TextButton(onClick = onRefresh, enabled = !uiState.isLoadingFriends) {
                        Icon(Icons.Default.Refresh, null, Modifier.size(16.dp))
                        Text("主动刷新")
                    }
                }
                if (uiState.isLoadingFriends && uiState.friends.isEmpty()) {
                    Box(Modifier.fillMaxWidth().height(180.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
                } else {
                    LazyColumn(Modifier.fillMaxWidth().heightIn(max = 360.dp)) {
                        items(filtered, key = { it.identityKey() }) { friend ->
                            val added = friend.identityKey() in addedConversations
                            Row(
                                modifier = Modifier.fillMaxWidth().clickable(enabled = !added) { onAdd(friend) }.padding(vertical = 10.dp),
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Box(
                                    Modifier.size(36.dp).clip(CircleShape).background(MaterialTheme.colorScheme.primaryContainer),
                                    contentAlignment = Alignment.Center
                                ) {
                                    Icon(
                                        if (friend.conversationType == "group") Icons.Default.Groups else Icons.Default.Person,
                                        null,
                                        Modifier.size(20.dp)
                                    )
                                }
                                Spacer(Modifier.width(10.dp))
                                Column(Modifier.weight(1f)) {
                                    Text(friend.name, maxLines = 1)
                                    Text(
                                        if (friend.conversationType == "group") "群聊" else "好友",
                                        style = MaterialTheme.typography.labelSmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant
                                    )
                                }
                                Text(if (added) "已添加" else "添加", color = if (added) MaterialTheme.colorScheme.outline else MaterialTheme.colorScheme.primary)
                            }
                            HorizontalDivider()
                        }
                        if (filtered.isEmpty()) {
                            item { Text("没有匹配的好友", Modifier.fillMaxWidth().padding(24.dp), color = MaterialTheme.colorScheme.onSurfaceVariant) }
                        }
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("完成") } }
    )
}

@Composable
private fun EditTargetDialog(
    target: SparkTarget,
    defaultMessage: String,
    onSave: (String, String) -> Unit,
    onDismiss: () -> Unit
) {
    var mode by remember(target) { mutableStateOf(target.resolvedMode()) }
    var message by remember(target) { mutableStateOf(target.message.orEmpty()) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("编辑 ${target.name}") },
        text = {
            Column {
                Row(
                    Modifier.fillMaxWidth().clickable { mode = "standard" }.padding(vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    RadioButton(selected = mode == "standard", onClick = { mode = "standard" })
                    Column {
                        Text("标准模式", fontWeight = FontWeight.Medium)
                        Text("发送全局文案：$defaultMessage", style = MaterialTheme.typography.bodySmall)
                    }
                }
                Row(
                    Modifier.fillMaxWidth().clickable { mode = "custom" }.padding(vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    RadioButton(selected = mode == "custom", onClick = { mode = "custom" })
                    Text("自定义模式", fontWeight = FontWeight.Medium)
                }
                if (mode == "custom") {
                    OutlinedTextField(
                        value = message,
                        onValueChange = { message = it },
                        label = { Text("该好友专属发送内容") },
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            }
        },
        confirmButton = {
            Button(onClick = { onSave(mode, message) }, enabled = mode != "custom" || message.isNotBlank()) { Text("保存") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } }
    )
}

@Composable
private fun SparkTargetCard(
    target: SparkTarget,
    defaultMessage: String,
    onEdit: () -> Unit,
    onDelete: () -> Unit
) {
    val mode = target.resolvedMode()
    Card(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
        shape = RoundedCornerShape(16.dp),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
    ) {
        Row(Modifier.fillMaxWidth().padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier.size(38.dp).clip(CircleShape).background(MaterialTheme.colorScheme.primaryContainer),
                contentAlignment = Alignment.Center
            ) {
                Icon(
                    if (target.conversationType == "group") Icons.Default.Groups else Icons.Default.Person,
                    null,
                    Modifier.size(20.dp),
                    tint = MaterialTheme.colorScheme.primary
                )
            }
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    if (target.conversationType == "group") "${target.name} · 群聊" else target.name,
                    fontWeight = FontWeight.Bold
                )
                Text(
                    if (mode == "custom") "自定义模式：${target.message.orEmpty()}" else "标准模式：$defaultMessage",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2
                )
            }
            IconButton(onClick = onEdit) { Icon(Icons.Default.Edit, contentDescription = "编辑") }
            IconButton(onClick = onDelete) { Icon(Icons.Default.DeleteOutline, contentDescription = "删除", tint = MaterialTheme.colorScheme.error) }
        }
    }
}

private fun formatSparkTimestamp(value: String): String =
    value.replace("T", " ").substringBefore("+").substringBeforeLast(":")
