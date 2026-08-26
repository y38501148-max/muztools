package com.muzermat.muztools.ui.screens.td

import android.content.Context
import android.net.Uri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.muzermat.muztools.data.api.ApiClient
import com.muzermat.muztools.data.model.SunshineStatusResponse
import com.muzermat.muztools.data.model.TdManualRequest
import com.muzermat.muztools.data.model.TdStatusResponse
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class TdUiState(
    val isLoading: Boolean = false,
    val isRefreshing: Boolean = false,
    val studentId: String = "",
    val studentStatus: String = "unbound",
    val tdStatus: TdStatusResponse = TdStatusResponse(),
    val sunshineStatus: SunshineStatusResponse = SunshineStatusResponse(),
    val selectedCampus: String = "学院路",
    val entranceMachineId: String = "",
    val exitMachineId: String = "",
    val gapMinutes: Int = 4,
    val entrancePhotoUri: Uri? = null,
    val exitPhotoUri: Uri? = null,
    val isSubmittingManual: Boolean = false,
)

class TdViewModel(
    private val apiClient: ApiClient
) : ViewModel() {

    private val _uiState = MutableStateFlow(TdUiState())
    val uiState: StateFlow<TdUiState> = _uiState.asStateFlow()

    private val _messageFlow = MutableSharedFlow<String>()
    val messageFlow: SharedFlow<String> = _messageFlow.asSharedFlow()

    fun loadData(isRefresh: Boolean = false) {
        viewModelScope.launch {
            _uiState.update {
                if (isRefresh) it.copy(isRefreshing = true) else it.copy(isLoading = true)
            }

            val studentDeferred = async { apiClient.getStudentStatus() }
            val tdDeferred = async { apiClient.getTdStatus() }
            val sunshineDeferred = async { apiClient.getSunshineStatus() }

            val studentRes = studentDeferred.await()
            val tdRes = tdDeferred.await()
            val sunshineRes = sunshineDeferred.await()

            _uiState.update { current ->
                current.copy(
                    isLoading = false,
                    isRefreshing = false,
                    studentId = studentRes.getOrNull()?.studentId.orEmpty(),
                    studentStatus = studentRes.getOrNull()?.let { it.tdStatus.ifBlank { it.approvals.td } } ?: current.studentStatus,
                    tdStatus = tdRes.getOrDefault(current.tdStatus),
                    sunshineStatus = sunshineRes.getOrDefault(current.sunshineStatus)
                )
            }
        }
    }

    fun setCampus(campus: String) {
        _uiState.update { it.copy(selectedCampus = campus) }
    }

    fun setGapMinutes(minutes: Int) {
        _uiState.update { it.copy(gapMinutes = minutes.coerceIn(1, 15)) }
    }

    fun setEntrancePhoto(uri: Uri?) {
        _uiState.update { it.copy(entrancePhotoUri = uri) }
    }

    fun setExitPhoto(uri: Uri?) {
        _uiState.update { it.copy(exitPhotoUri = uri) }
    }

    fun submitManualTd(context: Context) {
        val state = _uiState.value
        if (state.studentId.isBlank()) {
            viewModelScope.launch { _messageFlow.emit("请先绑定统一认证学号") }
            return
        }
        val entranceUri = state.entrancePhotoUri
        val exitUri = state.exitPhotoUri
        if (entranceUri == null || exitUri == null) {
            viewModelScope.launch { _messageFlow.emit("请先在本机选择入口图和出口图") }
            return
        }

        viewModelScope.launch {
            _uiState.update { it.copy(isSubmittingManual = true) }
            val result = runCatching {
                val entrancePhoto = readBytes(context, entranceUri)
                val exitPhoto = readBytes(context, exitUri)
                val entranceFile = java.io.File.createTempFile("td-entrance-", ".jpg", context.cacheDir)
                val exitFile = java.io.File.createTempFile("td-exit-", ".jpg", context.cacheDir)
                try {
                    entranceFile.writeBytes(entrancePhoto)
                    exitFile.writeBytes(exitPhoto)
                    apiClient.postTdPhotos(entranceFile, exitFile).getOrThrow()
                    apiClient.postTdManual(
                        TdManualRequest(
                            campus = if (state.selectedCampus == "沙河") "shahe" else "xueyuanlu",
                            entranceMachineId = state.entranceMachineId.ifBlank { null },
                            exitMachineId = state.exitMachineId.ifBlank { null },
                            gapSeconds = state.gapMinutes * 60,
                        )
                    ).getOrThrow()
                } finally {
                    entranceFile.delete()
                    exitFile.delete()
                }
            }
            _uiState.update { it.copy(isSubmittingManual = false) }
            result.fold(
                onSuccess = { td ->
                    _messageFlow.emit(td.message ?: "TD 打卡请求已完成")
                    if (td.success) loadData(isRefresh = true)
                },
                onFailure = { err ->
                    _messageFlow.emit(
                        "打卡失败: ${err.message ?: err.javaClass.simpleName}"
                    )
                }
            )
        }
    }

    private fun readBytes(context: Context, uri: Uri): ByteArray {
        return context.contentResolver.openInputStream(uri)?.use { it.readBytes() }
            ?: error("无法读取照片")
    }
}
