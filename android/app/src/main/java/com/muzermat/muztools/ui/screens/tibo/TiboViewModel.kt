package com.muzermat.muztools.ui.screens.tibo

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.muzermat.muztools.data.api.ApiClient
import com.muzermat.muztools.data.model.TiboPostItem
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class TiboUiState(
    val isLoading: Boolean = false,
    val items: List<TiboPostItem> = emptyList(),
    val lastChecked: String = "",
    val enabled: Boolean = false,
    val xConnected: Boolean = false,
    val isUpdating: Boolean = false,
    val isSubmittingCookie: Boolean = false,
    val showCookieDialog: Boolean = false,
    val error: String = ""
)

class TiboViewModel(private val apiClient: ApiClient) : ViewModel() {
    private val _uiState = MutableStateFlow(TiboUiState())
    val uiState: StateFlow<TiboUiState> = _uiState.asStateFlow()

    private val _messageFlow = MutableSharedFlow<String>()
    val messageFlow: SharedFlow<String> = _messageFlow.asSharedFlow()

    fun load() {
        if (_uiState.value.isLoading) return
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = "") }
            apiClient.getTiboHistory().fold(
                onSuccess = { data ->
                    _uiState.value = TiboUiState(
                        items = data.items,
                        lastChecked = data.lastChecked,
                        enabled = data.enabled,
                        xConnected = data.xConnected
                    )
                },
                onFailure = { error -> _uiState.update { it.copy(isLoading = false, error = error.message ?: "读取失败") } }
            )
        }
    }

    fun setEnabled(enabled: Boolean) {
        if (_uiState.value.isUpdating) return
        val previous = _uiState.value.enabled
        viewModelScope.launch {
            _uiState.update { it.copy(enabled = enabled, isUpdating = true, error = "") }
            apiClient.updateTiboConfig(enabled).fold(
                onSuccess = { response ->
                    _uiState.update { it.copy(enabled = response.enabled, isUpdating = false) }
                },
                onFailure = { error ->
                    _uiState.update { it.copy(enabled = previous, isUpdating = false, error = error.message ?: "更新推送开关失败") }
                }
            )
        }
    }

    fun showCookieDialog() {
        _uiState.update { it.copy(showCookieDialog = true) }
    }

    fun dismissCookieDialog() {
        _uiState.update { it.copy(showCookieDialog = false) }
    }

    fun submitXCookie(cookieText: String) {
        if (cookieText.isBlank()) {
            viewModelScope.launch { _messageFlow.emit("Cookie 不能为空") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isSubmittingCookie = true) }
            val result = apiClient.submitTiboXSession(cookieText.trim())
            _uiState.update { it.copy(isSubmittingCookie = false) }
            result.fold(
                onSuccess = { response ->
                    _uiState.update { it.copy(showCookieDialog = false, xConnected = response.valid) }
                    _messageFlow.emit(response.message.ifBlank { "X Cookie 导入成功" })
                    load()
                },
                onFailure = { error -> _messageFlow.emit("导入失败: ${error.message}") }
            )
        }
    }

    fun removeXCookie() {
        viewModelScope.launch {
            apiClient.deleteTiboXSession().fold(
                onSuccess = { response ->
                    _uiState.update { it.copy(xConnected = false) }
                    _messageFlow.emit(response.message.ifBlank { "已移除 X Cookie" })
                    load()
                },
                onFailure = { error -> _messageFlow.emit("移除失败: ${error.message}") }
            )
        }
    }
}
