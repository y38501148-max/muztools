package com.muzermat.muztools.update

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.muzermat.muztools.BuildConfig
import com.muzermat.muztools.data.api.ApiClient
import com.muzermat.muztools.data.model.AppVersion
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.io.File

data class UpdateUiState(
    val checking: Boolean = false,
    val info: AppVersion? = null,
    val visible: Boolean = false,
    val downloading: Boolean = false,
    val progressText: String = "",
    val error: String? = null
)

class UpdateViewModel(
    private val apiClient: ApiClient
) : ViewModel() {

    private val _uiState = MutableStateFlow(UpdateUiState())
    val uiState: StateFlow<UpdateUiState> = _uiState.asStateFlow()

    fun check() {
        viewModelScope.launch {
            _uiState.update { it.copy(checking = true, error = null) }
            val res = apiClient.getAppVersion()
            res.fold(
                onSuccess = { info ->
                    val newer = info.versionCode > BuildConfig.VERSION_CODE
                    _uiState.update {
                        it.copy(
                            checking = false,
                            info = info,
                            visible = newer,
                            error = null
                        )
                    }
                },
                onFailure = {
                    _uiState.update { it.copy(checking = false) }
                }
            )
        }
    }

    fun dismiss() {
        val info = _uiState.value.info
        val forced = info != null && (info.force || BuildConfig.VERSION_CODE < info.minVersionCode)
        if (!forced) {
            _uiState.update { it.copy(visible = false) }
        }
    }

    fun startUpdate(context: Context) {
        val info = _uiState.value.info ?: return
        viewModelScope.launch {
            _uiState.update { it.copy(downloading = true, progressText = "正在下载更新…", error = null) }
            val dir = File(context.cacheDir, "updates").apply { mkdirs() }
            val dest = File(dir, "muztools-${info.version}.apk")
            val download = apiClient.downloadApk(info.apkUrl, dest)
            download.fold(
                onSuccess = { file ->
                    _uiState.update { it.copy(downloading = false, progressText = "") }
                    installApk(context, file)
                },
                onFailure = { err ->
                    _uiState.update {
                        it.copy(downloading = false, error = err.message ?: "下载失败")
                    }
                }
            )
        }
    }

    private fun installApk(context: Context, file: File) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && !context.packageManager.canRequestPackageInstalls()) {
            val intent = Intent(
                Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                Uri.parse("package:${context.packageName}")
            ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            context.startActivity(intent)
        }
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(intent)
    }
}
