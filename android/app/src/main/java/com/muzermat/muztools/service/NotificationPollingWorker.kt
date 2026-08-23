package com.muzermat.muztools.service

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.muzermat.muztools.MainActivity
import com.muzermat.muztools.MuzApplication
import com.muzermat.muztools.R
import com.muzermat.muztools.data.model.NotificationItem
import kotlinx.coroutines.*
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import okhttp3.*
import java.util.concurrent.TimeUnit

class MuzNotificationService : Service() {
    companion object {
        private const val LIVE_CHANNEL_ID = "muztools_live_service"
        private const val NOTICE_CHANNEL_ID = "muztools_notifications"
        private const val FOREGROUND_ID = 10001

        fun start(context: Context) {
            val intent = Intent(context, MuzNotificationService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) context.startForegroundService(intent) else context.startService(intent)
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, MuzNotificationService::class.java))
        }
    }

    @Serializable
    private data class LiveEnvelope(val type: String = "", val item: NotificationItem? = null)

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val json = Json { ignoreUnknownKeys = true; coerceInputValues = true }
    private val socketClient = OkHttpClient.Builder()
        .pingInterval(20, TimeUnit.SECONDS)
        .connectTimeout(20, TimeUnit.SECONDS)
        .build()
    private var socket: WebSocket? = null
    private var reconnectJob: Job? = null

    private val app: MuzApplication get() = application as MuzApplication

    override fun onCreate() {
        super.onCreate()
        createChannels()
        startForeground(FOREGROUND_ID, foregroundNotification())
        connect()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (app.preferencesManager.token.isNullOrBlank()) {
            stopSelf()
            return START_NOT_STICKY
        }
        connect()
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        reconnectJob?.cancel()
        socket?.close(1000, "service stopped")
        socket = null
        scope.cancel()
        super.onDestroy()
    }

    private fun connect() {
        val token = app.preferencesManager.token?.takeIf { it.isNotBlank() } ?: return
        if (socket != null) return
        val base = app.preferencesManager.serverUrl.trimEnd('/')
        val wsBase = when {
            base.startsWith("https://") -> "wss://${base.removePrefix("https://")}"
            base.startsWith("http://") -> "ws://${base.removePrefix("http://")}"
            else -> "ws://$base"
        }
        val url = "$wsBase/api/notifications/ws?token=${Uri.encode(token)}"
        socket = socketClient.newWebSocket(Request.Builder().url(url).build(), object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                scope.launch { syncUnreadNotifications() }
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                runCatching { json.decodeFromString<LiveEnvelope>(text) }
                    .getOrNull()?.item?.let(::deliver)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = scheduleReconnect(webSocket)
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) = scheduleReconnect(webSocket)
        })
    }

    private fun scheduleReconnect(closedSocket: WebSocket) {
        if (socket !== closedSocket) return
        socket = null
        reconnectJob?.cancel()
        reconnectJob = scope.launch {
            delay(5_000)
            connect()
        }
    }

    private suspend fun syncUnreadNotifications() {
        app.apiClient.getNotifications().onSuccess { items ->
            items.filter { !it.read }.take(20).asReversed().forEach(::deliver)
        }
    }

    private fun deliver(item: NotificationItem) {
        val prefs = app.preferencesManager
        if (prefs.wasNotificationDelivered(item.id)) return
        prefs.markNotificationDelivered(item.id)
        val intent = if (item.url.startsWith("http://") || item.url.startsWith("https://")) {
            Intent(Intent.ACTION_VIEW, Uri.parse(item.url)).apply { flags = Intent.FLAG_ACTIVITY_NEW_TASK }
        } else {
            Intent(this, MainActivity::class.java).apply { flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP }
        }
        val pendingIntent = PendingIntent.getActivity(
            this,
            item.id.hashCode(),
            intent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val notification = NotificationCompat.Builder(this, NOTICE_CHANNEL_ID)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(item.title)
            .setContentText(item.content)
            .setStyle(NotificationCompat.BigTextStyle().bigText(item.content))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setContentIntent(pendingIntent)
            .build()
        (getSystemService(NOTIFICATION_SERVICE) as NotificationManager).notify(item.id.hashCode(), notification)
    }

    private fun foregroundNotification() = NotificationCompat.Builder(this, LIVE_CHANNEL_ID)
        .setSmallIcon(R.mipmap.ic_launcher)
        .setContentTitle("盐的工具箱通知服务")
        .setContentText("正在保持连接，以便及时接收系统提示")
        .setOngoing(true)
        .setPriority(NotificationCompat.PRIORITY_LOW)
        .setContentIntent(
            PendingIntent.getActivity(
                this,
                0,
                Intent(this, MainActivity::class.java),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
            )
        )
        .build()

    private fun createChannels() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        manager.createNotificationChannel(NotificationChannel(LIVE_CHANNEL_ID, "后台通知连接", NotificationManager.IMPORTANCE_LOW))
        manager.createNotificationChannel(NotificationChannel(NOTICE_CHANNEL_ID, "盐的工具箱通知", NotificationManager.IMPORTANCE_HIGH).apply {
            description = "接收签到、续火花和 Tibo 监测提示"
            enableVibration(true)
        })
    }
}
