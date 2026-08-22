package com.muzermat.muztools.ui.screens.auth

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.muzermat.muztools.data.api.ApiClient
import com.muzermat.muztools.data.local.Credentials
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
    val rememberPassword: Boolean = false,
    val autoLogin: Boolean = false,
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
            password = if (prefs.rememberPassword || prefs.autoLogin) prefs.password.orEmpty() else "",
            rememberPassword = prefs.rememberPassword || prefs.autoLogin,
            autoLogin = prefs.autoLogin,
            isLoggedIn = prefs.autoLogin && !prefs.token.isNullOrBlank()
        )
    )
    val uiState: StateFlow<AuthUiState> = _uiState.asStateFlow()

    var serverUrl: String
        get() = prefs.serverUrl
        set(value) {
            prefs.serverUrl = value
        }

    init {
        val state = _uiState.value
        if (!state.isLoggedIn && state.autoLogin && state.username.isNotBlank() && state.password.isNotBlank()) {
            login()
        }
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

    fun onRememberPasswordChange(enabled: Boolean) {
        val autoLogin = if (enabled) _uiState.value.autoLogin else false
        _uiState.update { it.copy(rememberPassword = enabled, autoLogin = autoLogin, errorMessage = null) }
        prefs.rememberPassword = enabled
        if (!enabled) {
            prefs.autoLogin = false
            prefs.password = null
        }
    }

    fun onAutoLoginChange(enabled: Boolean) {
        _uiState.update {
            it.copy(
                autoLogin = enabled,
                rememberPassword = if (enabled) true else it.rememberPassword,
                errorMessage = null
            )
        }
        prefs.autoLogin = enabled
        if (enabled) prefs.rememberPassword = true
    }

    fun clearError() {
        _uiState.update { it.copy(errorMessage = null) }
    }

    fun updateServerUrl(url: String) {
        prefs.serverUrl = url
    }

    fun login() {
        val state = _uiState.value
        Credentials.validateUsername(state.username)?.let { message ->
            _uiState.update { it.copy(errorMessage = message) }
            return
        }
        if (state.password.isBlank()) {
            _uiState.update { it.copy(errorMessage = "请输入密码") }
            return
        }

        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, errorMessage = null) }
            val res = apiClient.login(LoginRequest(state.username.trim(), state.password))
            handleAuthResult(res, state, isRegister = false)
        }
    }

    fun register() {
        val state = _uiState.value
        Credentials.validateUsername(state.username)?.let { message ->
            _uiState.update { it.copy(errorMessage = message) }
            return
        }
        Credentials.validatePassword(state.password)?.let { message ->
            _uiState.update { it.copy(errorMessage = message) }
            return
        }
        if (state.displayName.isBlank()) {
            _uiState.update { it.copy(errorMessage = "请填写显示名") }
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
            handleAuthResult(res, state, isRegister = true)
        }
    }

    private suspend fun handleAuthResult(
        res: Result<com.muzermat.muztools.data.model.AuthResponse>,
        state: AuthUiState,
        isRegister: Boolean
    ) {
        res.fold(
            onSuccess = { authRes ->
                if (!authRes.token.isNullOrBlank()) {
                    prefs.token = authRes.token
                    val username = authRes.user?.username ?: state.username.trim()
                    val displayName = authRes.user?.displayName ?: state.displayName
                    prefs.persistLogin(
                        username = username,
                        displayName = displayName,
                        rawPassword = state.password,
                        remember = state.rememberPassword,
                        autoLoginEnabled = state.autoLogin
                    )
                    apiClient.registerDevice(prefs.deviceId)
                    _uiState.update { it.copy(isLoading = false, isLoggedIn = true, username = username, displayName = displayName) }
                } else if (isRegister) {
                    login()
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
                        errorMessage = error.message ?: if (isRegister) "注册失败" else "网络请求失败"
                    )
                }
            }
        )
    }

    fun logout() {
        prefs.clearAuth()
        _uiState.update {
            it.copy(
                isLoggedIn = false,
                password = if (prefs.rememberPassword) prefs.password.orEmpty() else "",
                username = prefs.username ?: it.username,
                errorMessage = null
            )
        }
    }
}
