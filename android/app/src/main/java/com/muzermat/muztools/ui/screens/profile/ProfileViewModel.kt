package com.muzermat.muztools.ui.screens.profile

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.muzermat.muztools.data.api.ApiClient
import com.muzermat.muztools.data.local.PreferencesManager
import com.muzermat.muztools.data.model.NotificationItem
import com.muzermat.muztools.data.model.StudentStatusResponse
import com.muzermat.muztools.data.model.User
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class ProfileUiState(
    val isLoading: Boolean = false,
    val isRefreshing: Boolean = false,
    val user: User? = null,
    val studentStatus: StudentStatusResponse = StudentStatusResponse(),
    val notifications: List<NotificationItem> = emptyList(),
    val serverUrl: String = ""
)

class ProfileViewModel(
    private val apiClient: ApiClient,
    private val prefs: PreferencesManager
) : ViewModel() {

    private val _uiState = MutableStateFlow(
        ProfileUiState(
            user = User(username = prefs.username ?: "", displayName = prefs.displayName ?: ""),
            serverUrl = prefs.serverUrl
        )
    )
    val uiState: StateFlow<ProfileUiState> = _uiState.asStateFlow()

    private val _messageFlow = MutableSharedFlow<String>()
    val messageFlow: SharedFlow<String> = _messageFlow.asSharedFlow()

    fun loadData(isRefresh: Boolean = false) {
        viewModelScope.launch {
            _uiState.update {
                if (isRefresh) it.copy(isRefreshing = true) else it.copy(isLoading = true)
            }

            val userDeferred = async { apiClient.getMe() }
            val studentDeferred = async { apiClient.getStudentStatus() }
            val notifDeferred = async { apiClient.getNotifications() }

            val userRes = userDeferred.await()
            val studentRes = studentDeferred.await()
            val notifRes = notifDeferred.await()

            userRes.onSuccess { u ->
                prefs.displayName = u.displayName
                prefs.username = u.username
            }

            _uiState.update { current ->
                current.copy(
                    isLoading = false,
                    isRefreshing = false,
                    user = userRes.getOrNull() ?: current.user,
                    studentStatus = studentRes.getOrDefault(current.studentStatus),
                    notifications = notifRes.getOrDefault(current.notifications),
                    serverUrl = prefs.serverUrl
                )
            }
        }
    }

    fun updateServerUrl(url: String) {
        prefs.serverUrl = url
        _uiState.update { it.copy(serverUrl = prefs.serverUrl) }
    }

    fun logout() {
        prefs.clearAuth()
    }
}
