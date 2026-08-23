package com.muzermat.muztools.data.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class User(
    val username: String,
    @SerialName("display_name") val displayName: String = "",
    val role: String? = null,
    @SerialName("can_manage_invites") val canManageInvites: Boolean = false,
    @SerialName("can_use_douyin") val canUseDouyin: Boolean = false
)

@Serializable
data class AuthResponse(
    val token: String? = null,
    val user: User? = null,
    val detail: String? = null,
    val message: String? = null
)

@Serializable
data class RegisterRequest(
    val username: String,
    val password: String,
    @SerialName("display_name") val displayName: String,
    @SerialName("invite_code") val inviteCode: String
)

@Serializable
data class LoginRequest(
    val username: String,
    val password: String
)


@Serializable
data class TransportPublicKey(
    val algorithm: String = "RSA-PKCS1-v1_5",
    @SerialName("key_id") val keyId: String = "",
    @SerialName("modulus_hex") val modulusHex: String,
    val exponent: Long,
    @SerialName("key_size") val keySize: Int
)

@Serializable
data class EncryptedCredentialRequest(
    val encrypted: Map<String, String>,
    @SerialName("keep_login") val keepLogin: Boolean = false
)

@Serializable
data class InviteIssueResponse(
    val success: Boolean = false,
    val code: String = "",
    val remaining: Int = 0,
    val detail: String? = null
)

@Serializable
data class DeviceRegisterRequest(
    @SerialName("device_id") val deviceId: String
)

@Serializable
data class FcmTokenRequest(
    val token: String,
    @SerialName("device_id") val deviceId: String = "",
    @SerialName("app_version") val appVersion: String = ""
)

@Serializable
data class StudentBindRequest(
    @SerialName("student_id") val studentId: String,
    val password: String
)

@Serializable
data class FeatureApprovals(
    val signin: String = "none",
    val td: String = "none",
    val spark: String = "none"
)

@Serializable
data class StudentStatusResponse(
    val status: String = "unbound",
    @SerialName("student_id") val studentId: String? = null,
    @SerialName("display_name") val displayName: String? = null,
    @SerialName("auto_signin") val autoSignin: Boolean = false,
    val reason: String? = null,
    val detail: String? = null,
    val approvals: FeatureApprovals = FeatureApprovals(),
    @SerialName("signin_status") val signinStatus: String = "none",
    @SerialName("td_status") val tdStatus: String = "none",
    @SerialName("spark_status") val sparkStatus: String = "none"
)

@Serializable
data class FeatureRequest(
    val feature: String
)

@Serializable
data class SigninScheduleItem(
    @SerialName("course_name") val courseName: String,
    val classroom: String? = null,
    @SerialName("start_time") val startTime: String? = null,
    @SerialName("end_time") val endTime: String? = null,
    val status: String? = null, // signed, pending, missed, etc.
    @SerialName("scheduled_time") val scheduledTime: String? = null,
    val teacher: String? = null,
    @SerialName("course_id") val courseId: String? = null
)

@Serializable
data class SigninScheduleResponse(
    val enabled: Boolean = false,
    val schedule: List<SigninScheduleItem> = emptyList(),
    val message: String? = null
)

@Serializable
data class AutoSigninToggleRequest(
    val enabled: Boolean
)

@Serializable
data class TdStatusResponse(
    @SerialName("semester_count") val semesterCount: Int = 0,
    @SerialName("target_count") val targetCount: Int = 32,
    @SerialName("last_run_time") val lastRunTime: String? = null,
    val status: String? = null
)

@Serializable
data class SunshineStatusResponse(
    val count: Int = 0,
    @SerialName("target_count") val targetCount: Int = 16,
    @SerialName("last_sync_time") val lastSyncTime: String? = null
)

@Serializable
data class TdManualRequest(
    val campus: String, // 学院路 / 沙河
    @SerialName("entrance_machine_id") val entranceMachineId: String? = null,
    @SerialName("exit_machine_id") val exitMachineId: String? = null,
    @SerialName("gap_seconds") val gapSeconds: Int = 240
)

@Serializable
data class HybridEncryptedSecret(
    val key: String,
    val nonce: String,
    val ciphertext: String
)

@Serializable
data class DouyinSessionRequest(
    @SerialName("encrypted_secret") val encryptedSecret: HybridEncryptedSecret
)

@Serializable
data class DouyinRunTargetRequest(
    @SerialName("target_key") val targetKey: String
)

@Serializable
data class DouyinTargetStatus(
    val name: String = "",
    val status: String = "",
    val error: String = "",
    @SerialName("last_attempt") val lastAttempt: String = "",
    @SerialName("last_success") val lastSuccess: String = ""
)

@Serializable
data class DouyinLastResult(
    @SerialName("attempted_at") val attemptedAt: String = "",
    @SerialName("success_count") val successCount: Int = 0,
    @SerialName("failure_count") val failureCount: Int = 0,
    @SerialName("ambiguous_count") val ambiguousCount: Int = 0,
    @SerialName("halt_reason") val haltReason: String = ""
)

@Serializable
data class DouyinSessionState(
    val connected: Boolean = false,
    val username: String = "",
    val enabled: Boolean = false,
    @SerialName("default_message") val defaultMessage: String = "续火花",
    val targets: List<SparkTarget> = emptyList(),
    val hour: Int = 9,
    @SerialName("last_run") val lastRun: String = "",
    @SerialName("last_auto_run") val lastAutoRun: String = "",
    @SerialName("last_auto_attempt") val lastAutoAttempt: String = "",
    @SerialName("auto_blocked_date") val autoBlockedDate: String = "",
    @SerialName("auto_blocked_reason") val autoBlockedReason: String = "",
    @SerialName("last_result") val lastResult: DouyinLastResult = DouyinLastResult(),
    @SerialName("target_status") val targetStatus: Map<String, DouyinTargetStatus> = emptyMap(),
    @SerialName("disabled_reason") val disabledReason: String = ""
)

@Serializable
data class DouyinSessionResponse(
    val valid: Boolean = false,
    val nickname: String? = null,
    @SerialName("avatar_url") val avatarUrl: String? = null,
    @SerialName("expire_time") val expireTime: String? = null,
    val douyin: DouyinSessionState? = null,
    val enabled: Boolean = false,
    @SerialName("default_message") val defaultMessage: String = "续火花",
    val targets: List<SparkTarget> = emptyList(),
    val hour: Int = 9,
    @SerialName("last_run") val lastRun: String = "",
    @SerialName("last_auto_run") val lastAutoRun: String = "",
    @SerialName("last_auto_attempt") val lastAutoAttempt: String = ""
) {
    fun resolvedConfig(): DouyinConfig {
        val nested = douyin
        return DouyinConfig(
            enabled = nested?.enabled ?: enabled,
            defaultMessage = nested?.defaultMessage ?: defaultMessage,
            targets = nested?.targets ?: targets,
            hour = nested?.hour ?: hour
        )
    }
}

@Serializable
data class SparkTarget(
    val name: String,
    val mode: String? = null,
    val message: String? = null,
    @SerialName("conversation_id") val conversationId: String = "",
    @SerialName("conversation_short_id") val conversationShortId: String = "",
    @SerialName("conversation_type") val conversationType: String = ""
) {
    fun resolvedMode(): String =
        mode?.takeIf { it == "standard" || it == "custom" }
            ?: if (message.isNullOrBlank()) "standard" else "custom"

    fun identityKey(): String = conversationId.takeIf { it.isNotBlank() }?.let { "id:$it" }
        ?: "${conversationType.ifBlank { "unknown" }}:$name"
}

@Serializable
data class DouyinFriend(
    val name: String,
    @SerialName("avatar_url") val avatarUrl: String = "",
    @SerialName("conversation_id") val conversationId: String = "",
    @SerialName("conversation_short_id") val conversationShortId: String = "",
    @SerialName("conversation_type") val conversationType: String = ""
) {
    fun identityKey(): String = conversationId.takeIf { it.isNotBlank() }?.let { "id:$it" }
        ?: "${conversationType.ifBlank { "unknown" }}:$name"
}

@Serializable
data class DouyinFriendsResponse(
    val count: Int = 0,
    val total: Int = 0,
    val friends: List<DouyinFriend> = emptyList(),
    val cached: Boolean = true,
    @SerialName("cached_at") val cachedAt: String = ""
)

@Serializable
data class DouyinConfig(
    val enabled: Boolean = false,
    @SerialName("default_message") val defaultMessage: String = "续火花",
    val targets: List<SparkTarget> = emptyList(),
    val hour: Int = 9
)

@Serializable
data class TiboPostItem(
    val id: String,
    @SerialName("created_at") val createdAt: String = "",
    val text: String = "",
    val url: String = ""
)

@Serializable
data class TiboHistoryResponse(
    val items: List<TiboPostItem> = emptyList(),
    val count: Int = 0,
    @SerialName("last_checked") val lastChecked: String = "",
    val enabled: Boolean = false
)

@Serializable
data class TiboConfigRequest(val enabled: Boolean)

@Serializable
data class TiboConfigResponse(
    val success: Boolean = false,
    val enabled: Boolean = false,
    val message: String = ""
)

@Serializable
data class NotificationItem(
    val id: String,
    val title: String,
    val content: String,
    val timestamp: Long = 0L,
    @SerialName("created_at") val createdAt: String? = null,
    val read: Boolean = false,
    val url: String = ""
)

@Serializable
data class GenericApiResponse(
    val success: Boolean = true,
    val message: String? = null,
    val detail: String? = null
)


@Serializable
data class AppVersion(
    val version: String = "1.0.0",
    @SerialName("version_code") val versionCode: Int = 1,
    @SerialName("min_version_code") val minVersionCode: Int = 1,
    val force: Boolean = false,
    val title: String = "",
    val message: String = "",
    @SerialName("apk_url") val apkUrl: String = "",
    @SerialName("updated_at") val updatedAt: String = ""
)


@Serializable
data class HomeSummaryResponse(
    val user: User = User(username = ""),
    val student: StudentStatusResponse = StudentStatusResponse(),
    val schedule: SigninScheduleResponse = SigninScheduleResponse(),
    val td: TdStatusResponse? = null,
    val sunshine: SunshineStatusResponse? = null
)

@Serializable
data class DouyinQrResponse(
    @SerialName("login_id") val loginId: String = "",
    val status: String = "pending",
    @SerialName("qr_image") val qrImage: String = "",
    val nickname: String = "",
    val error: String = "",
    val valid: Boolean = false
)

@Serializable
data class DouyinQrCancelRequest(
    @SerialName("login_id") val loginId: String
)
