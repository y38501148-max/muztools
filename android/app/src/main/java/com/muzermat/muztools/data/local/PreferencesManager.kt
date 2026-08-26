package com.muzermat.muztools.data.local

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import java.util.UUID

class PreferencesManager(context: Context) {
    companion object {
        private const val PREFS_NAME = "muztools_secure_prefs"
        private const val KEY_SERVER_URL = "server_url"
        private const val KEY_TOKEN = "jwt_token"
        private const val KEY_USERNAME = "username"
        private const val KEY_DISPLAY_NAME = "display_name"
        private const val KEY_DEVICE_ID = "device_id"
        private const val KEY_PASSWORD = "password"
        private const val KEY_REMEMBER_PASSWORD = "remember_password"
        private const val KEY_AUTO_LOGIN = "auto_login"
        private const val KEY_DELIVERED_NOTIFICATIONS = "delivered_notifications"
        private const val KEY_BACKGROUND_POWER_PROMPT_SHOWN = "background_power_prompt_shown"
        private const val DEFAULT_SERVER_URL = "https://muzermat.online"
        private val LEGACY_SERVER_URLS = emptySet<String>()
    }

    // Do not fall back to plaintext SharedPreferences: this store contains the
    // application password when the user enables automatic login. If the
    // Android Keystore is unavailable, fail closed instead of silently
    // downgrading credential protection.
    private val prefs: SharedPreferences = run {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            context,
            PREFS_NAME,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )
    }

    var serverUrl: String
        get() {
            val stored = prefs.getString(KEY_SERVER_URL, null)?.trim()?.trimEnd('/')
            return if (stored.isNullOrBlank() || stored in LEGACY_SERVER_URLS) {
                DEFAULT_SERVER_URL
            } else {
                stored
            }
        }
        set(value) = prefs.edit().putString(KEY_SERVER_URL, value.trim().trimEnd('/')).apply()

    var token: String?
        get() = prefs.getString(KEY_TOKEN, null)
        set(value) = prefs.edit().putString(KEY_TOKEN, value).apply()

    var username: String?
        get() = prefs.getString(KEY_USERNAME, null)
        set(value) = prefs.edit().putString(KEY_USERNAME, value).apply()

    var displayName: String?
        get() = prefs.getString(KEY_DISPLAY_NAME, null)
        set(value) = prefs.edit().putString(KEY_DISPLAY_NAME, value).apply()

    var password: String?
        get() = prefs.getString(KEY_PASSWORD, null)
        set(value) = prefs.edit().putString(KEY_PASSWORD, value).apply()

    var rememberPassword: Boolean
        get() = prefs.getBoolean(KEY_REMEMBER_PASSWORD, false)
        set(value) = prefs.edit().putBoolean(KEY_REMEMBER_PASSWORD, value).apply()

    var autoLogin: Boolean
        get() = prefs.getBoolean(KEY_AUTO_LOGIN, false)
        set(value) = prefs.edit().putBoolean(KEY_AUTO_LOGIN, value).apply()

    var backgroundPowerPromptShown: Boolean
        get() = prefs.getBoolean(KEY_BACKGROUND_POWER_PROMPT_SHOWN, false)
        set(value) = prefs.edit().putBoolean(KEY_BACKGROUND_POWER_PROMPT_SHOWN, value).apply()

    val deviceId: String
        get() {
            var id = prefs.getString(KEY_DEVICE_ID, null)
            if (id == null) {
                id = UUID.randomUUID().toString()
                prefs.edit().putString(KEY_DEVICE_ID, id).apply()
            }
            return id
        }

    fun persistLogin(username: String, displayName: String, rawPassword: String, remember: Boolean, autoLoginEnabled: Boolean) {
        val editor = prefs.edit()
            .putString(KEY_USERNAME, username)
            .putString(KEY_DISPLAY_NAME, displayName)
            .putBoolean(KEY_REMEMBER_PASSWORD, remember || autoLoginEnabled)
            .putBoolean(KEY_AUTO_LOGIN, autoLoginEnabled)
        if (remember || autoLoginEnabled) {
            editor.putString(KEY_PASSWORD, rawPassword)
        } else {
            editor.remove(KEY_PASSWORD)
        }
        editor.apply()
    }


    fun wasNotificationDelivered(id: String): Boolean =
        prefs.getStringSet(KEY_DELIVERED_NOTIFICATIONS, emptySet())?.contains(id) == true

    fun markNotificationDelivered(id: String) {
        val current = prefs.getStringSet(KEY_DELIVERED_NOTIFICATIONS, emptySet()).orEmpty().toMutableList()
        current.remove(id)
        current.add(0, id)
        prefs.edit().putStringSet(KEY_DELIVERED_NOTIFICATIONS, current.take(100).toSet()).apply()
    }

    fun clearAuth() {
        val editor = prefs.edit().remove(KEY_TOKEN).remove(KEY_DISPLAY_NAME)
        if (!rememberPassword && !autoLogin) {
            editor.remove(KEY_USERNAME).remove(KEY_PASSWORD)
        }
        editor.apply()
    }
}
