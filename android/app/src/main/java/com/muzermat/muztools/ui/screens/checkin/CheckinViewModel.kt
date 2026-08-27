package com.muzermat.muztools.ui.screens.checkin

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.muzermat.muztools.data.api.ApiClient
import com.muzermat.muztools.data.model.CheckinActivity
import com.muzermat.muztools.data.model.CheckinConfigResponse
import com.muzermat.muztools.data.model.CheckinProvider
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class CheckinUiState(
    val isLoading: Boolean = false,
    val isSavingToken: Boolean = false,
    val isPreviewing: Boolean = false,
    val isSigning: Boolean = false,
    val providers: List<CheckinProvider> = emptyList(),
    val selectedProviderId: String = "",
    val config: CheckinConfigResponse = CheckinConfigResponse(),
    val isEditingToken: Boolean = false,
    val activityCode: String = "",
    val activity: CheckinActivity? = null,
    val fieldValues: Map<String, String> = emptyMap(),
    val error: String = ""
)

class CheckinViewModel(private val apiClient: ApiClient) : ViewModel() {
    private val _uiState = MutableStateFlow(CheckinUiState())
    val uiState: StateFlow<CheckinUiState> = _uiState.asStateFlow()

    private val _messageFlow = MutableSharedFlow<String>()
    val messageFlow: SharedFlow<String> = _messageFlow.asSharedFlow()

    fun load() {
        if (_uiState.value.isLoading || _uiState.value.providers.isNotEmpty()) return
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = "") }
            apiClient.getCheckinProviders().fold(
                onSuccess = { response ->
                    val firstId = response.providers.firstOrNull()?.id.orEmpty()
                    _uiState.update {
                        it.copy(
                            isLoading = false,
                            providers = response.providers,
                            selectedProviderId = firstId,
                            error = if (firstId.isBlank()) "服务端暂未配置签到平台" else ""
                        )
                    }
                    if (firstId.isNotBlank()) loadConfig(firstId)
                },
                onFailure = { error ->
                    _uiState.update { it.copy(isLoading = false, error = error.message ?: "读取签到平台失败") }
                }
            )
        }
    }

    fun reset() {
        _uiState.value = CheckinUiState()
    }

    fun selectProvider(providerId: String) {
        if (providerId == _uiState.value.selectedProviderId) return
        _uiState.update {
            it.copy(
                selectedProviderId = providerId,
                config = CheckinConfigResponse(provider = providerId),
                isEditingToken = false,
                activity = null,
                fieldValues = emptyMap(),
                error = ""
            )
        }
        loadConfig(providerId)
    }

    private fun loadConfig(providerId: String = _uiState.value.selectedProviderId) {
        if (providerId.isBlank()) return
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = "") }
            apiClient.getCheckinConfig(providerId).fold(
                onSuccess = { config ->
                    _uiState.update {
                        it.copy(
                            isLoading = false,
                            config = config,
                            isEditingToken = !config.connected
                        )
                    }
                },
                onFailure = { error ->
                    _uiState.update { it.copy(isLoading = false, error = error.message ?: "读取平台配置失败") }
                }
            )
        }
    }

    fun beginTokenEdit() {
        _uiState.update { it.copy(isEditingToken = true) }
    }

    fun cancelTokenEdit() {
        _uiState.update { it.copy(isEditingToken = !it.config.connected) }
    }

    fun saveToken(token: String, onSaved: () -> Unit = {}) {
        val providerId = _uiState.value.selectedProviderId
        if (providerId.isBlank() || token.isBlank() || _uiState.value.isSavingToken) return
        viewModelScope.launch {
            _uiState.update { it.copy(isSavingToken = true, error = "") }
            apiClient.saveCheckinToken(providerId, token.trim()).fold(
                onSuccess = { config ->
                    _uiState.update {
                        it.copy(
                            isSavingToken = false,
                            config = config,
                            isEditingToken = false,
                            activity = null,
                            fieldValues = emptyMap()
                        )
                    }
                    onSaved()
                    _messageFlow.emit(config.message.ifBlank { "Token 已保存并验证" })
                },
                onFailure = { error ->
                    _uiState.update { it.copy(isSavingToken = false, error = error.message ?: "Token 验证失败") }
                }
            )
        }
    }

    fun updateActivityCode(value: String) {
        _uiState.update { it.copy(activityCode = value, activity = null, fieldValues = emptyMap(), error = "") }
    }

    fun preview() {
        val state = _uiState.value
        val code = state.activityCode.trim()
        if (state.selectedProviderId.isBlank() || code.isBlank() || state.isPreviewing) return
        viewModelScope.launch {
            _uiState.update { it.copy(isPreviewing = true, activity = null, fieldValues = emptyMap(), error = "") }
            apiClient.previewCheckin(state.selectedProviderId, code).fold(
                onSuccess = { response ->
                    _uiState.update {
                        it.copy(
                            isPreviewing = false,
                            activity = response.activity,
                            fieldValues = response.activity.fields.associate { field -> field.title to "" }
                        )
                    }
                },
                onFailure = { error ->
                    _uiState.update { it.copy(isPreviewing = false, error = error.message ?: "读取活动失败") }
                }
            )
        }
    }

    fun updateField(name: String, value: String) {
        _uiState.update { state -> state.copy(fieldValues = state.fieldValues + (name to value), error = "") }
    }

    fun sign() {
        val state = _uiState.value
        val activity = state.activity ?: return
        if (state.isSigning) return
        val missing = activity.fields.firstOrNull { it.required && state.fieldValues[it.title].isNullOrBlank() }
        if (missing != null) {
            viewModelScope.launch { _messageFlow.emit("请填写${missing.title}") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isSigning = true, error = "") }
            apiClient.submitCheckin(
                provider = state.selectedProviderId,
                code = activity.code.ifBlank { state.activityCode.trim() },
                values = state.fieldValues
            ).fold(
                onSuccess = { response ->
                    _uiState.update { it.copy(isSigning = false) }
                    _messageFlow.emit(response.message.ifBlank { "签到成功" })
                },
                onFailure = { error ->
                    _uiState.update { it.copy(isSigning = false, error = error.message ?: "签到失败") }
                }
            )
        }
    }
}
