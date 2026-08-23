package com.muzermat.muztools.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.muzermat.muztools.data.local.PreferencesManager

class NotificationServiceRestartReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (!PreferencesManager(context).token.isNullOrBlank()) {
            MuzNotificationService.start(context)
            NotificationWatchdogWorker.schedule(context)
        }
    }
}
