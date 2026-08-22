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
import java.io.File
import java.io.FileOutputStream

data class TdUiState(
    val isLoading: Boolean = false,
    val isRefreshing: Boolean = false,
    val tdStatus: TdStatusResponse = TdStatusResponse(),
    val sunshineStatus: SunshineStatusResponse = SunshineStatusResponse(),
    val selectedCampus: String = "学院路",
    val entranceMachineId: String = "",
    val exitMachineId: String = "",
    val gapMinutes: Int = 4,
    val entrancePhotoUri: Uri? = null,
    val exitPhotoUri: Uri? = null,
    val isSubmittingManual: Boolean = false,
    val isUploadingPhotos: Boolean = false
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

            val tdDeferred = async { apiClient.getTdStatus() }
            val sunshineDeferred = async { apiClient.getSunshineStatus() }

            val tdRes = tdDeferred.await()
            val sunshineRes = sunshineDeferred.await()

            _uiState.update { current ->
                current.copy(
                    isLoading = false,
                    isRefreshing = false,
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
        _uiState.update { it.copy(gapMinutes = minutes.coerceIn(1, 60)) }
    }

    fun setEntrancePhoto(uri: Uri?) {
        _uiState.update { it.copy(entrancePhotoUri = uri) }
    }

    fun setExitPhoto(uri: Uri?) {
        _uiState.update { it.copy(exitPhotoUri = uri) }
    }

    fun uploadPhotos(context: Context) {
        val entranceUri = _uiState.value.entrancePhotoUri
        val exitUri = _uiState.value.exitPhotoUri

        if (entranceUri == null && exitUri == null) {
            viewModelScope.launch { _messageFlow.emit("请先选择至少一张打卡机照片") }
            return
        }

        viewModelScope.launch {
            _uiState.update { it.copy(isUploadingPhotos = true) }
            val entranceFile = entranceUri?.let { uriToFile(context, it, "entrance.jpg") }
            val exitFile = exitUri?.let { uriToFile(context, it, "exit.jpg") }

            val res = apiClient.postTdPhotos(entranceFile, exitFile)
            _uiState.update { it.copy(isUploadingPhotos = false) }

            res.fold(
                onSuccess = { resp ->
                    _messageFlow.emit(resp.message ?: "照片上传识别成功")
                },
                onFailure = { err ->
                    _messageFlow.emit("照片上传失败: ${err.message}")
                }
            )
        }
    }

    fun submitManualTd() {
        val state = _uiState.value
        viewModelScope.launch {
            _uiState.update { it.copy(isSubmittingManual = true) }
            val req = TdManualRequest(
                campus = state.selectedCampus,
                entranceMachineId = state.entranceMachineId.ifBlank { null },
                exitMachineId = state.exitMachineId.ifBlank { null },
                gapSeconds = state.gapMinutes * 60
            )

            val res = apiClient.postTdManual(req)
            _uiState.update { it.copy(isSubmittingManual = false) }

            res.fold(
                onSuccess = { resp ->
                    _messageFlow.emit(resp.message ?: "手动打卡任务已触发")
                    loadData(isRefresh = true)
                },
                onFailure = { err ->
                    _messageFlow.emit("打卡失败: ${err.message}")
                }
            )
        }
    }

    private fun uriToFile(context: Context, uri: Uri, fileName: String): File? {
        return try {
            val file = File(context.cacheDir, fileName)
            context.contentResolver.openInputStream(uri)?.use { input ->
                FileOutputStream(file).use { output ->
                    input.copyTo(output)
                }
            }
            file
        } catch (e: Exception) {
            null
        }
    }
}
