package com.muzermat.muztools.ui.screens.features

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.DirectionsRun
import androidx.compose.material.icons.filled.ElectricBolt
import androidx.compose.material.icons.filled.HowToReg
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.muzermat.muztools.ui.components.StatusBadge
import com.muzermat.muztools.ui.screens.signin.SigninViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FeaturesScreen(
    signinViewModel: SigninViewModel,
    onOpenSignin: () -> Unit,
    onOpenTd: () -> Unit,
    onOpenSpark: () -> Unit,
    onRequest: (String) -> Unit
) {
    val signinState by signinViewModel.uiState.collectAsState()
    val snackbarHostState = remember { SnackbarHostState() }

    LaunchedEffect(Unit) { signinViewModel.loadData() }
    LaunchedEffect(signinViewModel.messageFlow) {
        signinViewModel.messageFlow.collect { snackbarHostState.showSnackbar(it) }
    }

    val student = signinState.studentStatus
    val signin = student.signinStatus.ifBlank { student.approvals.signin }
    val td = student.tdStatus.ifBlank { student.approvals.td }
    val spark = student.sparkStatus.ifBlank { student.approvals.spark }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        text = "功能",
                        style = MaterialTheme.typography.titleLarge.copy(
                            fontWeight = FontWeight.Bold,
                            fontSize = 20.sp
                        )
                    )
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background
                )
            )
        }
    ) { padding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
            contentPadding = PaddingValues(top = 4.dp, bottom = 24.dp)
        ) {
            item {
                FeatureCard(
                    title = "自动签到",
                    subtitle = "课表查询与定时自动签到",
                    badgeText = "常用",
                    icon = Icons.Default.HowToReg,
                    iconTint = MaterialTheme.colorScheme.primary,
                    status = signin,
                    onOpen = onOpenSignin,
                    onRequest = { onRequest("signin") }
                )
            }
            item {
                FeatureCard(
                    title = "TD / 阳光",
                    subtitle = "体育锻炼次数查询与校园网直连打卡",
                    badgeText = "体育",
                    icon = Icons.Default.DirectionsRun,
                    iconTint = Color(0xFF0288D1),
                    status = td,
                    onOpen = onOpenTd,
                    onRequest = { onRequest("td") }
                )
            }
            item {
                FeatureCard(
                    title = "抖音续火花",
                    subtitle = "手机一键登录，每日自动互动续火花",
                    badgeText = "社交",
                    icon = Icons.Default.ElectricBolt,
                    iconTint = Color(0xFFE65100),
                    status = spark,
                    onOpen = onOpenSpark,
                    onRequest = { onRequest("spark") }
                )
            }
        }
    }
}

@Composable
private fun FeatureCard(
    title: String,
    subtitle: String,
    badgeText: String,
    icon: ImageVector,
    iconTint: Color,
    status: String,
    onOpen: () -> Unit,
    onRequest: () -> Unit
) {
    val isApproved = status == "approved" || status == "已通过"
    val isPending = status == "pending" || status == "待审批"

    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 6.dp)
            .clip(RoundedCornerShape(20.dp))
            .clickable(enabled = isApproved) { onOpen() },
        shape = RoundedCornerShape(20.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.5.dp)
    ) {
        Column(modifier = Modifier.padding(18.dp)) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth()
            ) {
                Box(
                    modifier = Modifier
                        .size(46.dp)
                        .clip(RoundedCornerShape(14.dp))
                        .background(iconTint.copy(alpha = 0.12f)),
                    contentAlignment = Alignment.Center
                ) {
                    Icon(
                        imageVector = icon,
                        contentDescription = null,
                        tint = iconTint,
                        modifier = Modifier.size(24.dp)
                    )
                }

                Spacer(modifier = Modifier.width(14.dp))

                Column(modifier = Modifier.weight(1f)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            text = title,
                            style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Bold)
                        )
                        Spacer(modifier = Modifier.width(6.dp))
                        Surface(
                            shape = RoundedCornerShape(6.dp),
                            color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.7f)
                        ) {
                            Text(
                                text = badgeText,
                                style = MaterialTheme.typography.labelSmall.copy(fontSize = 10.sp),
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(horizontal = 5.dp, vertical = 2.dp)
                            )
                        }
                    }
                    Spacer(modifier = Modifier.height(3.dp))
                    Text(
                        text = subtitle,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }

                Spacer(modifier = Modifier.width(8.dp))

                StatusBadge(status = statusLabel(status))

                if (isApproved) {
                    Spacer(modifier = Modifier.width(4.dp))
                    Icon(
                        imageVector = Icons.Default.ChevronRight,
                        contentDescription = "进入",
                        tint = MaterialTheme.colorScheme.outline
                    )
                }
            }

            if (!isApproved) {
                Spacer(modifier = Modifier.height(14.dp))
                Button(
                    onClick = onRequest,
                    enabled = !isPending,
                    shape = RoundedCornerShape(12.dp),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = MaterialTheme.colorScheme.primary,
                        disabledContainerColor = MaterialTheme.colorScheme.surfaceVariant
                    ),
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(42.dp)
                ) {
                    Text(
                        text = if (isPending) "审批中" else "申请开通",
                        style = MaterialTheme.typography.labelLarge.copy(fontWeight = FontWeight.SemiBold)
                    )
                }
            }
        }
    }
}

private fun statusLabel(status: String): String = when (status) {
    "approved" -> "已通过"
    "pending" -> "待审批"
    "rejected" -> "已拒绝"
    else -> "未申请"
}
