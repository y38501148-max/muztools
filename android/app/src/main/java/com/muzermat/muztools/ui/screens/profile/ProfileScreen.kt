package com.muzermat.muztools.ui.screens.profile

import androidx.compose.foundation.background
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.muzermat.muztools.data.model.NotificationItem
import com.muzermat.muztools.ui.components.SectionHeader
import com.muzermat.muztools.ui.components.StatusBadge

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProfileScreen(
    viewModel: ProfileViewModel,
    onLogout: () -> Unit
) {
    val uiState by viewModel.uiState.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }

    var showLogoutDialog by remember { mutableStateOf(false) }
    var showServerDialog by remember { mutableStateOf(false) }
    var tempServerUrl by remember { mutableStateOf(uiState.serverUrl) }

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
                        text = "个人中心",
                        style = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.Bold)
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
                    contentDescription = "刷新个人信息"
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
            // 用户基本信息卡片
            item {
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 8.dp),
                    shape = RoundedCornerShape(20.dp),
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                    elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(20.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Box(
                            modifier = Modifier
                                .size(56.dp)
                                .clip(CircleShape)
                                .background(MaterialTheme.colorScheme.primary.copy(alpha = 0.15f)),
                            contentAlignment = Alignment.Center
                        ) {
                            Icon(
                                imageVector = Icons.Default.Person,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.primary,
                                modifier = Modifier.size(32.dp)
                            )
                        }

                        Spacer(modifier = Modifier.width(16.dp))

                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = uiState.user?.displayName?.ifBlank { uiState.user?.username } ?: "木子用户",
                                style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Bold)
                            )
                            Spacer(modifier = Modifier.height(2.dp))
                            Text(
                                text = "账号: ${uiState.user?.username ?: "--"}",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }

                        StatusBadge(status = uiState.studentStatus.status)
                    }
                }
            }

            // 学生身份认证状态详情
            item {
                Spacer(modifier = Modifier.height(8.dp))
                SectionHeader(title = "学生身份认证")
                Card(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 4.dp),
                    shape = RoundedCornerShape(16.dp),
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.4f)
                    )
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            Text("认证学号", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Text(uiState.studentStatus.studentId ?: "未绑定", style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.SemiBold))
                        }
                        Spacer(modifier = Modifier.height(8.dp))
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            Text("认证姓名", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Text(uiState.studentStatus.displayName ?: "--", style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.SemiBold))
                        }
                        Spacer(modifier = Modifier.height(8.dp))
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            Text("审批状态", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Text(uiState.studentStatus.status, style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.SemiBold))
                        }
                        uiState.studentStatus.reason?.let { reason ->
                            Spacer(modifier = Modifier.height(8.dp))
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween
                            ) {
                                Text("审批备注", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.error)
                                Text(reason, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.error)
                            }
                        }
                    }
                }
            }

            // 系统通知列表
            item {
                Spacer(modifier = Modifier.height(12.dp))
                SectionHeader(
                    title = "最近通知",
                    action = {
                        Text(
                            text = "共 ${uiState.notifications.size} 条",
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.outline
                        )
                    }
                )
            }

            if (uiState.notifications.isEmpty()) {
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
                                text = "暂无系统通知",
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                }
            } else {
                items(uiState.notifications) { notif ->
                    NotificationCard(item = notif)
                }
            }

            // 服务器设置与退出登录
            item {
                Spacer(modifier = Modifier.height(16.dp))
                SectionHeader(title = "系统设置")
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
                                Text("后端 API 地址", style = MaterialTheme.typography.bodyLarge.copy(fontWeight = FontWeight.Medium))
                                Text(uiState.serverUrl, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            TextButton(onClick = {
                                tempServerUrl = uiState.serverUrl
                                showServerDialog = true
                            }) {
                                Text("修改")
                            }
                        }
                    }
                }

                Spacer(modifier = Modifier.height(20.dp))
                Box(modifier = Modifier.padding(horizontal = 16.dp)) {
                    OutlinedButton(
                        onClick = { showLogoutDialog = true },
                        shape = RoundedCornerShape(14.dp),
                        colors = ButtonDefaults.outlinedButtonColors(
                            contentColor = MaterialTheme.colorScheme.error
                        ),
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(50.dp)
                    ) {
                        Icon(imageVector = Icons.Default.Logout, contentDescription = null)
                        Spacer(modifier = Modifier.width(8.dp))
                        Text("退出登录", fontSize = 16.sp, fontWeight = FontWeight.Bold)
                    }
                }
            }
        }
    }

    if (showLogoutDialog) {
        AlertDialog(
            onDismissRequest = { showLogoutDialog = false },
            title = { Text("确认退出") },
            text = { Text("确定要退出当前木子工具账号吗？本地缓存凭据将被清除。") },
            confirmButton = {
                Button(
                    onClick = {
                        showLogoutDialog = false
                        viewModel.logout()
                        onLogout()
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error)
                ) {
                    Text("退出")
                }
            },
            dismissButton = {
                TextButton(onClick = { showLogoutDialog = false }) {
                    Text("取消")
                }
            }
        )
    }

    if (showServerDialog) {
        AlertDialog(
            onDismissRequest = { showServerDialog = false },
            title = { Text("修改服务器地址") },
            text = {
                Column {
                    OutlinedTextField(
                        value = tempServerUrl,
                        onValueChange = { tempServerUrl = it },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    viewModel.updateServerUrl(tempServerUrl)
                    showServerDialog = false
                }) {
                    Text("保存")
                }
            },
            dismissButton = {
                TextButton(onClick = { showServerDialog = false }) {
                    Text("取消")
                }
            }
        )
    }
}

@Composable
fun NotificationCard(
    item: NotificationItem,
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
        Column(modifier = Modifier.padding(14.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    text = item.title,
                    style = MaterialTheme.typography.titleSmall.copy(fontWeight = FontWeight.Bold),
                    color = MaterialTheme.colorScheme.primary
                )
                item.createdAt?.let {
                    Text(
                        text = it,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.outline
                    )
                }
            }
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = item.content,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface
            )
        }
    }
}
