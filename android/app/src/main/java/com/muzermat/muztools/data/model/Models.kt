package com.muzermat.muztools.data.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class User(
    val username: String,
    @SerialName("display_name") val displayName: String = "",
    val role: String? = null
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
    @SerialName("display_name") val displayName: String
)

@Serializable
data class LoginRequest(
    val username: String,
    val password: String
)

@Serializable
data class DeviceRegisterRequest(
    @SerialName("device_id") val deviceId: String
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
data class DouyinSessionRequest(
    val cookies: String
)

@Serializable
data class DouyinSessionResponse(
    val valid: Boolean = false,
    val nickname: String? = null,
    @SerialName("avatar_url") val avatarUrl: String? = null,
    @SerialName("expire_time") val expireTime: String? = null
)

@Serializable
data class SparkTarget(
    val name: String,
    val message: String? = null
)

@Serializable
data class DouyinConfig(
    val enabled: Boolean = false,
    @SerialName("default_message") val defaultMessage: String = "滴滴",
    val targets: List<SparkTarget> = emptyList(),
    val hour: Int = 8
)

@Serializable
data class NotificationItem(
    val id: String,
    val title: String,
    val content: String,
    val timestamp: Long = 0L,
    @SerialName("created_at") val createdAt: String? = null,
    val read: Boolean = false
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
