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
    val isTogglingAuto: Boolean = false,
    val canManageInvites: Boolean = false,
    val canUseDouyin: Boolean = false,
    val issuedInviteCode: String = "",
    val inviteRemaining: Int = 0,
    val isIssuingInvite: Boolean = false
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
            val userDeferred = async { apiClient.getMe() }

            val studentRes = studentDeferred.await()
            val scheduleRes = scheduleDeferred.await()
            val userRes = userDeferred.await()

            _uiState.update { current ->
                val student = studentRes.getOrNull()
                val schedule = scheduleRes.getOrNull()
                current.copy(
                    isLoading = false,
                    isRefreshing = false,
                    studentStatus = student ?: current.studentStatus,
                    scheduleItems = schedule?.schedule ?: current.scheduleItems,
                    isAutoSigninEnabled = schedule?.enabled ?: student?.autoSignin ?: current.isAutoSigninEnabled,
                    canManageInvites = userRes.getOrNull()?.canManageInvites ?: current.canManageInvites,
                    canUseDouyin = userRes.getOrNull()?.canUseDouyin ?: current.canUseDouyin
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

    fun issueInvite() {
        viewModelScope.launch {
            _uiState.update { it.copy(isIssuingInvite = true) }
            apiClient.issueInvite().fold(
                onSuccess = { result ->
                    _uiState.update { it.copy(isIssuingInvite = false, issuedInviteCode = result.code, inviteRemaining = result.remaining) }
                },
                onFailure = { error ->
                    _uiState.update { it.copy(isIssuingInvite = false) }
                    _messageFlow.emit("获取邀请码失败: ${error.message}")
                }
            )
        }
    }

    fun clearIssuedInvite() {
        _uiState.update { it.copy(issuedInviteCode = "") }
    }

    fun toggleAutoSignin(enable: Boolean) {
        viewModelScope.launch {
            _uiState.update { it.copy(isTogglingAuto = true) }
            val res = apiClient.setAutoSignin(enable)
            _uiState.update { it.copy(isTogglingAuto = false) }
            res.fold(
                onSuccess = { resp ->
                    _uiState.update {
                        it.copy(
                            isAutoSigninEnabled = enable,
                            studentStatus = it.studentStatus.copy(autoSignin = enable)
                        )
                    }
                    _messageFlow.emit(if (enable) "自动签到已开启" else "自动签到已关闭")
                },
                onFailure = { err ->
                    _messageFlow.emit("切换失败: ${err.message}")
                }
            )
        }
    }
}
