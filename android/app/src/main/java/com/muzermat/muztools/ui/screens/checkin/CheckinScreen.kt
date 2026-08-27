package com.muzermat.muztools.ui.screens.checkin

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.MenuBook
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.muzermat.muztools.data.model.CheckinActivityField
import com.muzermat.muztools.data.model.CheckinProvider

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CheckinScreen(viewModel: CheckinViewModel) {
    val state by viewModel.uiState.collectAsState()
    val snackbar = remember { SnackbarHostState() }
    val clipboard = LocalClipboardManager.current
    var tokenText by remember(state.selectedProviderId) { mutableStateOf("") }
    val selectedProvider = state.providers.firstOrNull { it.id == state.selectedProviderId }

    LaunchedEffect(Unit) { viewModel.load() }
    LaunchedEffect(viewModel.messageFlow) {
        viewModel.messageFlow.collect { snackbar.showSnackbar(it) }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        selectedProvider?.name ?: "签到工具",
                        fontWeight = FontWeight.Bold
                    )
                },
                navigationIcon = {
                    if (selectedProvider != null) {
                        IconButton(onClick = viewModel::closeProvider) {
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回签到平台列表")
                        }
                    }
                }
            )
        }
    ) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(padding),
            contentPadding = PaddingValues(16.dp, 8.dp, 16.dp, 88.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            if (state.isLoading && state.providers.isEmpty()) {
                item { LoadingCard("正在读取签到平台") }
            }

            if (selectedProvider == null) {
                item { CheckinHubIntro() }
                state.providers.forEach { provider ->
                    item(key = provider.id) {
                        ProviderFeatureCard(provider = provider, onOpen = { viewModel.openProvider(provider.id) })
                    }
                }
                if (state.error.isNotBlank()) item { ErrorCard(state.error) }
            } else {
                item { UsageTutorialCard(provider = selectedProvider) }
                item {
                    ProviderTokenCard(
                        connected = state.config.connected,
                        tokenTail = state.config.tokenTail,
                        editing = state.isEditingToken,
                        saving = state.isSavingToken,
                        tokenText = tokenText,
                        onTokenChanged = { tokenText = it },
                        onPaste = {
                            val pasted = clipboard.getText()?.text?.trim().orEmpty()
                            if (pasted.isBlank()) {
                                viewModel.showMessage("剪贴板中没有可用的 Token")
                            } else {
                                tokenText = pasted
                                viewModel.showMessage("已从剪贴板粘贴，请确认后保存")
                            }
                        },
                        onEdit = viewModel::beginTokenEdit,
                        onCancel = {
                            tokenText = ""
                            viewModel.cancelTokenEdit()
                        },
                        onSave = { viewModel.saveToken(tokenText) { tokenText = "" } }
                    )
                }

                if (state.config.connected) {
                    item {
                        ActivityLookupCard(
                            code = state.activityCode,
                            loading = state.isPreviewing,
                            signing = state.isSigning,
                            onCodeChanged = viewModel::updateActivityCode,
                            onPreview = viewModel::preview
                        )
                    }
                }

                if (state.error.isNotBlank()) item { ErrorCard(state.error) }

                state.activity?.let { activity ->
                    item {
                        Card(shape = RoundedCornerShape(18.dp)) {
                            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
                                Text(activity.name.ifBlank { "签到活动" }, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                                if (activity.startAt.isNotBlank() || activity.endAt.isNotBlank()) {
                                    Text("活动时间：${activity.startAt.ifBlank { "-" }} 至 ${activity.endAt.ifBlank { "-" }}", style = MaterialTheme.typography.bodySmall)
                                }
                                if (activity.signTime.isNotEmpty()) {
                                    Text("签到时段：${activity.signTime.joinToString("；") { it.joinToString(" - ") }}", style = MaterialTheme.typography.bodySmall)
                                }
                                if (activity.locationRequired) {
                                    Text("签到地点：${activity.locationAddress.ifBlank { "活动指定位置" }}", style = MaterialTheme.typography.bodySmall)
                                    Text(
                                        if (activity.locationLongitude.isNotBlank() && activity.locationLatitude.isNotBlank()) {
                                            "将自动使用活动返回的目标坐标，无需授予设备定位权限。"
                                        } else {
                                            "活动未返回目标坐标，请在下方手动填写经纬度。"
                                        },
                                        style = MaterialTheme.typography.bodySmall,
                                        color = if (activity.locationLongitude.isBlank() || activity.locationLatitude.isBlank()) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant
                                    )
                                }
                                AssistChip(
                                    onClick = {},
                                    enabled = false,
                                    label = { Text(if (activity.canSign == 1) "当前可签到" else "当前不在可签到状态") },
                                    leadingIcon = { Icon(if (activity.canSign == 1) Icons.Default.CheckCircle else Icons.Default.Schedule, null, Modifier.size(18.dp)) }
                                )
                            }
                        }
                    }

                    if (activity.locationRequired && (activity.locationLongitude.isBlank() || activity.locationLatitude.isBlank())) {
                        item {
                            LocationInputCard(
                                longitude = state.locationLongitude,
                                latitude = state.locationLatitude,
                                onLongitudeChanged = { viewModel.updateLocation(longitude = it) },
                                onLatitudeChanged = { viewModel.updateLocation(latitude = it) }
                            )
                        }
                    }

                    activity.fields.forEach { field ->
                        item(key = field.title) {
                            CheckinFieldInput(field, state.fieldValues[field.title].orEmpty(), viewModel::updateField)
                        }
                    }

                    item {
                        Button(
                            onClick = viewModel::sign,
                            modifier = Modifier.fillMaxWidth().height(50.dp),
                            enabled = activity.canSign == 1 && !state.isSigning
                        ) {
                            if (state.isSigning) {
                                CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                                Spacer(Modifier.width(8.dp))
                            } else {
                                Icon(Icons.AutoMirrored.Filled.Send, null, Modifier.size(18.dp))
                                Spacer(Modifier.width(8.dp))
                            }
                            Text("确认签到")
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun CheckinHubIntro() {
    Card(
        shape = RoundedCornerShape(20.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)
    ) {
        Column(Modifier.padding(18.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Default.Dashboard, null, tint = MaterialTheme.colorScheme.primary)
                Spacer(Modifier.width(10.dp))
                Text("远程签到功能区", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            }
            Spacer(Modifier.height(8.dp))
            Text(
                "请先选择对应的签到平台。进入小板块后，可查看完整教程、导入 Token、查询活动并执行签到。",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onPrimaryContainer
            )
        }
    }
}

@Composable
private fun ProviderFeatureCard(provider: CheckinProvider, onOpen: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onOpen),
        shape = RoundedCornerShape(18.dp)
    ) {
        Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
            Surface(shape = CircleShape, color = MaterialTheme.colorScheme.primaryContainer, modifier = Modifier.size(48.dp)) {
                Box(contentAlignment = Alignment.Center) {
                    Icon(Icons.Default.HowToReg, null, tint = MaterialTheme.colorScheme.primary)
                }
            }
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f)) {
                Text(provider.name, fontWeight = FontWeight.Bold)
                Text(
                    provider.description.ifBlank { "进入平台签到功能" },
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            Icon(Icons.Default.ChevronRight, contentDescription = "进入${provider.name}", tint = MaterialTheme.colorScheme.outline)
        }
    }
}

@Composable
private fun UsageTutorialCard(provider: CheckinProvider) {
    var expanded by remember(provider.id) { mutableStateOf(true) }
    Card(shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.padding(16.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth().clickable { expanded = !expanded },
                verticalAlignment = Alignment.CenterVertically
            ) {
                Icon(Icons.AutoMirrored.Filled.MenuBook, null, tint = MaterialTheme.colorScheme.primary)
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text("首次使用教程", fontWeight = FontWeight.Bold)
                    Text("Token 获取、导入和签到完整流程", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                Icon(if (expanded) Icons.Default.ExpandLess else Icons.Default.ExpandMore, contentDescription = if (expanded) "收起教程" else "展开教程")
            }
            if (expanded) {
                Spacer(Modifier.height(14.dp))
                TutorialStep(1, "获取 Token（推荐电脑端微信）", "在电脑安装并打开 Proxyman、Charles 或 mitmproxy，按工具提示安装并信任 HTTPS 证书，再把系统 HTTP/HTTPS 代理指向抓包工具。打开微信中的“${provider.name}”小程序并重新登录。")
                TutorialStep(2, "复制 32 位 Token", "在抓包记录中搜索 qiandaoerweima.yuleji.top，打开 POST /api/wxapp/auth 响应，复制 data.token.token；也可从 signInfo 等后续请求头 authori-zation 中复制。只分析你自己的账号与流量。")
                TutorialStep(3, "导入并验证", "回到此页点击“从剪贴板粘贴”，确认后选择“保存并验证”。Token 约 2 小时有效，重新登录小程序会使旧 Token 失效。")
                TutorialStep(4, "查询并签到", "从老师展示的二维码或链接中取得 AS 开头的活动码，查询活动，核对名称、时间和地点，填写姓名、学号等必填项，再点击“确认签到”。")
                HorizontalDivider(Modifier.padding(vertical = 10.dp))
                Row(verticalAlignment = Alignment.Top) {
                    Icon(Icons.Default.Security, null, Modifier.size(18.dp), tint = MaterialTheme.colorScheme.primary)
                    Spacer(Modifier.width(8.dp))
                    Text(
                        "系统无法越权直接读取微信中的 Token，因此不提供虚假的“自动提取”。剪贴板按钮只会在你主动点击时读取；请勿把 Token 发送给他人。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }
    }
}

@Composable
private fun TutorialStep(number: Int, title: String, content: String) {
    Row(Modifier.padding(bottom = 12.dp), verticalAlignment = Alignment.Top) {
        Surface(shape = CircleShape, color = MaterialTheme.colorScheme.primary, modifier = Modifier.size(26.dp)) {
            Box(contentAlignment = Alignment.Center) {
                Text(number.toString(), color = MaterialTheme.colorScheme.onPrimary, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Bold)
            }
        }
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text(title, fontWeight = FontWeight.SemiBold)
            Text(content, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun ProviderTokenCard(
    connected: Boolean,
    tokenTail: String,
    editing: Boolean,
    saving: Boolean,
    tokenText: String,
    onTokenChanged: (String) -> Unit,
    onPaste: () -> Unit,
    onEdit: () -> Unit,
    onCancel: () -> Unit,
    onSave: () -> Unit
) {
    Card(shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.padding(16.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("平台 Token", fontWeight = FontWeight.Bold)
                    Text(
                        if (connected) "已连接（末尾 ${tokenTail.ifBlank { "****" }}）" else "尚未绑定，请按教程导入 Token",
                        style = MaterialTheme.typography.bodySmall,
                        color = if (connected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                if (connected && !editing) TextButton(onClick = onEdit) { Text("更换") }
            }
            if (editing) {
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    value = tokenText,
                    onValueChange = onTokenChanged,
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("32 位 Token") },
                    placeholder = { Text("粘贴 authori-zation Token") },
                    singleLine = true,
                    visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii),
                    enabled = !saving,
                    trailingIcon = { IconButton(onClick = onPaste, enabled = !saving) { Icon(Icons.Default.ContentPaste, contentDescription = "从剪贴板粘贴") } }
                )
                Spacer(Modifier.height(8.dp))
                OutlinedButton(onClick = onPaste, enabled = !saving, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Default.ContentPaste, null, Modifier.size(18.dp))
                    Spacer(Modifier.width(7.dp))
                    Text("从剪贴板一键粘贴")
                }
                Spacer(Modifier.height(10.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = onSave, enabled = tokenText.isNotBlank() && !saving, modifier = Modifier.weight(1f)) {
                        if (saving) {
                            CircularProgressIndicator(Modifier.size(17.dp), strokeWidth = 2.dp)
                            Spacer(Modifier.width(7.dp))
                        }
                        Text("保存并验证")
                    }
                    if (connected) OutlinedButton(onClick = onCancel, enabled = !saving) { Text("取消") }
                }
            }
        }
    }
}

@Composable
private fun ActivityLookupCard(
    code: String,
    loading: Boolean,
    signing: Boolean,
    onCodeChanged: (String) -> Unit,
    onPreview: () -> Unit
) {
    Card(shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.padding(16.dp)) {
            Text("活动签到", fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(10.dp))
            OutlinedTextField(
                value = code,
                onValueChange = onCodeChanged,
                modifier = Modifier.fillMaxWidth(),
                label = { Text("活动码") },
                placeholder = { Text("例如 AS202608243746752343") },
                singleLine = true,
                enabled = !loading && !signing
            )
            Spacer(Modifier.height(10.dp))
            Button(onClick = onPreview, enabled = code.isNotBlank() && !loading && !signing, modifier = Modifier.fillMaxWidth()) {
                if (loading) {
                    CircularProgressIndicator(Modifier.size(17.dp), strokeWidth = 2.dp)
                    Spacer(Modifier.width(7.dp))
                } else {
                    Icon(Icons.Default.Search, null, Modifier.size(18.dp))
                    Spacer(Modifier.width(7.dp))
                }
                Text("读取活动信息")
            }
        }
    }
}

@Composable
private fun LoadingCard(text: String) {
    Card(shape = RoundedCornerShape(18.dp)) {
        Row(Modifier.fillMaxWidth().padding(20.dp), verticalAlignment = Alignment.CenterVertically) {
            CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp)
            Spacer(Modifier.width(12.dp))
            Text(text)
        }
    }
}

@Composable
private fun ErrorCard(message: String) {
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer), shape = RoundedCornerShape(18.dp)) {
        Text(message, modifier = Modifier.padding(16.dp), color = MaterialTheme.colorScheme.onErrorContainer)
    }
}

@Composable
private fun LocationInputCard(
    longitude: String,
    latitude: String,
    onLongitudeChanged: (String) -> Unit,
    onLatitudeChanged: (String) -> Unit
) {
    Card(shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.padding(16.dp)) {
            Text("签到目标坐标", fontWeight = FontWeight.SemiBold)
            Text(
                "请填写活动要求的目标位置，而不是当前设备位置。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedTextField(
                    value = longitude,
                    onValueChange = onLongitudeChanged,
                    modifier = Modifier.weight(1f),
                    label = { Text("经度 *") },
                    placeholder = { Text("116.23128") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal)
                )
                OutlinedTextField(
                    value = latitude,
                    onValueChange = onLatitudeChanged,
                    modifier = Modifier.weight(1f),
                    label = { Text("纬度 *") },
                    placeholder = { Text("40.22077") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal)
                )
            }
        }
    }
}

@Composable
private fun CheckinFieldInput(field: CheckinActivityField, value: String, onChanged: (String, String) -> Unit) {
    Card(shape = RoundedCornerShape(18.dp)) {
        Column(Modifier.padding(16.dp)) {
            Text(field.title + if (field.required) " *" else "", fontWeight = FontWeight.SemiBold)
            if (field.options.isNotEmpty()) {
                Spacer(Modifier.height(6.dp))
                field.options.forEach { option ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        RadioButton(selected = value == option, onClick = { onChanged(field.title, option) })
                        Text(option)
                    }
                }
            } else {
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = value,
                    onValueChange = { onChanged(field.title, it) },
                    modifier = Modifier.fillMaxWidth(),
                    placeholder = { Text("请输入${field.title}") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Text)
                )
            }
        }
    }
}
