package com.muzermat.muztools.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.HourglassEmpty
import androidx.compose.material.icons.filled.Info
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.muzermat.muztools.ui.theme.ErrorColor
import com.muzermat.muztools.ui.theme.InfoColor
import com.muzermat.muztools.ui.theme.SuccessColor
import com.muzermat.muztools.ui.theme.WarningColor

@Composable
fun StatusBadge(
    status: String,
    modifier: Modifier = Modifier
) {
    val (bgColor, textColor, text, icon) = when (status.lowercase()) {
        "approved", "available", "verified", "通过", "已通过", "已认证" -> {
            Tuple4(SuccessColor.copy(alpha = 0.12f), SuccessColor, if (status.lowercase() == "verified" || status == "已认证") "已认证" else "可用", Icons.Default.CheckCircle)
        }
        "signed", "已签到" -> {
            Tuple4(SuccessColor.copy(alpha = 0.12f), SuccessColor, "已签到", Icons.Default.CheckCircle)
        }
        "pending", "待处理", "待签到" -> {
            Tuple4(WarningColor.copy(alpha = 0.15f), Color(0xFFC07000), if (status == "待签到") "待签到" else "待处理", Icons.Default.HourglassEmpty)
        }
        "rejected", "failed", "认证失败", "未签到", "missed" -> {
            Tuple4(ErrorColor.copy(alpha = 0.12f), ErrorColor, if (status == "未签到" || status.lowercase() == "missed") "未签到" else "认证失败", Icons.Default.Error)
        }
        "unbound", "未绑定" -> {
            Tuple4(InfoColor.copy(alpha = 0.12f), InfoColor, "未绑定", Icons.Default.Info)
        }
        else -> {
            Tuple4(InfoColor.copy(alpha = 0.12f), InfoColor, "未配置", Icons.Default.Info)
        }
    }

    Surface(
        color = bgColor,
        shape = RoundedCornerShape(20.dp),
        modifier = modifier
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = textColor,
                modifier = Modifier.size(13.dp)
            )
            Spacer(modifier = Modifier.width(4.dp))
            Text(
                text = text,
                color = textColor,
                fontSize = 12.sp,
                fontWeight = FontWeight.SemiBold
            )
        }
    }
}

@Composable
fun SectionHeader(
    title: String,
    modifier: Modifier = Modifier,
    action: (@Composable () -> Unit)? = null
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                modifier = Modifier
                    .width(3.5.dp)
                    .height(14.dp)
                    .clip(RoundedCornerShape(2.dp))
                    .background(MaterialTheme.colorScheme.primary)
            )
            Spacer(modifier = Modifier.width(8.dp))
            Text(
                text = title,
                style = MaterialTheme.typography.titleMedium.copy(
                    fontWeight = FontWeight.Bold,
                    fontSize = 16.sp
                ),
                color = MaterialTheme.colorScheme.onSurface
            )
        }
        action?.invoke()
    }
}

private data class Tuple4<A, B, C, D>(val a: A, val b: B, val c: C, val d: D)
