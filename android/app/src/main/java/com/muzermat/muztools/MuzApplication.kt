package com.muzermat.muztools

import com.google.firebase.FirebaseApp
import com.google.firebase.messaging.FirebaseMessaging
import com.muzermat.muztools.data.api.ApiClient
import com.muzermat.muztools.data.local.PreferencesManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.cancel
import kotlinx.coroutines.tasks.await

class MuzApplication : android.app.Application() {

    lateinit var preferencesManager: PreferencesManager
        private set

    lateinit var apiClient: ApiClient
        private set

    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onCreate() {
        super.onCreate()
        preferencesManager = PreferencesManager(this)
        apiClient = ApiClient(preferencesManager)
    }

    fun refreshFcmRegistration() {
        appScope.launch {
            registerFcmTokenIfConfigured()
        }
    }

    fun registerFcmToken(token: String) {
        appScope.launch {
            if (!preferencesManager.token.isNullOrBlank()) {
                apiClient.registerFcmToken(token, preferencesManager.deviceId, appVersion())
            }
        }
    }

    private suspend fun registerFcmTokenIfConfigured() {
        if (preferencesManager.token.isNullOrBlank()) return
        runCatching { FirebaseApp.initializeApp(this@MuzApplication) }.getOrNull() ?: return
        val token = runCatching { FirebaseMessaging.getInstance().token.await() }.getOrNull() ?: return
        apiClient.registerFcmToken(token, preferencesManager.deviceId, appVersion())
    }

    private fun appVersion(): String = try {
        packageManager.getPackageInfo(packageName, 0).versionName.orEmpty()
    } catch (_: Exception) {
        ""
    }

    override fun onTerminate() {
        appScope.cancel()
        super.onTerminate()
    }
}
