package com.muzermat.muztools.service

import android.Manifest
import android.app.AlarmManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.Network
import android.net.Uri
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.os.SystemClock
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.muzermat.muztools.MainActivity
import com.muzermat.muztools.MuzApplication
import com.muzermat.muztools.R
import com.muzermat.muztools.data.model.NotificationItem
import kotlinx.coroutines.*
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import okhttp3.*
import java.util.concurrent.TimeUnit

class MuzNotificationService : Service() {
    companion object {
        private const val LIVE_CHANNEL_ID = "muztools_live_service"
        private const val NOTICE_CHANNEL_ID = "muztools_notifications"
        private const val FOREGROUND_ID = 10001
        private const val RECONNECT_DELAY_MS = 5_000L
        private const val FALLBACK_SYNC_INTERVAL_MS = 15_000L
        private const val SOCKET_STALE_AFTER_MS = 70_000L
        private const val RESTART_DELAY_MS = 5_000L
        private const val RESTART_REQUEST_CODE = 10002

        fun start(context: Context) {
            val intent = Intent(context, MuzNotificationService::class.java)
            runCatching {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    ContextCompat.startForegroundService(context.applicationContext, intent)
                } else {
                    context.applicationContext.startService(intent)
                }
            }
            NotificationWatchdogWorker.schedule(context)
        }

        fun stop(context: Context) {
            NotificationWatchdogWorker.cancel(context)
            context.stopService(Intent(context, MuzNotificationService::class.java))
        }

        fun scheduleRestart(context: Context) {
            if (com.muzermat.muztools.data.local.PreferencesManager(context).token.isNullOrBlank()) return
            val alarm = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
            val pending = PendingIntent.getBroadcast(
                context,
                RESTART_REQUEST_CODE,
                Intent(context, NotificationServiceRestartReceiver::class.java),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
            )
            alarm.setAndAllowWhileIdle(
                AlarmManager.ELAPSED_REALTIME_WAKEUP,
                SystemClock.elapsedRealtime() + RESTART_DELAY_MS,
                pending
            )
            NotificationWatchdogWorker.restartSoon(context)
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
    private var maintenanceJob: Job? = null
    private val syncMutex = Mutex()
    @Volatile private var lastSocketActivityAt = 0L
    private var wakeLock: PowerManager.WakeLock? = null
    private var connectivityManager: ConnectivityManager? = null
    private var networkCallback: ConnectivityManager.NetworkCallback? = null

    private val app: MuzApplication get() = application as MuzApplication

    override fun onCreate() {
        super.onCreate()
        createChannels()
        startForeground(FOREGROUND_ID, foregroundNotification())
        acquireWakeLock()
        registerNetworkCallback()
        startMaintenanceLoop()
        connect()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (app.preferencesManager.token.isNullOrBlank()) {
            stopSelf()
            return START_NOT_STICKY
        }
        startMaintenanceLoop()
        connect()
        NotificationWatchdogWorker.schedule(this)
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onTaskRemoved(rootIntent: Intent?) {
        scheduleRestart(this)
        super.onTaskRemoved(rootIntent)
    }

    override fun onDestroy() {
        reconnectJob?.cancel()
        maintenanceJob?.cancel()
        socket?.close(1000, "service stopped")
        socket = null
        networkCallback?.let { callback -> runCatching { connectivityManager?.unregisterNetworkCallback(callback) } }
        networkCallback = null
        wakeLock?.let { if (it.isHeld) it.release() }
        wakeLock = null
        scope.cancel()
        scheduleRestart(this)
        super.onDestroy()
    }

    private fun acquireWakeLock() {
        val powerManager = getSystemService(POWER_SERVICE) as PowerManager
        wakeLock = powerManager.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "$packageName:notification-service").apply {
            setReferenceCounted(false)
            acquire()
        }
    }

    private fun registerNetworkCallback() {
        val manager = getSystemService(CONNECTIVITY_SERVICE) as ConnectivityManager
        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                scope.launch {
                    socket?.cancel()
                    socket = null
                    connect()
                    syncUnreadNotifications()
                }
            }
        }
        runCatching { manager.registerDefaultNetworkCallback(callback) }
            .onSuccess {
                connectivityManager = manager
                networkCallback = callback
            }
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
        val url = "$wsBase/api/notifications/ws"
        lastSocketActivityAt = SystemClock.elapsedRealtime()
        val request = Request.Builder()
            .url(url)
            .header("Authorization", "Bearer $token")
            .build()
        socket = socketClient.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                lastSocketActivityAt = SystemClock.elapsedRealtime()
                scope.launch { syncUnreadNotifications() }
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                lastSocketActivityAt = SystemClock.elapsedRealtime()
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
            delay(RECONNECT_DELAY_MS)
            connect()
        }
    }

    private fun startMaintenanceLoop() {
        if (maintenanceJob?.isActive == true) return
        maintenanceJob = scope.launch {
            while (isActive) {
                delay(FALLBACK_SYNC_INTERVAL_MS)
                syncUnreadNotifications()
                val currentSocket = socket
                val inactiveFor = SystemClock.elapsedRealtime() - lastSocketActivityAt
                if (currentSocket == null) {
                    connect()
                } else if (inactiveFor >= SOCKET_STALE_AFTER_MS) {
                    socket = null
                    currentSocket.cancel()
                    connect()
                }
            }
        }
    }

    private suspend fun syncUnreadNotifications() = syncMutex.withLock {
        app.apiClient.getNotifications().onSuccess { items ->
            items.filter { !it.read }.take(20).asReversed().forEach(::deliver)
        }
    }

    @Synchronized
    private fun deliver(item: NotificationItem) {
        val prefs = app.preferencesManager
        if (prefs.wasNotificationDelivered(item.id)) return
        if (!notificationsAllowed()) return
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
        NotificationManagerCompat.from(this).notify(item.id.hashCode(), notification)
        prefs.markNotificationDelivered(item.id)
    }

    private fun notificationsAllowed(): Boolean {
        if (
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) return false
        if (!NotificationManagerCompat.from(this).areNotificationsEnabled()) return false
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = (getSystemService(NOTIFICATION_SERVICE) as NotificationManager)
                .getNotificationChannel(NOTICE_CHANNEL_ID)
            if (channel?.importance == NotificationManager.IMPORTANCE_NONE) return false
        }
        return true
    }

    private fun foregroundNotification() = NotificationCompat.Builder(this, LIVE_CHANNEL_ID)
        .setSmallIcon(R.mipmap.ic_launcher)
        .setContentTitle("盐的工具箱通知服务")
        .setContentText("正在保持实时连接，并定期检查遗漏消息")
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
