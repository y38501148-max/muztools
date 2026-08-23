package com.muzermat.muztools.ui.screens.features

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.muzermat.muztools.ui.screens.signin.SigninViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FeaturesScreen(
    signinViewModel: SigninViewModel,
    onOpenSignin: () -> Unit,
    onOpenTd: () -> Unit,
    onOpenSpark: () -> Unit,
    onOpenTibo: () -> Unit
) {
    val state by signinViewModel.uiState.collectAsState()
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(Unit) { signinViewModel.loadData() }
    LaunchedEffect(signinViewModel.messageFlow) { signinViewModel.messageFlow.collect { snackbar.showSnackbar(it) } }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = { TopAppBar(title = { Text("功能", fontWeight = FontWeight.Bold) }) }
    ) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding), contentPadding = PaddingValues(vertical = 8.dp)) {
            item { FeatureCard("自动签到", "课表查询与定时自动签到", Icons.Default.HowToReg, MaterialTheme.colorScheme.primary, onOpenSignin) }
            item { FeatureCard("TD / 阳光", "体育锻炼次数查询与校园网直连打卡", Icons.Default.DirectionsRun, Color(0xFF0288D1), onOpenTd) }
            if (state.canUseDouyin) {
                item { FeatureCard("抖音续火花", "导入 Cookie 后自动维护聊天火花", Icons.Default.ElectricBolt, Color(0xFFE65100), onOpenSpark) }
            }
            item { FeatureCard("Tibo Reset 监测", "查看相关推特历史与系统通知", Icons.Default.Radar, Color(0xFF111827), onOpenTibo) }
            if (state.canManageInvites) {
                item {
                    FeatureCard(
                        "获取邀请码", "领取一个未使用的一次性注册邀请码",
                        Icons.Default.ConfirmationNumber, Color(0xFF7B1FA2), signinViewModel::issueInvite,
                        loading = state.isIssuingInvite
                    )
                }
            }
        }
    }

    if (state.issuedInviteCode.isNotBlank()) {
        AlertDialog(
            onDismissRequest = signinViewModel::clearIssuedInvite,
            title = { Text("注册邀请码") },
            text = {
                Column {
                    Text("邀请码只能使用一次，请通过可信渠道发送。")
                    Spacer(Modifier.height(14.dp))
                    SelectionContainer {
                        Text(state.issuedInviteCode, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                    }
                    Spacer(Modifier.height(10.dp))
                    Text("库存剩余 ${state.inviteRemaining} 个", style = MaterialTheme.typography.bodySmall)
                }
            },
            confirmButton = { TextButton(onClick = signinViewModel::clearIssuedInvite) { Text("关闭") } }
        )
    }
}

@Composable
private fun FeatureCard(title: String, subtitle: String, icon: ImageVector, tint: Color, onOpen: () -> Unit, loading: Boolean = false) {
    Card(
        Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 5.dp).clickable(enabled = !loading, onClick = onOpen),
        shape = RoundedCornerShape(18.dp)
    ) {
        Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(46.dp).clip(CircleShape).background(tint.copy(alpha = .12f)), contentAlignment = Alignment.Center) {
                if (loading) CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp) else Icon(icon, null, tint = tint)
            }
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f)) {
                Text(title, fontWeight = FontWeight.Bold)
                Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Text("可用", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
            Spacer(Modifier.width(4.dp))
            Icon(Icons.Default.ChevronRight, null, tint = MaterialTheme.colorScheme.outline)
        }
    }
}
