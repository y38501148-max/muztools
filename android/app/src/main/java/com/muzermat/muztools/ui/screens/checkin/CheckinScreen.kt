package com.muzermat.muztools.ui.screens.checkin

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
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
    var tokenText by remember(state.selectedProviderId) { mutableStateOf("") }

    LaunchedEffect(Unit) { viewModel.load() }
    LaunchedEffect(viewModel.messageFlow) {
        viewModel.messageFlow.collect { snackbar.showSnackbar(it) }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = { TopAppBar(title = { Text("签到工具", fontWeight = FontWeight.Bold) }) }
    ) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(padding),
            contentPadding = PaddingValues(16.dp, 8.dp, 16.dp, 88.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            if (state.isLoading && state.providers.isEmpty()) {
                item { LoadingCard("正在读取签到平台") }
            }

            if (state.providers.size > 1) {
                item {
                    ProviderSelector(
                        providers = state.providers,
                        selectedId = state.selectedProviderId,
                        onSelected = viewModel::selectProvider
                    )
                }
            }

            state.providers.firstOrNull { it.id == state.selectedProviderId }?.let { provider ->
                item {
                    Card(shape = RoundedCornerShape(18.dp)) {
                        Column(Modifier.padding(16.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Icon(Icons.Default.HowToReg, null, tint = MaterialTheme.colorScheme.primary)
                                Spacer(Modifier.width(10.dp))
                                Text(provider.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                            }
                            if (provider.description.isNotBlank()) {
                                Spacer(Modifier.height(6.dp))
                                Text(provider.description, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                        }
                    }
                }
            }

            if (state.selectedProviderId.isNotBlank()) {
                item {
                    Card(shape = RoundedCornerShape(18.dp)) {
                        Column(Modifier.padding(16.dp)) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Column(Modifier.weight(1f)) {
                                    Text("平台 Token", fontWeight = FontWeight.Bold)
                                    Text(
                                        if (state.config.connected) "已连接（末尾 ${state.config.tokenTail.ifBlank { "****" }}）" else "尚未绑定，请先导入小程序 Token",
                                        style = MaterialTheme.typography.bodySmall,
                                        color = if (state.config.connected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant
                                    )
                                }
                                if (state.config.connected && !state.isEditingToken) {
                                    TextButton(onClick = viewModel::beginTokenEdit) { Text("更换") }
                                }
                            }
                            if (state.isEditingToken) {
                                Spacer(Modifier.height(12.dp))
                                OutlinedTextField(
                                    value = tokenText,
                                    onValueChange = { tokenText = it },
                                    modifier = Modifier.fillMaxWidth(),
                                    label = { Text("Token") },
                                    placeholder = { Text("粘贴平台 Token") },
                                    singleLine = true,
                                    visualTransformation = PasswordVisualTransformation(),
                                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii),
                                    enabled = !state.isSavingToken
                                )
                                Spacer(Modifier.height(10.dp))
                                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    Button(
                                        onClick = { viewModel.saveToken(tokenText) { tokenText = "" } },
                                        enabled = tokenText.isNotBlank() && !state.isSavingToken,
                                        modifier = Modifier.weight(1f)
                                    ) {
                                        if (state.isSavingToken) {
                                            CircularProgressIndicator(Modifier.size(17.dp), strokeWidth = 2.dp)
                                            Spacer(Modifier.width(7.dp))
                                        }
                                        Text("保存并验证")
                                    }
                                    if (state.config.connected) {
                                        OutlinedButton(
                                            onClick = {
                                                tokenText = ""
                                                viewModel.cancelTokenEdit()
                                            },
                                            enabled = !state.isSavingToken
                                        ) { Text("取消") }
                                    }
                                }
                            }
                        }
                    }
                }

                if (state.config.connected) {
                    item {
                        Card(shape = RoundedCornerShape(18.dp)) {
                            Column(Modifier.padding(16.dp)) {
                                Text("活动签到", fontWeight = FontWeight.Bold)
                                Spacer(Modifier.height(10.dp))
                                OutlinedTextField(
                                    value = state.activityCode,
                                    onValueChange = viewModel::updateActivityCode,
                                    modifier = Modifier.fillMaxWidth(),
                                    label = { Text("活动码") },
                                    placeholder = { Text("例如 AS202608243746752343") },
                                    singleLine = true,
                                    enabled = !state.isPreviewing && !state.isSigning
                                )
                                Spacer(Modifier.height(10.dp))
                                Button(
                                    onClick = viewModel::preview,
                                    enabled = state.activityCode.isNotBlank() && !state.isPreviewing && !state.isSigning,
                                    modifier = Modifier.fillMaxWidth()
                                ) {
                                    if (state.isPreviewing) {
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
                }
            }

            if (state.error.isNotBlank()) {
                item {
                    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer), shape = RoundedCornerShape(18.dp)) {
                        Text(state.error, modifier = Modifier.padding(16.dp), color = MaterialTheme.colorScheme.onErrorContainer)
                    }
                }
            }

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
                                Text("服务器会按活动指定坐标提交，无需授予设备定位权限。", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
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
private fun ProviderSelector(providers: List<CheckinProvider>, selectedId: String, onSelected: (String) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    val selected = providers.firstOrNull { it.id == selectedId } ?: providers.first()
    Box {
        OutlinedButton(onClick = { expanded = true }, modifier = Modifier.fillMaxWidth()) {
            Text(selected.name, modifier = Modifier.weight(1f))
            Icon(Icons.Default.ArrowDropDown, null)
        }
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }, modifier = Modifier.fillMaxWidth(.85f)) {
            providers.forEach { provider ->
                DropdownMenuItem(
                    text = { Text(provider.name) },
                    onClick = {
                        expanded = false
                        onSelected(provider.id)
                    }
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
