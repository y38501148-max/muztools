package com.muzermat.muztools.ui.screens.spark

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.muzermat.muztools.data.api.ApiClient
import com.muzermat.muztools.data.model.DouyinConfig
import com.muzermat.muztools.data.model.DouyinFriend
import com.muzermat.muztools.data.model.DouyinQrResponse
import com.muzermat.muztools.data.model.DouyinSessionResponse
import com.muzermat.muztools.data.model.SparkTarget
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

const val MAX_SPARK_TARGETS = 15


data class SparkUiState(
    val isLoading: Boolean = false,
    val isRefreshing: Boolean = false,
    val accessChecked: Boolean = false,
    val canUseDouyin: Boolean = false,
    val session: DouyinSessionResponse = DouyinSessionResponse(),
    val config: DouyinConfig = DouyinConfig(),
    val friends: List<DouyinFriend> = emptyList(),
    val friendsLoaded: Boolean = false,
    val isLoadingFriends: Boolean = false,
    val friendsCachedAt: String = "",
    val friendSearchQuery: String = "",
    val friendError: String = "",
    val isSubmittingCookie: Boolean = false,
    val isSavingConfig: Boolean = false,
    val isRunningSpark: Boolean = false,
    val runningTargetKey: String = "",
    val showQrLogin: Boolean = false,
    val qrLoginId: String = "",
    val qrImage: String = "",
    val qrStatus: String = "pending",
    val qrError: String = "",
    val qrLoading: Boolean = false
)

class SparkViewModel(
    private val apiClient: ApiClient
) : ViewModel() {

    private val _uiState = MutableStateFlow(SparkUiState())
    val uiState: StateFlow<SparkUiState> = _uiState.asStateFlow()

    private val _messageFlow = MutableSharedFlow<String>()
    val messageFlow: SharedFlow<String> = _messageFlow.asSharedFlow()

    private var qrJob: Job? = null

    fun reset() {
        qrJob?.cancel()
        _uiState.value = SparkUiState()
    }

    fun loadData(isRefresh: Boolean = false) {
        viewModelScope.launch {
            _uiState.update {
                if (isRefresh) it.copy(isRefreshing = true) else it.copy(isLoading = true)
            }

            val user = apiClient.getMe().getOrNull()
            if (user != null && !user.canUseDouyin) {
                _uiState.update {
                    it.copy(isLoading = false, isRefreshing = false, accessChecked = true, canUseDouyin = false)
                }
                return@launch
            }

            val sessionRes = apiClient.getDouyinSession()
            val loadedSession = sessionRes.getOrNull()
            _uiState.update { current ->
                current.copy(
                    isLoading = false,
                    isRefreshing = false,
                    accessChecked = true,
                    canUseDouyin = user?.canUseDouyin ?: sessionRes.isSuccess,
                    session = loadedSession ?: current.session,
                    config = loadedSession?.resolvedConfig() ?: current.config
                )
            }
            if (loadedSession?.valid == true) {
                loadFriends(refresh = false, announce = false)
            }
        }
    }

    fun loadFriends(refresh: Boolean = false, announce: Boolean = true) {
        if (!_uiState.value.session.valid) return
        viewModelScope.launch {
            _uiState.update { it.copy(isLoadingFriends = true, friendError = "") }
            val result = apiClient.getDouyinFriends(refresh)
            result.fold(
                onSuccess = { response ->
                    _uiState.update {
                        it.copy(
                            isLoadingFriends = false,
                            friendsLoaded = true,
                            friends = response.friends,
                            friendsCachedAt = response.cachedAt,
                            friendError = ""
                        )
                    }
                    if (announce) {
                        _messageFlow.emit(if (refresh) "好友列表已刷新" else "已载入好友列表")
                    }
                },
                onFailure = { error ->
                    _uiState.update {
                        it.copy(
                            isLoadingFriends = false,
                            friendsLoaded = true,
                            friendError = error.message ?: "好友列表读取失败"
                        )
                    }
                    if (announce) _messageFlow.emit("好友列表读取失败: ${error.message}")
                }
            )
        }
    }

    fun setFriendSearchQuery(query: String) {
        _uiState.update { it.copy(friendSearchQuery = query) }
    }

    fun startQrLogin() {
        qrJob?.cancel()
        qrJob = viewModelScope.launch {
            _uiState.update {
                it.copy(showQrLogin = true, qrLoading = true, qrError = "", qrImage = "", qrStatus = "pending", qrLoginId = "")
            }
            apiClient.startDouyinQr().fold(
                onSuccess = { qr ->
                    val ready = qr.qrImage.isNotBlank() || qr.status in listOf("failed", "expired", "cancelled", "success")
                    _uiState.update {
                        it.copy(qrLoginId = qr.loginId, qrImage = qr.qrImage, qrStatus = qr.status, qrError = qr.error, qrLoading = !ready && qr.qrImage.isBlank())
                    }
                    if (qr.status == "success" || qr.valid) onQrSuccess(qr)
                    else if (qr.status !in listOf("failed", "expired", "cancelled")) pollQr(qr.loginId)
                },
                onFailure = { error ->
                    _uiState.update { it.copy(qrLoading = false, qrError = error.message ?: "无法生成二维码", qrStatus = "failed") }
                }
            )
        }
    }

    private suspend fun pollQr(loginId: String) {
        repeat(90) {
            delay(2000)
            val qr = apiClient.getDouyinQrStatus(loginId).getOrNull() ?: return@repeat
            val freezeQr = _uiState.value.qrStatus in listOf("scanned", "success")
            _uiState.update {
                it.copy(
                    qrImage = if (freezeQr) it.qrImage else qr.qrImage.ifBlank { it.qrImage },
                    qrStatus = qr.status,
                    qrError = qr.error,
                    qrLoading = qr.qrImage.ifBlank { it.qrImage }.isBlank() && qr.status !in listOf("failed", "expired", "cancelled", "success", "scanned")
                )
            }
            if (qr.status == "success" || qr.valid) {
                onQrSuccess(qr)
                return
            }
            if (qr.status in listOf("failed", "expired", "cancelled")) return
        }
        _uiState.update { it.copy(qrStatus = "expired", qrError = "二维码已过期，请重试") }
    }

    private suspend fun onQrSuccess(qr: DouyinQrResponse) {
        _uiState.update {
            it.copy(qrStatus = "success", qrLoading = false, session = DouyinSessionResponse(valid = true, nickname = qr.nickname.ifBlank { "抖音用户" }))
        }
        _messageFlow.emit("抖音扫码登录成功")
        delay(600)
        closeQrLogin()
        loadData(isRefresh = true)
    }

    fun closeQrLogin() {
        val loginId = _uiState.value.qrLoginId
        qrJob?.cancel()
        qrJob = null
        if (loginId.isNotBlank() && _uiState.value.qrStatus in listOf("pending", "scanned")) {
            viewModelScope.launch { apiClient.cancelDouyinQr(loginId) }
        }
        _uiState.update { it.copy(showQrLogin = false, qrLoading = false, qrError = "", qrStatus = "pending") }
    }

    fun submitCookies(cookieJson: String) {
        if (cookieJson.isBlank()) {
            viewModelScope.launch { _messageFlow.emit("Cookie 不能为空") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isSubmittingCookie = true) }
            val result = apiClient.submitDouyinSession(cookieJson.trim())
            _uiState.update { it.copy(isSubmittingCookie = false) }
            result.fold(
                onSuccess = { session ->
                    _uiState.update {
                        val preserveCache = session.configurationPreserved
                        it.copy(
                            session = session,
                            config = session.resolvedConfig(),
                            friends = if (preserveCache) it.friends else emptyList(),
                            friendsLoaded = preserveCache && it.friendsLoaded,
                            friendsCachedAt = if (preserveCache) it.friendsCachedAt else ""
                        )
                    }
                    _messageFlow.emit(
                        session.message ?: if (session.valid) "抖音 Cookie 校验成功" else "Cookie 状态已更新"
                    )
                    loadData(isRefresh = true)
                },
                onFailure = { error -> _messageFlow.emit("提交失败: ${error.message}") }
            )
        }
    }

    fun toggleAutoSpark(enabled: Boolean) = updateConfig(_uiState.value.config.copy(enabled = enabled))

    fun setDefaultMessage(message: String) {
        _uiState.update { it.copy(config = it.config.copy(defaultMessage = message)) }
    }

    fun setRunHour(hour: Int) {
        _uiState.update { it.copy(config = it.config.copy(hour = hour.coerceIn(0, 23))) }
    }

    fun addTarget(friend: DouyinFriend) {
        if (friend.conversationId.isBlank() || friend.conversationType !in setOf("direct", "group")) {
            viewModelScope.launch { _messageFlow.emit("该会话缺少稳定标识，请主动刷新好友列表后重试") }
            return
        }
        val current = _uiState.value.config
        if (current.targets.size >= MAX_SPARK_TARGETS) {
            viewModelScope.launch { _messageFlow.emit("续火花目标最多可添加 $MAX_SPARK_TARGETS 个") }
            return
        }
        if (current.targets.any { it.identityKey() == friend.identityKey() }) {
            viewModelScope.launch { _messageFlow.emit("该会话已在续火花列表中") }
            return
        }
        updateConfig(
            current.copy(
                targets = current.targets + SparkTarget(
                    name = friend.name,
                    mode = "standard",
                    message = null,
                    conversationId = friend.conversationId,
                    conversationShortId = friend.conversationShortId,
                    conversationType = friend.conversationType
                )
            )
        )
    }

    fun updateTarget(original: SparkTarget, mode: String, message: String) {
        val normalizedMode = if (mode == "custom") "custom" else "standard"
        if (normalizedMode == "custom" && message.isBlank()) {
            viewModelScope.launch { _messageFlow.emit("自定义模式需要填写发送内容") }
            return
        }
        val replacement = original.copy(
            mode = normalizedMode,
            message = message.trim().takeIf { normalizedMode == "custom" && it.isNotBlank() }
        )
        val targets = _uiState.value.config.targets.map { if (it.identityKey() == original.identityKey()) replacement else it }
        updateConfig(_uiState.value.config.copy(targets = targets))
    }

    fun removeTarget(target: SparkTarget) {
        updateConfig(_uiState.value.config.copy(targets = _uiState.value.config.targets.filterNot { it.identityKey() == target.identityKey() }))
    }

    fun updateConfig(config: DouyinConfig = _uiState.value.config) {
        viewModelScope.launch {
            _uiState.update { it.copy(isSavingConfig = true, config = config) }
            apiClient.updateDouyinConfig(config).fold(
                onSuccess = { response ->
                    _uiState.update { it.copy(isSavingConfig = false) }
                    _messageFlow.emit(response.message ?: "火花配置已保存")
                },
                onFailure = { error ->
                    _uiState.update { it.copy(isSavingConfig = false) }
                    _messageFlow.emit("保存配置失败: ${error.message}")
                    loadData(isRefresh = true)
                }
            )
        }
    }

    fun runSparkNow() {
        if (_uiState.value.runningTargetKey.isNotBlank()) return
        _uiState.update { it.copy(isRunningSpark = true) }
        viewModelScope.launch {
            apiClient.runDouyinSpark().fold(
                onSuccess = { response ->
                    _uiState.update { it.copy(isRunningSpark = false) }
                    _messageFlow.emit(response.message ?: "已触发火花发送任务")
                    loadData(isRefresh = true)
                },
                onFailure = { error ->
                    _uiState.update { it.copy(isRunningSpark = false) }
                    _messageFlow.emit("执行失败: ${error.message}")
                }
            )
        }
    }

    fun runSparkTarget(target: SparkTarget) {
        val targetKey = target.identityKey()
        if (
            _uiState.value.isRunningSpark ||
            _uiState.value.runningTargetKey.isNotBlank() ||
            target.conversationId.isBlank() ||
            target.conversationType !in setOf("direct", "group")
        ) return
        _uiState.update { it.copy(runningTargetKey = targetKey) }
        viewModelScope.launch {
            // Save the currently visible default/custom message before the
            // real test send, so the message being tested matches the UI.
            val saveResult = apiClient.updateDouyinConfig(_uiState.value.config)
            if (saveResult.isFailure) {
                _uiState.update { it.copy(runningTargetKey = "") }
                _messageFlow.emit("保存配置失败，未发送测试消息: ${saveResult.exceptionOrNull()?.message}")
                return@launch
            }

            apiClient.runDouyinSparkTarget(targetKey).fold(
                onSuccess = { response ->
                    _uiState.update { it.copy(runningTargetKey = "") }
                    _messageFlow.emit(response.message ?: "单个好友测试发送完成")
                    loadData(isRefresh = true)
                },
                onFailure = { error ->
                    _uiState.update { it.copy(runningTargetKey = "") }
                    _messageFlow.emit("测试发送失败: ${error.message}")
                }
            )
        }
    }
}
