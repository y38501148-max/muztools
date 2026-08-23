package com.muzermat.muztools

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.core.content.ContextCompat
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import com.muzermat.muztools.ui.navigation.AppNavigation
import com.muzermat.muztools.ui.screens.auth.AuthViewModel
import com.muzermat.muztools.ui.screens.home.HomeViewModel
import com.muzermat.muztools.ui.screens.profile.ProfileViewModel
import com.muzermat.muztools.ui.screens.signin.SigninViewModel
import com.muzermat.muztools.ui.screens.spark.SparkViewModel
import com.muzermat.muztools.ui.screens.td.TdViewModel
import com.muzermat.muztools.ui.screens.tibo.TiboViewModel
import com.muzermat.muztools.service.MuzNotificationService
import com.muzermat.muztools.service.NotificationAccess
import com.muzermat.muztools.ui.theme.MuzToolsTheme
import com.muzermat.muztools.update.UpdateDialog
import com.muzermat.muztools.update.UpdateViewModel

class MainActivity : ComponentActivity() {

    private var notificationStateVersion by mutableIntStateOf(0)

    private val requestPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) {
        notificationPermissionPrefs().edit().putBoolean("asked", true).apply()
        notificationStateVersion++
    }

    private val authViewModel: AuthViewModel by viewModels {
        val app = application as MuzApplication
        object : ViewModelProvider.Factory {
            override fun <T : ViewModel> create(modelClass: Class<T>): T {
                @Suppress("UNCHECKED_CAST")
                return AuthViewModel(app.apiClient, app.preferencesManager, app::refreshFcmRegistration) as T
            }
        }
    }

    private val homeViewModel: HomeViewModel by viewModels {
        val app = application as MuzApplication
        object : ViewModelProvider.Factory {
            override fun <T : ViewModel> create(modelClass: Class<T>): T {
                @Suppress("UNCHECKED_CAST")
                return HomeViewModel(app.apiClient, app.preferencesManager) as T
            }
        }
    }

    private val signinViewModel: SigninViewModel by viewModels {
        val app = application as MuzApplication
        object : ViewModelProvider.Factory {
            override fun <T : ViewModel> create(modelClass: Class<T>): T {
                @Suppress("UNCHECKED_CAST")
                return SigninViewModel(app.apiClient) as T
            }
        }
    }

    private val tdViewModel: TdViewModel by viewModels {
        val app = application as MuzApplication
        object : ViewModelProvider.Factory {
            override fun <T : ViewModel> create(modelClass: Class<T>): T {
                @Suppress("UNCHECKED_CAST")
                return TdViewModel(app.apiClient) as T
            }
        }
    }

    private val sparkViewModel: SparkViewModel by viewModels {
        val app = application as MuzApplication
        object : ViewModelProvider.Factory {
            override fun <T : ViewModel> create(modelClass: Class<T>): T {
                @Suppress("UNCHECKED_CAST")
                return SparkViewModel(app.apiClient) as T
            }
        }
    }

    private val tiboViewModel: TiboViewModel by viewModels {
        val app = application as MuzApplication
        object : ViewModelProvider.Factory {
            override fun <T : ViewModel> create(modelClass: Class<T>): T {
                @Suppress("UNCHECKED_CAST")
                return TiboViewModel(app.apiClient) as T
            }
        }
    }

    private val updateViewModel: UpdateViewModel by viewModels {
        val app = application as MuzApplication
        object : ViewModelProvider.Factory {
            override fun <T : ViewModel> create(modelClass: Class<T>): T {
                @Suppress("UNCHECKED_CAST")
                return UpdateViewModel(app.apiClient) as T
            }
        }
    }

    private val profileViewModel: ProfileViewModel by viewModels {
        val app = application as MuzApplication
        object : ViewModelProvider.Factory {
            override fun <T : ViewModel> create(modelClass: Class<T>): T {
                @Suppress("UNCHECKED_CAST")
                return ProfileViewModel(app.apiClient, app.preferencesManager) as T
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        setContent {
            MuzToolsTheme {
                val authState by authViewModel.uiState.collectAsState()
                val stateVersion = notificationStateVersion
                val notificationsEnabled = notificationsEnabled()
                var notificationPromptDismissed by rememberSaveable { mutableStateOf(false) }

                LaunchedEffect(Unit) { updateViewModel.check() }
                LaunchedEffect(authState.isLoggedIn) {
                    if (authState.isLoggedIn) notificationPromptDismissed = false
                }
                LaunchedEffect(authState.isLoggedIn, stateVersion, notificationsEnabled) {
                    if (authState.isLoggedIn && notificationsEnabled) MuzNotificationService.start(this@MainActivity)
                    else MuzNotificationService.stop(this@MainActivity)
                }
                AppNavigation(
                    authViewModel = authViewModel,
                    homeViewModel = homeViewModel,
                    signinViewModel = signinViewModel,
                    tdViewModel = tdViewModel,
                    sparkViewModel = sparkViewModel,
                    tiboViewModel = tiboViewModel,
                    profileViewModel = profileViewModel
                )
                UpdateDialog(updateViewModel)
                if (authState.isLoggedIn && !notificationsEnabled && !notificationPromptDismissed) {
                    AlertDialog(
                        onDismissRequest = { notificationPromptDismissed = true },
                        title = { Text("开启系统通知") },
                        text = { Text("用于接收自动任务结果、Tibo Reset 和重要系统提示。关闭应用后是否能显示通知，也取决于此权限。") },
                        confirmButton = {
                            TextButton(onClick = {
                                notificationPromptDismissed = true
                                requestNotificationAccess()
                            }) { Text("开启通知") }
                        },
                        dismissButton = {
                            TextButton(onClick = { notificationPromptDismissed = true }) { Text("稍后") }
                        }
                    )
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        notificationStateVersion++
    }

    private fun notificationsEnabled(): Boolean = NotificationAccess.isEnabled(this)

    private fun notificationPermissionPrefs() = getSharedPreferences("notification_permission", MODE_PRIVATE)

    private fun requestNotificationAccess() {
        val runtimeMissing = Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        val asked = notificationPermissionPrefs().getBoolean("asked", false)
        if (runtimeMissing && !asked) {
            requestPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        } else {
            openNotificationSettings()
        }
    }

    private fun openNotificationSettings() {
        startActivity(NotificationAccess.settingsIntent(this))
    }
}
