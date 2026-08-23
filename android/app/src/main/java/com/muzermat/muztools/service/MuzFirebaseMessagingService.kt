package com.muzermat.muztools.service

import android.app.PendingIntent
import android.content.Intent
import android.net.Uri
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import com.muzermat.muztools.MainActivity
import com.muzermat.muztools.MuzApplication
import com.muzermat.muztools.R

class MuzFirebaseMessagingService : FirebaseMessagingService() {
    override fun onNewToken(token: String) {
        (application as? MuzApplication)?.registerFcmToken(token)
    }

    override fun onMessageReceived(message: RemoteMessage) {
        if (!NotificationAccess.isEnabled(this)) return
        val data = message.data
        val title = data["title"] ?: message.notification?.title ?: "盐的工具箱"
        val body = data["body"] ?: message.notification?.body ?: "收到一条新通知"
        val url = data["url"].orEmpty()
        val id = data["notification_id"] ?: "fcm-${System.currentTimeMillis()}"
        val intent = if (url.startsWith("http://") || url.startsWith("https://")) {
            Intent(Intent.ACTION_VIEW, Uri.parse(url)).apply { flags = Intent.FLAG_ACTIVITY_NEW_TASK }
        } else {
            Intent(this, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            }
        }
        val pendingIntent = PendingIntent.getActivity(
            this,
            id.hashCode(),
            intent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val notification = NotificationCompat.Builder(this, "muztools_notifications")
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setContentIntent(pendingIntent)
            .build()
        NotificationManagerCompat.from(this).notify(id.hashCode(), notification)
    }
}
