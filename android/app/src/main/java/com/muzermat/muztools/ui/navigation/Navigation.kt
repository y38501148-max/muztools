package com.muzermat.muztools.ui.navigation

import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.*
import com.muzermat.muztools.ui.screens.auth.AuthScreen
import com.muzermat.muztools.ui.screens.auth.AuthViewModel
import com.muzermat.muztools.ui.screens.features.FeaturesScreen
import com.muzermat.muztools.ui.screens.home.HomeScreen
import com.muzermat.muztools.ui.screens.home.HomeViewModel
import com.muzermat.muztools.ui.screens.profile.ProfileScreen
import com.muzermat.muztools.ui.screens.profile.ProfileViewModel
import com.muzermat.muztools.ui.screens.signin.SigninScreen
import com.muzermat.muztools.ui.screens.signin.SigninViewModel
import com.muzermat.muztools.ui.screens.spark.SparkScreen
import com.muzermat.muztools.ui.screens.spark.SparkViewModel
import com.muzermat.muztools.ui.screens.td.TdScreen
import com.muzermat.muztools.ui.screens.td.TdViewModel

sealed class Screen(val route: String) {
    object Auth : Screen("auth")
    object Main : Screen("main")
}

sealed class BottomTab(
    val route: String,
    val title: String,
    val selectedIcon: ImageVector,
    val unselectedIcon: ImageVector
) {
    object Home : BottomTab("tab_home", "首页", Icons.Filled.Home, Icons.Outlined.Home)
    object Features : BottomTab("tab_features", "功能", Icons.Filled.Apps, Icons.Outlined.Apps)
    object Profile : BottomTab("tab_profile", "我的", Icons.Filled.Person, Icons.Outlined.Person)
}

val bottomTabs = listOf(
    BottomTab.Home,
    BottomTab.Features,
    BottomTab.Profile
)

@Composable
fun AppNavigation(
    authViewModel: AuthViewModel,
    homeViewModel: HomeViewModel,
    signinViewModel: SigninViewModel,
    tdViewModel: TdViewModel,
    sparkViewModel: SparkViewModel,
    profileViewModel: ProfileViewModel
) {
    val navController = rememberNavController()
    val authState by authViewModel.uiState.collectAsState()
    val startDestination = if (authState.isLoggedIn) Screen.Main.route else Screen.Auth.route

    NavHost(
        navController = navController,
        startDestination = startDestination
    ) {
        composable(Screen.Auth.route) {
            AuthScreen(
                onLoginSuccess = {
                    navController.navigate(Screen.Main.route) {
                        popUpTo(Screen.Auth.route) { inclusive = true }
                    }
                },
                viewModel = authViewModel
            )
        }

        composable(Screen.Main.route) {
            MainContainer(
                onLogout = {
                    authViewModel.logout()
                    navController.navigate(Screen.Auth.route) {
                        popUpTo(Screen.Main.route) { inclusive = true }
                    }
                },
                homeViewModel = homeViewModel,
                signinViewModel = signinViewModel,
                tdViewModel = tdViewModel,
                sparkViewModel = sparkViewModel,
                profileViewModel = profileViewModel
            )
        }
    }
}

@Composable
fun MainContainer(
    onLogout: () -> Unit,
    homeViewModel: HomeViewModel,
    signinViewModel: SigninViewModel,
    tdViewModel: TdViewModel,
    sparkViewModel: SparkViewModel,
    profileViewModel: ProfileViewModel
) {
    val tabNavController = rememberNavController()
    val navBackStackEntry by tabNavController.currentBackStackEntryAsState()
    val currentDestination = navBackStackEntry?.destination

    Scaffold(
        bottomBar = {
            NavigationBar(
                containerColor = MaterialTheme.colorScheme.surface,
                tonalElevation = 6.dp
            ) {
                bottomTabs.forEach { tab ->
                    val route = currentDestination?.route
                    val isSelected = route == tab.route || (tab == BottomTab.Features && route?.startsWith("feature/") == true)
                    NavigationBarItem(
                        icon = {
                            Icon(
                                imageVector = if (isSelected) tab.selectedIcon else tab.unselectedIcon,
                                contentDescription = tab.title
                            )
                        },
                        label = { Text(tab.title) },
                        selected = isSelected,
                        colors = NavigationBarItemDefaults.colors(
                            selectedIconColor = MaterialTheme.colorScheme.primary,
                            selectedTextColor = MaterialTheme.colorScheme.primary,
                            indicatorColor = MaterialTheme.colorScheme.primaryContainer,
                            unselectedIconColor = MaterialTheme.colorScheme.onSurfaceVariant,
                            unselectedTextColor = MaterialTheme.colorScheme.onSurfaceVariant
                        ),
                        onClick = {
                            tabNavController.navigate(tab.route) {
                                popUpTo(tabNavController.graph.findStartDestination().id) {
                                    saveState = true
                                }
                                launchSingleTop = true
                                restoreState = true
                            }
                        }
                    )
                }
            }
        }
    ) { paddingValues ->
        NavHost(
            navController = tabNavController,
            startDestination = BottomTab.Home.route,
            modifier = Modifier.padding(paddingValues)
        ) {
            composable(BottomTab.Home.route) {
                HomeScreen(
                    viewModel = homeViewModel,
                    onNavigateToFeature = { feature ->
                        tabNavController.navigate("feature/$feature")
                    }
                )
            }
            composable(BottomTab.Features.route) {
                FeaturesScreen(
                    signinViewModel = signinViewModel,
                    onOpenSignin = { tabNavController.navigate("feature/signin") },
                    onOpenTd = { tabNavController.navigate("feature/td") },
                    onOpenSpark = { tabNavController.navigate("feature/spark") },
                    onRequest = { signinViewModel.requestFeature(it) }
                )
            }
            composable("feature/signin") { SigninScreen(viewModel = signinViewModel) }
            composable("feature/td") { TdScreen(viewModel = tdViewModel) }
            composable("feature/spark") { SparkScreen(viewModel = sparkViewModel) }
            composable(BottomTab.Profile.route) {
                ProfileScreen(
                    viewModel = profileViewModel,
                    onLogout = onLogout
                )
            }
        }
    }
}
