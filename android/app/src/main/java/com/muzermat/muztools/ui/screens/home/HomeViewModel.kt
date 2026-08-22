package com.muzermat.muztools.ui.screens.home

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.muzermat.muztools.data.api.ApiClient
import com.muzermat.muztools.data.local.PreferencesManager
import com.muzermat.muztools.data.model.*
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class HomeUiState(
    val isLoading: Boolean = false,
    val isRefreshing: Boolean = false,
    val hasLoaded: Boolean = false,
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

    companion object {
        private const val CACHE_TTL_MS = 60_000L
    }

    private val _uiState = MutableStateFlow(
        HomeUiState(
            displayName = prefs.displayName ?: prefs.username ?: "同学"
        )
    )
    val uiState: StateFlow<HomeUiState> = _uiState.asStateFlow()

    private var lastLoadedAt = 0L
    private var loadJob: Job? = null

    init {
        loadIfNeeded()
    }

    fun loadIfNeeded() {
        val fresh = _uiState.value.hasLoaded && System.currentTimeMillis() - lastLoadedAt < CACHE_TTL_MS
        if (fresh) return
        loadData(isRefresh = _uiState.value.hasLoaded)
    }

    fun reset() {
        loadJob?.cancel()
        lastLoadedAt = 0L
        _uiState.value = HomeUiState(
            displayName = prefs.displayName ?: prefs.username ?: "同学"
        )
    }

    fun loadData(isRefresh: Boolean = false) {
        if (loadJob?.isActive == true && !isRefresh) return
        loadJob = viewModelScope.launch {
            val hasCache = _uiState.value.hasLoaded
            _uiState.update {
                when {
                    isRefresh || hasCache -> it.copy(isRefreshing = true, errorMessage = null)
                    else -> it.copy(isLoading = true, errorMessage = null)
                }
            }

            val homeRes = apiClient.getHome(cached = !isRefresh)
            if (homeRes.isSuccess) {
                val home = homeRes.getOrThrow()
                prefs.displayName = home.user.displayName.ifBlank { home.user.username }
                lastLoadedAt = System.currentTimeMillis()
                _uiState.update { current ->
                    current.copy(
                        isLoading = false,
                        isRefreshing = false,
                        hasLoaded = true,
                        displayName = prefs.displayName?.ifBlank { "同学" } ?: "同学",
                        studentStatus = home.student,
                        scheduleItems = home.schedule.schedule,
                        autoSigninEnabled = home.schedule.enabled,
                        tdStatus = home.td ?: current.tdStatus,
                        sunshineStatus = home.sunshine ?: current.sunshineStatus
                    )
                }
                return@launch
            }

            val userDeferred = async { apiClient.getMe() }
            val studentDeferred = async { apiClient.getStudentStatus() }
            val scheduleDeferred = async { apiClient.getSigninSchedule(cached = !isRefresh) }
            val studentRes = studentDeferred.await()
            val student = studentRes.getOrNull()
            val tdApproved = student?.let { it.tdStatus == "approved" || it.approvals.td == "approved" } == true
            val tdDeferred = async {
                if (tdApproved) apiClient.getTdStatus() else Result.success(TdStatusResponse())
            }
            val sunshineDeferred = async {
                if (tdApproved) apiClient.getSunshineStatus() else Result.success(SunshineStatusResponse())
            }

            val userRes = userDeferred.await()
            val scheduleRes = scheduleDeferred.await()
            val tdRes = tdDeferred.await()
            val sunshineRes = sunshineDeferred.await()

            userRes.onSuccess { u ->
                prefs.displayName = u.displayName
                _uiState.update { it.copy(displayName = u.displayName.ifBlank { u.username }) }
            }

            lastLoadedAt = System.currentTimeMillis()
            _uiState.update { current ->
                current.copy(
                    isLoading = false,
                    isRefreshing = false,
                    hasLoaded = true,
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
