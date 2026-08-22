package com.muzermat.muztools.ui.screens.home

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
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.muzermat.muztools.data.model.SigninScheduleItem
import com.muzermat.muztools.ui.components.PendingApprovalBanner
import com.muzermat.muztools.ui.components.SectionHeader
import com.muzermat.muztools.ui.components.StatusBadge
import com.muzermat.muztools.ui.theme.SuccessColor

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(
    viewModel: HomeViewModel,
    onNavigateToTab: (Int) -> Unit
) {
    val uiState by viewModel.uiState.collectAsState()

    LaunchedEffect(Unit) {
        viewModel.loadData()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(
                            text = "木子工具",
                            style = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.Bold)
                        )
                        Text(
                            text = "你好，${uiState.displayName.ifBlank { "同学" }}",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                },
                actions = {
                    StatusBadge(
                        status = uiState.studentStatus.status,
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
                    contentDescription = "刷新"
                )
            }
        }
    ) { paddingValues ->
        if (uiState.isLoading && !uiState.isRefreshing) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(paddingValues),
                contentAlignment = Alignment.Center
            ) {
                CircularProgressIndicator()
            }
        } else {
            LazyColumn(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(paddingValues),
                contentPadding = PaddingValues(bottom = 80.dp)
            ) {
                if (uiState.studentStatus.status == "pending" || uiState.studentStatus.status == "待审批") {
                    item {
                        PendingApprovalBanner()
                    }
                }

                // 快捷统计卡片 (TD / 阳光体育)
                item {
                    SectionHeader(title = "体育与锻炼概况")
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 16.dp),
                        horizontalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        StatCard(
                            title = "TD 课外锻炼",
                            count = uiState.tdStatus.semesterCount,
                            target = uiState.tdStatus.targetCount,
                            unit = "次",
                            icon = Icons.Default.DirectionsRun,
                            onClick = { onNavigateToTab(2) },
                            modifier = Modifier.weight(1f)
                        )
                        StatCard(
                            title = "阳光体育",
                            count = uiState.sunshineStatus.count,
                            target = uiState.sunshineStatus.targetCount,
                            unit = "次",
                            icon = Icons.Default.WbSunny,
                            onClick = { onNavigateToTab(2) },
                            modifier = Modifier.weight(1f)
                        )
                    }
                }

                // 快捷功能入口
                item {
                    Spacer(modifier = Modifier.height(16.dp))
                    SectionHeader(title = "常用功能")
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 16.dp),
                        horizontalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        QuickActionItem(
                            title = "自动签到",
                            subtitle = if (uiState.autoSigninEnabled) "已开启" else "未开启",
                            icon = Icons.Default.HowToReg,
                            color = MaterialTheme.colorScheme.primary,
                            onClick = { onNavigateToTab(1) },
                            modifier = Modifier.weight(1f)
                        )
                        QuickActionItem(
                            title = "火花自动化",
                            subtitle = "定时续火花",
                            icon = Icons.Default.ElectricBolt,
                            color = MaterialTheme.colorScheme.tertiary,
                            onClick = { onNavigateToTab(3) },
                            modifier = Modifier.weight(1f)
                        )
                    }
                }

                // 今日课程 / 待签到列表
                item {
                    Spacer(modifier = Modifier.height(16.dp))
                    SectionHeader(
                        title = "今日课程签到",
                        action = {
                            TextButton(onClick = { onNavigateToTab(1) }) {
                                Text("查看全部")
                            }
                        }
                    )
                }

                if (uiState.scheduleItems.isEmpty()) {
                    item {
                        Card(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 16.dp, vertical = 8.dp),
                            shape = RoundedCornerShape(16.dp),
                            colors = CardDefaults.cardColors(
                                containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.4f)
                            )
                        ) {
                            Box(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(32.dp),
                                contentAlignment = Alignment.Center
                            ) {
                                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                    Icon(
                                        imageVector = Icons.Default.EventBusy,
                                        contentDescription = null,
                                        tint = MaterialTheme.colorScheme.outline,
                                        modifier = Modifier.size(40.dp)
                                    )
                                    Spacer(modifier = Modifier.height(8.dp))
                                    Text(
                                        text = "今日暂无课程安排或尚未同步",
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant
                                    )
                                }
                            }
                        }
                    }
                } else {
                    items(uiState.scheduleItems) { item ->
                        TodayCourseCard(item = item)
                    }
                }
            }
        }
    }
}

@Composable
private fun StatCard(
    title: String,
    count: Int,
    target: Int,
    unit: String,
    icon: ImageVector,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    Card(
        modifier = modifier
            .clip(RoundedCornerShape(16.dp))
            .clickable { onClick() },
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f)
        )
    ) {
        Column(
            modifier = Modifier.padding(16.dp)
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(
                    text = title,
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Icon(
                    imageVector = icon,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(18.dp)
                )
            }
            Spacer(modifier = Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.Bottom) {
                Text(
                    text = "$count",
                    style = MaterialTheme.typography.headlineMedium.copy(fontWeight = FontWeight.Bold),
                    color = MaterialTheme.colorScheme.onSurface
                )
                Text(
                    text = " / $target $unit",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(start = 4.dp, bottom = 4.dp)
                )
            }
            Spacer(modifier = Modifier.height(8.dp))
            LinearProgressIndicator(
                progress = { (count.toFloat() / target.coerceAtLeast(1)).coerceIn(0f, 1f) },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(6.dp)
                    .clip(CircleShape),
                color = MaterialTheme.colorScheme.primary,
                trackColor = MaterialTheme.colorScheme.surfaceVariant
            )
        }
    }
}

@Composable
private fun QuickActionItem(
    title: String,
    subtitle: String,
    icon: ImageVector,
    color: androidx.compose.ui.graphics.Color,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    Card(
        modifier = modifier
            .clip(RoundedCornerShape(16.dp))
            .clickable { onClick() },
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f)
        )
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(
                modifier = Modifier
                    .size(40.dp)
                    .clip(RoundedCornerShape(10.dp))
                    .background(color.copy(alpha = 0.15f)),
                contentAlignment = Alignment.Center
            ) {
                Icon(
                    imageVector = icon,
                    contentDescription = null,
                    tint = color,
                    modifier = Modifier.size(22.dp)
                )
            }
            Spacer(modifier = Modifier.width(12.dp))
            Column {
                Text(
                    text = title,
                    style = MaterialTheme.typography.bodyLarge.copy(fontWeight = FontWeight.SemiBold)
                )
                Text(
                    text = subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

@Composable
fun TodayCourseCard(
    item: SigninScheduleItem,
    modifier: Modifier = Modifier
) {
    Card(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 6.dp),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface
        ),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(
                modifier = Modifier.weight(1f)
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = item.courseName,
                        style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Bold),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis
                    )
                }

                Spacer(modifier = Modifier.height(4.dp))

                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        imageVector = Icons.Default.Place,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(14.dp)
                    )
                    Spacer(modifier = Modifier.width(4.dp))
                    Text(
                        text = item.classroom ?: "未知教室",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )

                    Spacer(modifier = Modifier.width(12.dp))

                    Icon(
                        imageVector = Icons.Default.Schedule,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(14.dp)
                    )
                    Spacer(modifier = Modifier.width(4.dp))
                    Text(
                        text = "${item.startTime ?: "--:--"} ~ ${item.endTime ?: "--:--"}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }

                item.scheduledTime?.let { sched ->
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = "预定触发时间: $sched",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.outline
                    )
                }
            }

            StatusBadge(
                status = item.status ?: "待签到",
                modifier = Modifier.padding(start = 8.dp)
            )
        }
    }
}
