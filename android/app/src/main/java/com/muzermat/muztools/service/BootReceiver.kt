package com.muzermat.muztools.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.muzermat.muztools.data.local.PreferencesManager

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action == Intent.ACTION_BOOT_COMPLETED &&
            !PreferencesManager(context).token.isNullOrBlank() &&
            NotificationAccess.isEnabled(context)
        ) {
            MuzNotificationService.start(context)
        }
    }
}
