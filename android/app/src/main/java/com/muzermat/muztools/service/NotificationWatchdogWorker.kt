package com.muzermat.muztools.service

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.OutOfQuotaPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.muzermat.muztools.data.local.PreferencesManager
import java.util.concurrent.TimeUnit

class NotificationWatchdogWorker(
    appContext: Context,
    params: WorkerParameters
) : CoroutineWorker(appContext, params) {

    override suspend fun doWork(): Result {
        if (PreferencesManager(applicationContext).token.isNullOrBlank()) return Result.success()
        MuzNotificationService.start(applicationContext)
        return Result.success()
    }

    companion object {
        private const val PERIODIC_NAME = "muztools-notification-watchdog"
        private const val IMMEDIATE_NAME = "muztools-notification-restart"

        fun schedule(context: Context) {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()
            val request = PeriodicWorkRequestBuilder<NotificationWatchdogWorker>(15, TimeUnit.MINUTES)
                .setConstraints(constraints)
                .build()
            WorkManager.getInstance(context.applicationContext).enqueueUniquePeriodicWork(
                PERIODIC_NAME,
                ExistingPeriodicWorkPolicy.UPDATE,
                request
            )
        }

        fun restartSoon(context: Context) {
            val request = OneTimeWorkRequestBuilder<NotificationWatchdogWorker>()
                .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
                .build()
            WorkManager.getInstance(context.applicationContext).enqueueUniqueWork(
                IMMEDIATE_NAME,
                ExistingWorkPolicy.REPLACE,
                request
            )
        }

        fun cancel(context: Context) {
            WorkManager.getInstance(context.applicationContext).cancelUniqueWork(PERIODIC_NAME)
            WorkManager.getInstance(context.applicationContext).cancelUniqueWork(IMMEDIATE_NAME)
        }
    }
}
