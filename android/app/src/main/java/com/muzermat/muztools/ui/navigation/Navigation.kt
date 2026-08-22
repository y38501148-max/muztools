package com.muzermat.muztools.ui.navigation

import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.*
import com.muzermat.muztools.ui.screens.auth.AuthScreen
import com.muzermat.muztools.ui.screens.auth.AuthViewModel
import com.muzermat.muztools.ui.screens.home.HomeScreen
import com.muzermat.muztools.ui.screens.home.HomeViewModel
import com.muzermat.muztools.ui.screens.profile.ProfileScreen
import com.muzermat.muztools.ui.screens.profile.ProfileViewModel
import com.muzermat.muztools.ui.screens.signin.SigninScreen
import com.muzermat.muztools.ui.screens.signin.SigninViewModel
import com.muzermat.muztools.ui.screens.spark.SparkScreen
import com.muzermat.muztools.ui.screens.spark.SparkViewModel

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
    object Signin : BottomTab("tab_signin", "自动签到", Icons.Filled.FactCheck, Icons.Outlined.FactCheck)
    object Td : BottomTab("tab_td", "TD", Icons.Filled.DirectionsRun, Icons.Outlined.DirectionsRun)
    object Spark : BottomTab("tab_spark", "火花", Icons.Filled.ElectricBolt, Icons.Outlined.ElectricBolt)
    object Profile : BottomTab("tab_profile", "我的", Icons.Filled.Person, Icons.Outlined.Person)
}

val bottomTabs = listOf(
    BottomTab.Home,
    BottomTab.Signin,
    BottomTab.Td,
    BottomTab.Spark,
    BottomTab.Profile
)

@Composable
fun AppNavigation(
    authViewModel: AuthViewModel,
    homeViewModel: HomeViewModel,
    signinViewModel: SigninViewModel,
    tdViewModel: com.muzermat.muztools.ui.screens.td.TdViewModel,
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
    tdViewModel: com.muzermat.muztools.ui.screens.td.TdViewModel,
    sparkViewModel: SparkViewModel,
    profileViewModel: ProfileViewModel
) {
    val tabNavController = rememberNavController()
    val navBackStackEntry by tabNavController.currentBackStackEntryAsState()
    val currentDestination = navBackStackEntry?.destination

    Scaffold(
        bottomBar = {
            NavigationBar {
                bottomTabs.forEachIndexed { index, tab ->
                    val isSelected = currentDestination?.route == tab.route
                    NavigationBarItem(
                        icon = {
                            Icon(
                                imageVector = if (isSelected) tab.selectedIcon else tab.unselectedIcon,
                                contentDescription = tab.title
                            )
                        },
                        label = { Text(tab.title) },
                        selected = isSelected,
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
                    onNavigateToTab = { index ->
                        if (index in bottomTabs.indices) {
                            tabNavController.navigate(bottomTabs[index].route) {
                                popUpTo(tabNavController.graph.findStartDestination().id) {
                                    saveState = true
                                }
                                launchSingleTop = true
                                restoreState = true
                            }
                        }
                    }
                )
            }
            composable(BottomTab.Signin.route) {
                SigninScreen(viewModel = signinViewModel)
            }
            composable(BottomTab.Td.route) {
                com.muzermat.muztools.ui.screens.td.TdScreen(viewModel = tdViewModel)
            }
            composable(BottomTab.Spark.route) {
                SparkScreen(viewModel = sparkViewModel)
            }
            composable(BottomTab.Profile.route) {
                ProfileScreen(
                    viewModel = profileViewModel,
                    onLogout = onLogout
                )
            }
        }
    }
}
