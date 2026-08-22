package com.muzermat.muztools

import android.app.Application
import com.muzermat.muztools.data.api.ApiClient
import com.muzermat.muztools.data.local.PreferencesManager
import com.muzermat.muztools.service.NotificationPollingService

class MuzApplication : Application() {

    lateinit var preferencesManager: PreferencesManager
        private set

    lateinit var apiClient: ApiClient
        private set

    lateinit var pollingService: NotificationPollingService
        private set

    override fun onCreate() {
        super.onCreate()
        preferencesManager = PreferencesManager(this)
        apiClient = ApiClient(preferencesManager)
        pollingService = NotificationPollingService(this, apiClient, preferencesManager)
        pollingService.startPolling()
    }
}
