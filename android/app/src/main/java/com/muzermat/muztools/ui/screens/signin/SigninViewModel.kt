package com.muzermat.muztools.ui.screens.signin

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.muzermat.muztools.data.api.ApiClient
import com.muzermat.muztools.data.model.SigninScheduleItem
import com.muzermat.muztools.data.model.StudentBindRequest
import com.muzermat.muztools.data.model.StudentStatusResponse
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class SigninUiState(
    val isLoading: Boolean = false,
    val isRefreshing: Boolean = false,
    val studentStatus: StudentStatusResponse = StudentStatusResponse(),
    val isAutoSigninEnabled: Boolean = false,
    val scheduleItems: List<SigninScheduleItem> = emptyList(),
    val isBinding: Boolean = false,
    val isTogglingAuto: Boolean = false
)

class SigninViewModel(
    private val apiClient: ApiClient
) : ViewModel() {

    private val _uiState = MutableStateFlow(SigninUiState())
    val uiState: StateFlow<SigninUiState> = _uiState.asStateFlow()

    private val _messageFlow = MutableSharedFlow<String>()
    val messageFlow: SharedFlow<String> = _messageFlow.asSharedFlow()

    fun loadData(isRefresh: Boolean = false) {
        viewModelScope.launch {
            _uiState.update {
                if (isRefresh) it.copy(isRefreshing = true) else it.copy(isLoading = true)
            }

            val studentDeferred = async { apiClient.getStudentStatus() }
            val scheduleDeferred = async { apiClient.getSigninSchedule() }

            val studentRes = studentDeferred.await()
            val scheduleRes = scheduleDeferred.await()

            _uiState.update { current ->
                current.copy(
                    isLoading = false,
                    isRefreshing = false,
                    studentStatus = studentRes.getOrDefault(current.studentStatus),
                    scheduleItems = scheduleRes.map { it.schedule }.getOrDefault(current.scheduleItems),
                    isAutoSigninEnabled = scheduleRes.map { it.enabled }.getOrDefault(current.isAutoSigninEnabled)
                )
            }
        }
    }

    fun bindStudent(studentId: String, password: String) {
        if (studentId.isBlank() || password.isBlank()) {
            viewModelScope.launch { _messageFlow.emit("学号和密码不能为空") }
            return
        }

        viewModelScope.launch {
            _uiState.update { it.copy(isBinding = true) }
            val res = apiClient.bindStudent(StudentBindRequest(studentId.trim(), password))
            _uiState.update { it.copy(isBinding = false) }
            res.fold(
                onSuccess = { resp ->
                    _messageFlow.emit(resp.message ?: "绑定请求已提交")
                    loadData(isRefresh = true)
                },
                onFailure = { err ->
                    _messageFlow.emit("绑定失败: ${err.message}")
                }
            )
        }
    }

    fun toggleAutoSignin(enable: Boolean) {
        val currentStatus = _uiState.value.studentStatus.status
        val isApproved = currentStatus == "approved" || currentStatus == "已通过"

        if (enable && !isApproved) {
            viewModelScope.launch {
                _messageFlow.emit("学生认证未通过，审批完成后方可开启自动签到")
            }
            return
        }

        viewModelScope.launch {
            _uiState.update { it.copy(isTogglingAuto = true) }
            val res = apiClient.setAutoSignin(enable)
            _uiState.update { it.copy(isTogglingAuto = false) }
            res.fold(
                onSuccess = { resp ->
                    _uiState.update { it.copy(isAutoSigninEnabled = enable) }
                    _messageFlow.emit(if (enable) "自动签到已开启" else "自动签到已关闭")
                },
                onFailure = { err ->
                    _messageFlow.emit("切换失败: ${err.message}")
                }
            )
        }
    }
}
