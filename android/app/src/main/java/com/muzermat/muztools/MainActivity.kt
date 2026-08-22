package com.muzermat.muztools

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.LaunchedEffect
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
                return AuthViewModel(app.apiClient, app.preferencesManager) as T
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
                LaunchedEffect(Unit) { updateViewModel.check() }
                AppNavigation(
                    authViewModel = authViewModel,
                    homeViewModel = homeViewModel,
                    signinViewModel = signinViewModel,
                    tdViewModel = tdViewModel,
                    sparkViewModel = sparkViewModel,
                    profileViewModel = profileViewModel
                )
                UpdateDialog(updateViewModel)
            }
        }
    }
}
