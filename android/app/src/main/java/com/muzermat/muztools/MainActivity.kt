package com.muzermat.muztools

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.core.content.ContextCompat
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import com.muzermat.muztools.ui.navigation.AppNavigation
import com.muzermat.muztools.ui.screens.auth.AuthViewModel
import com.muzermat.muztools.ui.screens.checkin.CheckinViewModel
import com.muzermat.muztools.ui.screens.home.HomeViewModel
import com.muzermat.muztools.ui.screens.profile.ProfileViewModel
import com.muzermat.muztools.ui.screens.signin.SigninViewModel
import com.muzermat.muztools.ui.screens.spark.SparkViewModel
import com.muzermat.muztools.ui.screens.td.TdViewModel
import com.muzermat.muztools.ui.screens.tibo.TiboViewModel
import com.muzermat.muztools.service.MuzNotificationService
import com.muzermat.muztools.ui.theme.MuzToolsTheme
import com.muzermat.muztools.update.UpdateDialog
import com.muzermat.muztools.update.UpdateViewModel

class MainActivity : ComponentActivity() {

    private val requestPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { _ -> }

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

    private val checkinViewModel: CheckinViewModel by viewModels {
        val app = application as MuzApplication
        object : ViewModelProvider.Factory {
            override fun <T : ViewModel> create(modelClass: Class<T>): T {
                @Suppress("UNCHECKED_CAST")
                return CheckinViewModel(app.apiClient) as T
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

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                requestPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        }

        setContent {
            MuzToolsTheme {
                val authState by authViewModel.uiState.collectAsState()
                LaunchedEffect(Unit) { updateViewModel.check() }
                LaunchedEffect(authState.isLoggedIn) {
                    if (authState.isLoggedIn) {
                        MuzNotificationService.start(this@MainActivity)
                        requestBackgroundExecutionIfNeeded()
                    } else {
                        MuzNotificationService.stop(this@MainActivity)
                    }
                }
                AppNavigation(
                    authViewModel = authViewModel,
                    homeViewModel = homeViewModel,
                    signinViewModel = signinViewModel,
                    tdViewModel = tdViewModel,
                    sparkViewModel = sparkViewModel,
                    tiboViewModel = tiboViewModel,
                    checkinViewModel = checkinViewModel,
                    profileViewModel = profileViewModel
                )
                UpdateDialog(updateViewModel)
            }
        }
    }

    private fun requestBackgroundExecutionIfNeeded() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return
        val app = application as MuzApplication
        if (app.preferencesManager.backgroundPowerPromptShown) return
        val powerManager = getSystemService(POWER_SERVICE) as PowerManager
        if (powerManager.isIgnoringBatteryOptimizations(packageName)) return
        app.preferencesManager.backgroundPowerPromptShown = true
        runCatching {
            startActivity(
                Intent(
                    Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                    Uri.parse("package:$packageName")
                )
            )
        }
    }
}
