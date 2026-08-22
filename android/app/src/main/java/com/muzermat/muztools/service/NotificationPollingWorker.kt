package com.muzermat.muztools.service

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import com.muzermat.muztools.MainActivity
import com.muzermat.muztools.R
import com.muzermat.muztools.data.api.ApiClient
import com.muzermat.muztools.data.local.PreferencesManager
import kotlinx.coroutines.*

class NotificationPollingService(
    private val context: Context,
    private val apiClient: ApiClient,
    private val prefs: PreferencesManager
) {
    companion object {
        const val CHANNEL_ID = "muztools_notifications"
        const val CHANNEL_NAME = "木子工具通知"
    }

    private var pollJob: Job? = null
    private val serviceScope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private val shownNotificationIds = mutableSetOf<String>()

    init {
        createNotificationChannel()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                CHANNEL_NAME,
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = "接收签到状态、TD打卡与火花任务推送通知"
                enableVibration(true)
            }
            val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            notificationManager.createNotificationChannel(channel)
        }
    }

    fun startPolling() {
        stopPolling()
        pollJob = serviceScope.launch {
            while (isActive) {
                if (!prefs.token.isNullOrBlank()) {
                    try {
                        val result = apiClient.getNotifications()
                        result.onSuccess { notifications ->
                            for (notif in notifications) {
                                if (!notif.read && !shownNotificationIds.contains(notif.id)) {
                                    shownNotificationIds.add(notif.id)
                                    showSystemNotification(notif.id, notif.title, notif.content)
                                }
                            }
                        }
                    } catch (e: Exception) {
                        // Ignore network poll errors
                    }
                }
                delay(15000L) // 15秒轮询一次
            }
        }
    }

    fun stopPolling() {
        pollJob?.cancel()
        pollJob = null
    }

    private fun showSystemNotification(idStr: String, title: String, content: String) {
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
        }
        val pendingIntent = PendingIntent.getActivity(
            context,
            0,
            intent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(title)
            .setContentText(content)
            .setStyle(NotificationCompat.BigTextStyle().bigText(content))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setContentIntent(pendingIntent)
            .build()

        val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        notificationManager.notify(idStr.hashCode(), notification)
    }
}
