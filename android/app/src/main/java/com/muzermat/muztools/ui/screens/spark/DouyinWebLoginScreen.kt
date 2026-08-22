package com.muzermat.muztools.ui.screens.spark

import android.annotation.SuppressLint
import android.webkit.CookieManager
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView

@SuppressLint("SetJavaScriptEnabled")
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DouyinWebLoginScreen(
    onCaptured: (String) -> Unit,
    onClose: () -> Unit
) {
    val cookieManager = remember { CookieManager.getInstance() }
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("抖音登录") },
                navigationIcon = {
                    IconButton(onClick = onClose) {
                        Icon(Icons.Default.Close, contentDescription = "关闭")
                    }
                },
                actions = {
                    TextButton(onClick = {
                        cookieManager.flush()
                        val cookie = listOf(
                            "https://www.douyin.com",
                            "https://creator.douyin.com",
                            "https://m.douyin.com"
                        ).mapNotNull { cookieManager.getCookie(it) }
                            .firstOrNull { it.isNotBlank() }
                            .orEmpty()
                        onCaptured(cookie)
                    }) {
                        Text("完成")
                    }
                }
            )
        }
    ) { padding ->
        AndroidView(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
            factory = { context ->
                WebView(context).apply {
                    settings.javaScriptEnabled = true
                    settings.domStorageEnabled = true
                    settings.cacheMode = WebSettings.LOAD_DEFAULT
                    settings.userAgentString = settings.userAgentString.replace("; wv", "")
                    cookieManager.setAcceptCookie(true)
                    cookieManager.setAcceptThirdPartyCookies(this, true)
                    webViewClient = WebViewClient()
                    loadUrl("https://www.douyin.com/")
                }
            }
        )
    }
}
