package com.muzermat.muztools.ui.screens.home

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.muzermat.muztools.data.api.ApiClient
import com.muzermat.muztools.data.local.PreferencesManager
import com.muzermat.muztools.data.model.*
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class HomeUiState(
    val isLoading: Boolean = false,
    val isRefreshing: Boolean = false,
    val displayName: String = "",
    val studentStatus: StudentStatusResponse = StudentStatusResponse(),
    val scheduleItems: List<SigninScheduleItem> = emptyList(),
    val autoSigninEnabled: Boolean = false,
    val tdStatus: TdStatusResponse = TdStatusResponse(),
    val sunshineStatus: SunshineStatusResponse = SunshineStatusResponse(),
    val errorMessage: String? = null
)

class HomeViewModel(
    private val apiClient: ApiClient,
    private val prefs: PreferencesManager
) : ViewModel() {

    private val _uiState = MutableStateFlow(
        HomeUiState(
            displayName = prefs.displayName ?: prefs.username ?: "同学"
        )
    )
    val uiState: StateFlow<HomeUiState> = _uiState.asStateFlow()

    fun loadData(isRefresh: Boolean = false) {
        viewModelScope.launch {
            _uiState.update {
                if (isRefresh) it.copy(isRefreshing = true) else it.copy(isLoading = true)
            }

            val userDeferred = async { apiClient.getMe() }
            val studentDeferred = async { apiClient.getStudentStatus() }
            val scheduleDeferred = async { apiClient.getSigninSchedule() }
            val tdDeferred = async { apiClient.getTdStatus() }
            val sunshineDeferred = async { apiClient.getSunshineStatus() }

            val userRes = userDeferred.await()
            val studentRes = studentDeferred.await()
            val scheduleRes = scheduleDeferred.await()
            val tdRes = tdDeferred.await()
            val sunshineRes = sunshineDeferred.await()

            userRes.onSuccess { u ->
                prefs.displayName = u.displayName
                _uiState.update { it.copy(displayName = u.displayName.ifBlank { u.username }) }
            }

            _uiState.update { current ->
                current.copy(
                    isLoading = false,
                    isRefreshing = false,
                    studentStatus = studentRes.getOrDefault(current.studentStatus),
                    scheduleItems = scheduleRes.map { it.schedule }.getOrDefault(current.scheduleItems),
                    autoSigninEnabled = scheduleRes.map { it.enabled }.getOrDefault(current.autoSigninEnabled),
                    tdStatus = tdRes.getOrDefault(current.tdStatus),
                    sunshineStatus = sunshineRes.getOrDefault(current.sunshineStatus)
                )
            }
        }
    }
}
