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
            level = HttpLoggingInterceptor.Level.BODY
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
        .readTimeout(45, TimeUnit.SECONDS)
        .writeTimeout(45, TimeUnit.SECONDS)
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

    // Auth APIs
    suspend fun register(req: RegisterRequest): Result<AuthResponse> =
        executePost("/api/auth/register", req)

    suspend fun login(req: LoginRequest): Result<AuthResponse> =
        executePost("/api/auth/login", req)

    suspend fun getMe(): Result<User> =
        executeGet("/api/me")

    suspend fun registerDevice(deviceId: String): Result<GenericApiResponse> =
        executePost("/api/devices", DeviceRegisterRequest(deviceId))

    suspend fun getNotifications(): Result<List<NotificationItem>> =
        executeGet("/api/notifications")

    // Student & Signin APIs
    suspend fun bindStudent(req: StudentBindRequest): Result<GenericApiResponse> =
        executePost("/api/student/bind", req)

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
    suspend fun submitDouyinSession(cookies: String): Result<DouyinSessionResponse> =
        executePost("/api/douyin/session", DouyinSessionRequest(cookies))

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

    suspend fun updateDouyinConfig(config: DouyinConfig): Result<GenericApiResponse> =
        executePut("/api/douyin/config", config)

    suspend fun runDouyinSpark(): Result<GenericApiResponse> =
        executePost("/api/douyin/run", emptyMap<String, String>())

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
