package com.muzermat.muztools.ui.screens.auth

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.muzermat.muztools.data.api.ApiClient
import com.muzermat.muztools.data.local.PreferencesManager
import com.muzermat.muztools.data.model.LoginRequest
import com.muzermat.muztools.data.model.RegisterRequest
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class AuthUiState(
    val username: String = "",
    val displayName: String = "",
    val password: String = "",
    val isLoading: Boolean = false,
    val errorMessage: String? = null,
    val isLoggedIn: Boolean = false
)

class AuthViewModel(
    private val apiClient: ApiClient,
    private val prefs: PreferencesManager
) : ViewModel() {

    private val _uiState = MutableStateFlow(
        AuthUiState(
            username = prefs.username ?: "",
            displayName = prefs.displayName ?: "",
            isLoggedIn = !prefs.token.isNullOrBlank()
        )
    )
    val uiState: StateFlow<AuthUiState> = _uiState.asStateFlow()

    var serverUrl: String
        get() = prefs.serverUrl
        set(value) {
            prefs.serverUrl = value
        }

    fun onUsernameChange(name: String) {
        _uiState.update { it.copy(username = name, errorMessage = null) }
    }

    fun onDisplayNameChange(name: String) {
        _uiState.update { it.copy(displayName = name, errorMessage = null) }
    }

    fun onPasswordChange(pwd: String) {
        _uiState.update { it.copy(password = pwd, errorMessage = null) }
    }

    fun clearError() {
        _uiState.update { it.copy(errorMessage = null) }
    }

    fun updateServerUrl(url: String) {
        prefs.serverUrl = url
    }

    fun login() {
        val state = _uiState.value
        if (state.username.isBlank() || state.password.isBlank()) {
            _uiState.update { it.copy(errorMessage = "请输入用户名和密码") }
            return
        }

        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, errorMessage = null) }
            val res = apiClient.login(LoginRequest(state.username.trim(), state.password))
            res.fold(
                onSuccess = { authRes ->
                    if (!authRes.token.isNullOrBlank()) {
                        prefs.token = authRes.token
                        prefs.username = authRes.user?.username ?: state.username.trim()
                        prefs.displayName = authRes.user?.displayName ?: ""
                        // 注册设备
                        apiClient.registerDevice(prefs.deviceId)
                        _uiState.update { it.copy(isLoading = false, isLoggedIn = true) }
                    } else {
                        _uiState.update {
                            it.copy(
                                isLoading = false,
                                errorMessage = authRes.detail ?: authRes.message ?: "登录失败，未返回 Token"
                            )
                        }
                    }
                },
                onFailure = { error ->
                    _uiState.update {
                        it.copy(
                            isLoading = false,
                            errorMessage = error.message ?: "网络请求失败"
                        )
                    }
                }
            )
        }
    }

    fun register() {
        val state = _uiState.value
        if (state.username.isBlank() || state.password.isBlank() || state.displayName.isBlank()) {
            _uiState.update { it.copy(errorMessage = "请完整填写注册信息") }
            return
        }

        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, errorMessage = null) }
            val res = apiClient.register(
                RegisterRequest(
                    username = state.username.trim(),
                    password = state.password,
                    displayName = state.displayName.trim()
                )
            )
            res.fold(
                onSuccess = { authRes ->
                    if (!authRes.token.isNullOrBlank()) {
                        prefs.token = authRes.token
                        prefs.username = authRes.user?.username ?: state.username.trim()
                        prefs.displayName = authRes.user?.displayName ?: state.displayName.trim()
                        // 注册设备
                        apiClient.registerDevice(prefs.deviceId)
                        _uiState.update { it.copy(isLoading = false, isLoggedIn = true) }
                    } else {
                        // 尝试自动登录
                        login()
                    }
                },
                onFailure = { error ->
                    _uiState.update {
                        it.copy(
                            isLoading = false,
                            errorMessage = error.message ?: "注册失败"
                        )
                    }
                }
            )
        }
    }

    fun logout() {
        prefs.clearAuth()
        _uiState.update {
            it.copy(
                isLoggedIn = false,
                password = "",
                errorMessage = null
            )
        }
    }
}
