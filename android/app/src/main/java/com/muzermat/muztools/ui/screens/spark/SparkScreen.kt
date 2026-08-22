package com.muzermat.muztools.ui.screens.spark

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.muzermat.muztools.data.model.SparkTarget
import com.muzermat.muztools.ui.components.SectionHeader
import com.muzermat.muztools.ui.components.StatusBadge

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SparkScreen(
    viewModel: SparkViewModel
) {
    val uiState by viewModel.uiState.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }

    var showCookieDialog by remember { mutableStateOf(false) }
    var cookieInput by remember { mutableStateOf("") }

    var showAddTargetDialog by remember { mutableStateOf(false) }
    var targetNameInput by remember { mutableStateOf("") }
    var targetMsgInput by remember { mutableStateOf("") }

    LaunchedEffect(Unit) {
        viewModel.loadData()
    }

    LaunchedEffect(viewModel.messageFlow) {
        viewModel.messageFlow.collect { msg ->
            snackbarHostState.showSnackbar(msg)
        }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        text = "抖音火花自动化",
                        style = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.Bold)
                    )
                },
                actions = {
                    StatusBadge(
                        status = if (uiState.session.valid) "已登录" else "未登录",
                        modifier = Modifier.padding(end = 16.dp)
                    )
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background
                )
            )
        },
        floatingActionButton = {
            FloatingActionButton(
                onClick = { viewModel.loadData(isRefresh = true) },
                containerColor = MaterialTheme.colorScheme.primaryContainer,
                contentColor = MaterialTheme.colorScheme.onPrimaryContainer
            ) {
                Icon(
                    imageVector = Icons.Default.Refresh,
                    contentDescription = "刷新状态"
                )
            }
        }
    ) { paddingValues ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues),
            contentPadding = PaddingValues(bottom = 80.dp)
        ) {
            // 账号授权 / Cookie 状态卡片
            item {
                SectionHeader(title = "抖音账号与会话")
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 4.dp),
                    shape = RoundedCornerShape(16.dp),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f)
                    )
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            Column {
                                Text(
                                    text = if (uiState.session.valid) "已绑定: ${uiState.session.nickname ?: "抖音用户"}" else "未登录抖音 Cookie",
                                    style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Bold)
                                )
                                Spacer(modifier = Modifier.height(2.dp))
                                Text(
                                    text = if (uiState.session.valid) "过期时间: ${uiState.session.expireTime ?: "长期有效"}" else "请粘贴包含 Session 信息的 Cookie JSON",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                            Button(
                                onClick = {
                                    cookieInput = ""
                                    showCookieDialog = true
                                },
                                shape = RoundedCornerShape(10.dp)
                            ) {
                                Text(if (uiState.session.valid) "更新 Cookie" else "导入 Cookie")
                            }
                        }
                    }
                }
            }

            // 定时开关与全局默认文案
            item {
                Spacer(modifier = Modifier.height(12.dp))
                SectionHeader(title = "定时与消息配置")
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 4.dp),
                    shape = RoundedCornerShape(16.dp),
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                    elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    text = "开启每日定时续火花",
                                    style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Bold)
                                )
                                Text(
                                    text = "每天 ${uiState.config.hour}:00 自动向目标好友发送消息",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                            Switch(
                                checked = uiState.config.enabled,
                                onCheckedChange = { viewModel.toggleAutoSpark(it) }
                            )
                        }

                        Spacer(modifier = Modifier.height(16.dp))

                        OutlinedTextField(
                            value = uiState.config.defaultMessage,
                            onValueChange = { viewModel.setDefaultMessage(it) },
                            label = { Text("全局默认续火花消息") },
                            singleLine = true,
                            shape = RoundedCornerShape(10.dp),
                            modifier = Modifier.fillMaxWidth()
                        )

                        Spacer(modifier = Modifier.height(8.dp))
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.End
                        ) {
                            TextButton(
                                onClick = { viewModel.updateConfig() },
                                enabled = !uiState.isSavingConfig
                            ) {
                                Text("保存默认消息")
                            }
                        }
                    }
                }
            }

            // 目标好友列表
            item {
                Spacer(modifier = Modifier.height(12.dp))
                SectionHeader(
                    title = "火花好友列表",
                    action = {
                        IconButton(onClick = {
                            targetNameInput = ""
                            targetMsgInput = ""
                            showAddTargetDialog = true
                        }) {
                            Icon(imageVector = Icons.Default.Add, contentDescription = "添加好友")
                        }
                    }
                )
            }

            if (uiState.config.targets.isEmpty()) {
                item {
                    Card(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 16.dp, vertical = 6.dp),
                        shape = RoundedCornerShape(16.dp),
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.3f)
                        )
                    ) {
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(24.dp),
                            contentAlignment = Alignment.Center
                        ) {
                            Text(
                                text = "暂无配置的目标好友，点击右上角 + 添加",
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                }
            } else {
                items(uiState.config.targets) { target ->
                    SparkTargetCard(
                        target = target,
                        defaultMessage = uiState.config.defaultMessage,
                        onDelete = { viewModel.removeTarget(target) }
                    )
                }
            }

            // 立即执行按钮
            item {
                Spacer(modifier = Modifier.height(24.dp))
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp)
                ) {
                    Button(
                        onClick = { viewModel.runSparkNow() },
                        enabled = !uiState.isRunningSpark,
                        shape = RoundedCornerShape(14.dp),
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(52.dp)
                    ) {
                        if (uiState.isRunningSpark) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(22.dp),
                                strokeWidth = 2.dp,
                                color = MaterialTheme.colorScheme.onPrimary
                            )
                            Spacer(modifier = Modifier.width(10.dp))
                            Text("正在发送火花消息...")
                        } else {
                            Icon(imageVector = Icons.Default.ElectricBolt, contentDescription = null)
                            Spacer(modifier = Modifier.width(8.dp))
                            Text("立即执行续火花", fontSize = 16.sp, fontWeight = FontWeight.Bold)
                        }
                    }
                }
            }
        }
    }

    // Cookie 粘贴弹窗
    if (showCookieDialog) {
        AlertDialog(
            onDismissRequest = { if (!uiState.isSubmittingCookie) showCookieDialog = false },
            title = { Text("粘贴抖音 Cookie") },
            text = {
                Column {
                    Text(
                        text = "请从浏览器抓取抖音网页版 Cookie JSON 或字符串：",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Spacer(modifier = Modifier.height(12.dp))
                    OutlinedTextField(
                        value = cookieInput,
                        onValueChange = { cookieInput = it },
                        label = { Text("Cookie JSON 内容") },
                        minLines = 4,
                        maxLines = 8,
                        shape = RoundedCornerShape(10.dp),
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            },
            confirmButton = {
                Button(
                    onClick = {
                        viewModel.submitCookies(cookieInput)
                        showCookieDialog = false
                    },
                    enabled = !uiState.isSubmittingCookie && cookieInput.isNotBlank()
                ) {
                    Text("导入并验证")
                }
            },
            dismissButton = {
                TextButton(
                    onClick = { showCookieDialog = false },
                    enabled = !uiState.isSubmittingCookie
                ) {
                    Text("取消")
                }
            }
        )
    }

    // 添加目标好友弹窗
    if (showAddTargetDialog) {
        AlertDialog(
            onDismissRequest = { showAddTargetDialog = false },
            title = { Text("添加目标好友") },
            text = {
                Column {
                    OutlinedTextField(
                        value = targetNameInput,
                        onValueChange = { targetNameInput = it },
                        label = { Text("好友昵称/备注") },
                        singleLine = true,
                        shape = RoundedCornerShape(10.dp),
                        modifier = Modifier.fillMaxWidth()
                    )
                    Spacer(modifier = Modifier.height(12.dp))
                    OutlinedTextField(
                        value = targetMsgInput,
                        onValueChange = { targetMsgInput = it },
                        label = { Text("专属消息 (留空则用默认文案)") },
                        singleLine = true,
                        shape = RoundedCornerShape(10.dp),
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            },
            confirmButton = {
                Button(
                    onClick = {
                        viewModel.addTarget(targetNameInput, targetMsgInput)
                        showAddTargetDialog = false
                    },
                    enabled = targetNameInput.isNotBlank()
                ) {
                    Text("添加")
                }
            },
            dismissButton = {
                TextButton(onClick = { showAddTargetDialog = false }) {
                    Text("取消")
                }
            }
        )
    }
}

@Composable
private fun SparkTargetCard(
    target: SparkTarget,
    defaultMessage: String,
    onDelete: () -> Unit,
    modifier: Modifier = Modifier
) {
    Card(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 4.dp),
        shape = RoundedCornerShape(14.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = target.name,
                    style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Bold)
                )
                Spacer(modifier = Modifier.height(2.dp))
                Text(
                    text = "发送内容: ${target.message ?: "(默认) $defaultMessage"}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            IconButton(onClick = onDelete) {
                Icon(
                    imageVector = Icons.Default.DeleteOutline,
                    contentDescription = "删除",
                    tint = MaterialTheme.colorScheme.error
                )
            }
        }
    }
}
