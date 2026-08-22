package com.muzermat.muztools.ui.screens.spark

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.muzermat.muztools.data.api.ApiClient
import com.muzermat.muztools.data.model.DouyinConfig
import com.muzermat.muztools.data.model.DouyinSessionResponse
import com.muzermat.muztools.data.model.SparkTarget
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class SparkUiState(
    val isLoading: Boolean = false,
    val isRefreshing: Boolean = false,
    val session: DouyinSessionResponse = DouyinSessionResponse(),
    val config: DouyinConfig = DouyinConfig(),
    val studentStatus: String = "unbound",
    val isSubmittingCookie: Boolean = false,
    val isSavingConfig: Boolean = false,
    val isRunningSpark: Boolean = false
)

class SparkViewModel(
    private val apiClient: ApiClient
) : ViewModel() {

    private val _uiState = MutableStateFlow(SparkUiState())
    val uiState: StateFlow<SparkUiState> = _uiState.asStateFlow()

    private val _messageFlow = MutableSharedFlow<String>()
    val messageFlow: SharedFlow<String> = _messageFlow.asSharedFlow()

    fun loadData(isRefresh: Boolean = false) {
        viewModelScope.launch {
            _uiState.update {
                if (isRefresh) it.copy(isRefreshing = true) else it.copy(isLoading = true)
            }

            val studentRes = apiClient.getStudentStatus()
            val sessionRes = apiClient.getDouyinSession()
            _uiState.update { current ->
                current.copy(
                    isLoading = false,
                    isRefreshing = false,
                    studentStatus = studentRes.getOrNull()?.status ?: current.studentStatus,
                    session = sessionRes.getOrDefault(current.session)
                )
            }
        }
    }

    private fun ensureApproved(): Boolean {
        val approved = _uiState.value.studentStatus == "approved" || _uiState.value.studentStatus == "已通过"
        if (!approved) {
            viewModelScope.launch { _messageFlow.emit("学生认证尚未通过审批，无法使用抖音续火花") }
        }
        return approved
    }

    fun submitCookies(cookieJson: String) {
        if (!ensureApproved()) return
        if (cookieJson.isBlank()) {
            viewModelScope.launch { _messageFlow.emit("Cookie 不能为空") }
            return
        }

        viewModelScope.launch {
            _uiState.update { it.copy(isSubmittingCookie = true) }
            val res = apiClient.submitDouyinSession(cookieJson.trim())
            _uiState.update { it.copy(isSubmittingCookie = false) }

            res.fold(
                onSuccess = { session ->
                    _uiState.update { it.copy(session = session) }
                    _messageFlow.emit(if (session.valid) "抖音 Session 校验成功" else "Session 状态已更新")
                },
                onFailure = { err ->
                    _messageFlow.emit("提交失败: ${err.message}")
                }
            )
        }
    }

    fun toggleAutoSpark(enabled: Boolean) {
        if (!ensureApproved()) return
        val newConfig = _uiState.value.config.copy(enabled = enabled)
        updateConfig(newConfig)
    }

    fun setDefaultMessage(msg: String) {
        _uiState.update { it.copy(config = it.config.copy(defaultMessage = msg)) }
    }

    fun setRunHour(hour: Int) {
        _uiState.update { it.copy(config = it.config.copy(hour = hour.coerceIn(0, 23))) }
    }

    fun addTarget(name: String, message: String?) {
        if (name.isBlank()) return
        val currentTargets = _uiState.value.config.targets.toMutableList()
        currentTargets.add(SparkTarget(name = name.trim(), message = message?.takeIf { it.isNotBlank() }))
        val newConfig = _uiState.value.config.copy(targets = currentTargets)
        updateConfig(newConfig)
    }

    fun removeTarget(target: SparkTarget) {
        val currentTargets = _uiState.value.config.targets.filterNot { it.name == target.name }
        val newConfig = _uiState.value.config.copy(targets = currentTargets)
        updateConfig(newConfig)
    }

    fun updateConfig(config: DouyinConfig = _uiState.value.config) {
        if (!ensureApproved()) return
        viewModelScope.launch {
            _uiState.update { it.copy(isSavingConfig = true, config = config) }
            val res = apiClient.updateDouyinConfig(config)
            _uiState.update { it.copy(isSavingConfig = false) }
            res.fold(
                onSuccess = { resp ->
                    _messageFlow.emit(resp.message ?: "火花配置已保存")
                },
                onFailure = { err ->
                    _messageFlow.emit("保存配置失败: ${err.message}")
                }
            )
        }
    }

    fun runSparkNow() {
        if (!ensureApproved()) return
        viewModelScope.launch {
            _uiState.update { it.copy(isRunningSpark = true) }
            val res = apiClient.runDouyinSpark()
            _uiState.update { it.copy(isRunningSpark = false) }

            res.fold(
                onSuccess = { resp ->
                    _messageFlow.emit(resp.message ?: "已触发火花发送任务")
                },
                onFailure = { err ->
                    _messageFlow.emit("执行失败: ${err.message}")
                }
            )
        }
    }
}
