package com.muzermat.muztools.update

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.muzermat.muztools.BuildConfig

@Composable
fun UpdateDialog(viewModel: UpdateViewModel) {
    val state by viewModel.uiState.collectAsState()
    val info = state.info ?: return
    if (!state.visible) return
    val context = LocalContext.current
    val forced = info.force || BuildConfig.VERSION_CODE < info.minVersionCode

    AlertDialog(
        onDismissRequest = { if (!forced && !state.downloading) viewModel.dismiss() },
        title = { Text(info.title.ifBlank { "发现新版本 v${info.version}" }) },
        text = {
            Column {
                Text("当前版本 v${BuildConfig.VERSION_NAME}，最新版本 v${info.version}")
                if (info.message.isNotBlank()) {
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(info.message)
                }
                if (state.downloading) {
                    Spacer(modifier = Modifier.height(12.dp))
                    CircularProgressIndicator()
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(state.progressText.ifBlank { "正在下载…" })
                }
                state.error?.let {
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(it)
                }
            }
        },
        confirmButton = {
            TextButton(
                onClick = { viewModel.startUpdate(context) },
                enabled = !state.downloading
            ) {
                Text("立即更新")
            }
        },
        dismissButton = if (forced) null else {
            {
                TextButton(
                    onClick = { viewModel.dismiss() },
                    enabled = !state.downloading
                ) {
                    Text("稍后")
                }
            }
        }
    )
}
