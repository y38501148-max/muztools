package com.muzermat.muztools.data.api

import com.muzermat.muztools.data.local.PreferencesManager
import com.muzermat.muztools.data.model.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.logging.HttpLoggingInterceptor
import java.io.File
import java.io.IOException
import java.math.BigInteger
import java.security.SecureRandom
import java.security.KeyFactory
import java.security.spec.RSAPublicKeySpec
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec
import android.util.Base64
import java.util.concurrent.TimeUnit

class ApiClient(private val prefs: PreferencesManager) {

    private val json = Json {
        ignoreUnknownKeys = true
        coerceInputValues = true
        isLenient = true
        encodeDefaults = true
    }

    private val okHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .writeTimeout(20, TimeUnit.SECONDS)
        .addInterceptor(HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BASIC
        })
        .addInterceptor { chain ->
            val original = chain.request()
            val requestBuilder = original.newBuilder()
                .header("Accept", "application/json")

            prefs.token?.let {
                if (it.isNotBlank()) {
                    requestBuilder.header("Authorization", "Bearer $it")
                }
            }
            chain.proceed(requestBuilder.build())
        }
        .build()

    private fun getFullUrl(path: String): String {
        val base = prefs.serverUrl.trimEnd('/')
        val endpoint = if (path.startsWith("/")) path else "/$path"
        return "$base$endpoint"
    }

    private val jsonMediaType = "application/json; charset=utf-8".toMediaType()

    private fun longClient(): OkHttpClient = okHttpClient.newBuilder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .build()


    private suspend inline fun <reified T> executeGet(path: String): Result<T> = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url(getFullUrl(path))
            .get()
            .build()

        try {
            val response = okHttpClient.newCall(request).execute()
            val body = response.body?.string() ?: ""
            if (response.isSuccessful) {
                Result.success(json.decodeFromString<T>(body))
            } else {
                Result.failure(ApiException(response.code, body.ifBlank { response.message }))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    private suspend inline fun <reified REQ, reified RES> executePost(path: String, bodyObj: REQ): Result<RES> = withContext(Dispatchers.IO) {
        val bodyJson = json.encodeToString(bodyObj)
        val requestBody = bodyJson.toRequestBody(jsonMediaType)
        val request = Request.Builder()
            .url(getFullUrl(path))
            .post(requestBody)
            .build()

        try {
            val response = okHttpClient.newCall(request).execute()
            val responseBody = response.body?.string() ?: ""
            if (response.isSuccessful) {
                Result.success(json.decodeFromString<RES>(responseBody))
            } else {
                Result.failure(ApiException(response.code, responseBody.ifBlank { response.message }))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    private suspend inline fun <reified REQ, reified RES> executePut(path: String, bodyObj: REQ): Result<RES> = withContext(Dispatchers.IO) {
        val bodyJson = json.encodeToString(bodyObj)
        val requestBody = bodyJson.toRequestBody(jsonMediaType)
        val request = Request.Builder()
            .url(getFullUrl(path))
            .put(requestBody)
            .build()

        try {
            val response = okHttpClient.newCall(request).execute()
            val responseBody = response.body?.string() ?: ""
            if (response.isSuccessful) {
                Result.success(json.decodeFromString<RES>(responseBody))
            } else {
                Result.failure(ApiException(response.code, responseBody.ifBlank { response.message }))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    private suspend inline fun <reified REQ, reified RES> executeDelete(path: String, bodyObj: REQ): Result<RES> = withContext(Dispatchers.IO) {
        val bodyJson = json.encodeToString(bodyObj)
        val request = Request.Builder()
            .url(getFullUrl(path))
            .delete(bodyJson.toRequestBody(jsonMediaType))
            .build()
        try {
            val response = okHttpClient.newCall(request).execute()
            val responseBody = response.body?.string() ?: ""
            if (response.isSuccessful) Result.success(json.decodeFromString<RES>(responseBody))
            else Result.failure(ApiException(response.code, responseBody.ifBlank { response.message }))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    private suspend fun transportKey(): Result<TransportPublicKey> =
        executeGet("/api/security/public-key")

    private fun encryptBytes(value: ByteArray, key: TransportPublicKey): String {
        val publicKey = KeyFactory.getInstance("RSA").generatePublic(
            RSAPublicKeySpec(BigInteger(key.modulusHex, 16), BigInteger.valueOf(key.exponent))
        )
        val cipher = Cipher.getInstance("RSA/ECB/PKCS1Padding")
        cipher.init(Cipher.ENCRYPT_MODE, publicKey)
        return Base64.encodeToString(cipher.doFinal(value), Base64.NO_WRAP)
    }

    private fun encryptValue(value: String, key: TransportPublicKey): String =
        encryptBytes(value.toByteArray(Charsets.UTF_8), key)

    private suspend fun hybridSecretRequest(value: String): Result<DouyinSessionRequest> =
        transportKey().mapCatching { transport ->
            val aesKey = ByteArray(32).also(SecureRandom()::nextBytes)
            val nonce = ByteArray(12).also(SecureRandom()::nextBytes)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.ENCRYPT_MODE, SecretKeySpec(aesKey, "AES"), GCMParameterSpec(128, nonce))
            val sealed = cipher.doFinal(value.toByteArray(Charsets.UTF_8))
            DouyinSessionRequest(
                HybridEncryptedSecret(
                    key = encryptBytes(aesKey, transport),
                    nonce = Base64.encodeToString(nonce, Base64.NO_WRAP),
                    ciphertext = Base64.encodeToString(sealed, Base64.NO_WRAP)
                )
            )
        }

    private suspend fun encryptedRequest(fields: Map<String, String>, keepLogin: Boolean = false): Result<EncryptedCredentialRequest> {
        return transportKey().mapCatching { key ->
            EncryptedCredentialRequest(fields.mapValues { encryptValue(it.value, key) }, keepLogin)
        }
    }

    // Auth APIs
    suspend fun register(req: RegisterRequest): Result<AuthResponse> =
        encryptedRequest(
            mapOf("username" to req.username, "password" to req.password, "display_name" to req.displayName, "invite_code" to req.inviteCode),
            keepLogin = true
        ).fold(onSuccess = { executePost("/api/auth/register", it) }, onFailure = { Result.failure(it) })

    suspend fun login(req: LoginRequest): Result<AuthResponse> =
        encryptedRequest(mapOf("username" to req.username, "password" to req.password), keepLogin = true)
            .fold(onSuccess = { executePost("/api/auth/login", it) }, onFailure = { Result.failure(it) })

    suspend fun getMe(): Result<User> =
        executeGet("/api/me")

    suspend fun registerDevice(deviceId: String): Result<GenericApiResponse> =
        executePost("/api/devices", DeviceRegisterRequest(deviceId))

    suspend fun registerFcmToken(token: String, deviceId: String, appVersion: String): Result<GenericApiResponse> =
        executePost("/api/devices/fcm", FcmTokenRequest(token, deviceId, appVersion))

    suspend fun unregisterFcmToken(token: String): Result<GenericApiResponse> =
        executeDelete("/api/devices/fcm", mapOf("token" to token))

    suspend fun getNotifications(): Result<List<NotificationItem>> =
        executeGet("/api/notifications")

    // Student & Signin APIs
    suspend fun bindStudent(req: StudentBindRequest): Result<GenericApiResponse> =
        encryptedRequest(mapOf("student_id" to req.studentId, "password" to req.password))
            .fold(onSuccess = { executePost("/api/student/bind", it) }, onFailure = { Result.failure(it) })

    suspend fun issueInvite(): Result<InviteIssueResponse> =
        executePost("/api/invites/issue", emptyMap<String, String>())

    suspend fun getStudentStatus(): Result<StudentStatusResponse> =
        executeGet("/api/student")

    suspend fun requestFeature(feature: String): Result<GenericApiResponse> =
        executePost("/api/student/request", FeatureRequest(feature))

    suspend fun getSigninSchedule(cached: Boolean = false): Result<SigninScheduleResponse> =
        executeGet("/api/signin/schedule?cached=${if (cached) 1 else 0}")

    suspend fun getHome(cached: Boolean = true): Result<HomeSummaryResponse> =
        executeGet("/api/home?cached=${if (cached) 1 else 0}")

    suspend fun setAutoSignin(enabled: Boolean): Result<GenericApiResponse> =
        executePost("/api/signin/auto", AutoSigninToggleRequest(enabled))

    // TD & Sunshine APIs
    suspend fun getTdStatus(): Result<TdStatusResponse> =
        executeGet("/api/td/status")

    suspend fun getSunshineStatus(): Result<SunshineStatusResponse> =
        executeGet("/api/sunshine/status")

    suspend fun postTdPhotos(entranceFile: File?, exitFile: File?): Result<GenericApiResponse> = withContext(Dispatchers.IO) {
        val builder = MultipartBody.Builder().setType(MultipartBody.FORM)
        entranceFile?.let {
            val mediaType = "image/*".toMediaType()
            builder.addFormDataPart("entrance", it.name, it.asRequestBody(mediaType))
        }
        exitFile?.let {
            val mediaType = "image/*".toMediaType()
            builder.addFormDataPart("exit", it.name, it.asRequestBody(mediaType))
        }

        val request = Request.Builder()
            .url(getFullUrl("/api/td/photos"))
            .post(builder.build())
            .build()

        try {
            val response = okHttpClient.newCall(request).execute()
            val body = response.body?.string() ?: ""
            if (response.isSuccessful) {
                Result.success(json.decodeFromString<GenericApiResponse>(body))
            } else {
                Result.failure(ApiException(response.code, body.ifBlank { response.message }))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun postTdManual(req: TdManualRequest): Result<GenericApiResponse> =
        executePost("/api/td/manual", req)

    // Douyin APIs
    suspend fun submitDouyinSession(cookies: String): Result<DouyinSessionResponse> = withContext(Dispatchers.IO) {
        val encrypted = hybridSecretRequest(cookies).getOrElse { return@withContext Result.failure(it) }
        val bodyJson = json.encodeToString(encrypted)
        val request = Request.Builder()
            .url(getFullUrl("/api/douyin/session"))
            .post(bodyJson.toRequestBody(jsonMediaType))
            .build()
        try {
            val response = longClient().newCall(request).execute()
            val responseBody = response.body?.string() ?: ""
            if (response.isSuccessful) {
                Result.success(json.decodeFromString<DouyinSessionResponse>(responseBody))
            } else {
                Result.failure(ApiException(response.code, responseBody.ifBlank { response.message }))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun startDouyinQr(): Result<DouyinQrResponse> = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url(getFullUrl("/api/douyin/qr/start"))
            .post("{}".toRequestBody(jsonMediaType))
            .build()
        try {
            val response = longClient().newCall(request).execute()
            val body = response.body?.string() ?: ""
            if (response.isSuccessful) {
                Result.success(json.decodeFromString<DouyinQrResponse>(body))
            } else {
                Result.failure(ApiException(response.code, body.ifBlank { response.message }))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun getDouyinQrStatus(loginId: String): Result<DouyinQrResponse> =
        executeGet("/api/douyin/qr/status?login_id=$loginId")

    suspend fun cancelDouyinQr(loginId: String): Result<GenericApiResponse> =
        executePost("/api/douyin/qr/cancel", DouyinQrCancelRequest(loginId))

    suspend fun getDouyinSession(): Result<DouyinSessionResponse> =
        executeGet("/api/douyin/session")

    suspend fun getDouyinFriends(refresh: Boolean = false): Result<DouyinFriendsResponse> = withContext(Dispatchers.IO) {
        val path = "/api/douyin/friends" + if (refresh) "?refresh=1" else ""
        val request = Request.Builder().url(getFullUrl(path)).get().build()
        try {
            val response = longClient().newCall(request).execute()
            val body = response.body?.string() ?: ""
            if (response.isSuccessful) {
                Result.success(json.decodeFromString<DouyinFriendsResponse>(body))
            } else {
                Result.failure(ApiException(response.code, body.ifBlank { response.message }))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun updateDouyinConfig(config: DouyinConfig): Result<GenericApiResponse> =
        executePut("/api/douyin/config", config)

    suspend fun runDouyinSpark(): Result<GenericApiResponse> =
        executePost("/api/douyin/run", emptyMap<String, String>())

    suspend fun runDouyinSparkTarget(targetKey: String): Result<GenericApiResponse> =
        executePost("/api/douyin/run-target", DouyinRunTargetRequest(targetKey))

    suspend fun getTiboHistory(): Result<TiboHistoryResponse> =
        executeGet("/api/tibo/history")

    suspend fun submitTiboXSession(cookies: String): Result<TiboXSessionResponse> = withContext(Dispatchers.IO) {
        val encrypted = hybridSecretRequest(cookies).getOrElse { return@withContext Result.failure(it) }
        val bodyJson = json.encodeToString(encrypted)
        val request = Request.Builder()
            .url(getFullUrl("/api/tibo/x-session"))
            .post(bodyJson.toRequestBody(jsonMediaType))
            .build()
        try {
            val response = longClient().newCall(request).execute()
            val responseBody = response.body?.string() ?: ""
            if (response.isSuccessful) {
                Result.success(json.decodeFromString<TiboXSessionResponse>(responseBody))
            } else {
                Result.failure(ApiException(response.code, responseBody.ifBlank { response.message }))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun deleteTiboXSession(): Result<TiboXSessionResponse> =
        executeDelete("/api/tibo/x-session", mapOf<String, String>())

    suspend fun updateTiboConfig(enabled: Boolean): Result<TiboConfigResponse> =
        executePut("/api/tibo/config", TiboConfigRequest(enabled))

    suspend fun getCheckinProviders(): Result<CheckinProvidersResponse> =
        executeGet("/api/checkin/providers")

    suspend fun getCheckinConfig(provider: String): Result<CheckinConfigResponse> =
        executeGet("/api/checkin/${android.net.Uri.encode(provider)}/config")

    suspend fun saveCheckinToken(provider: String, token: String): Result<CheckinConfigResponse> =
        encryptedRequest(mapOf("token" to token)).fold(
            onSuccess = { executePut("/api/checkin/${android.net.Uri.encode(provider)}/config", it) },
            onFailure = { Result.failure(it) }
        )

    suspend fun previewCheckin(provider: String, code: String): Result<CheckinPreviewResponse> =
        executePost("/api/checkin/${android.net.Uri.encode(provider)}/preview", CheckinPreviewRequest(code))

    suspend fun submitCheckin(provider: String, code: String, values: Map<String, String>): Result<CheckinSignResponse> =
        executePost("/api/checkin/${android.net.Uri.encode(provider)}/sign", CheckinSignRequest(code, values))

    suspend fun getAppVersion(): Result<AppVersion> =
        executeGet("/api/app/version")

    suspend fun downloadApk(relativeOrAbsolute: String, dest: File): Result<File> = withContext(Dispatchers.IO) {
        val url = if (relativeOrAbsolute.startsWith("http")) relativeOrAbsolute else getFullUrl(relativeOrAbsolute.ifBlank { "/api/app/apk" })
        val request = Request.Builder().url(url).get().build()
        val client = okHttpClient.newBuilder().readTimeout(5, TimeUnit.MINUTES).writeTimeout(5, TimeUnit.MINUTES).build()
        try {
            val response = client.newCall(request).execute()
            if (!response.isSuccessful) {
                return@withContext Result.failure(ApiException(response.code, response.body?.string().orEmpty().ifBlank { response.message }))
            }
            response.body?.byteStream()?.use { input ->
                dest.outputStream().use { output -> input.copyTo(output) }
            } ?: return@withContext Result.failure(IOException("安装包为空"))
            Result.success(dest)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
}

class ApiException(val code: Int, override val message: String) : IOException("HTTP $code: $message")
