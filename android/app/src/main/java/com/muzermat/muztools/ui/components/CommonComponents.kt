package com.muzermat.muztools.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
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
        "approved", "通过", "已通过", "signed", "已签到" -> {
            Tuple4(SuccessColor.copy(alpha = 0.15f), SuccessColor, if (status == "signed" || status == "已签到") "已签到" else "已通过", Icons.Default.CheckCircle)
        }
        "pending", "待审批", "待签到" -> {
            Tuple4(WarningColor.copy(alpha = 0.15f), WarningColor, if (status == "pending" || status == "待审批") "待审批" else "待签到", Icons.Default.HourglassEmpty)
        }
        "rejected", "已拒绝", "未签到", "missed" -> {
            Tuple4(ErrorColor.copy(alpha = 0.15f), ErrorColor, if (status == "rejected" || status == "已拒绝") "已拒绝" else "未签到", Icons.Default.Error)
        }
        else -> {
            Tuple4(InfoColor.copy(alpha = 0.15f), InfoColor, "未绑定", Icons.Default.Info)
        }
    }

    Surface(
        color = bgColor,
        shape = RoundedCornerShape(12.dp),
        modifier = modifier
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = textColor,
                modifier = Modifier.size(14.dp)
            )
            Spacer(modifier = Modifier.width(4.dp))
            Text(
                text = text,
                color = textColor,
                fontSize = 12.sp,
                fontWeight = FontWeight.Medium
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
            .padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(
            text = title,
            style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.Bold),
            color = MaterialTheme.colorScheme.onSurface
        )
        action?.invoke()
    }
}

@Composable
fun PendingApprovalBanner(
    modifier: Modifier = Modifier,
    message: String = "学生认证待审批中，审批通过后方可开启自动签到"
) {
    Card(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.tertiaryContainer.copy(alpha = 0.6f)
        ),
        shape = RoundedCornerShape(12.dp)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(
                modifier = Modifier
                    .size(36.dp)
                    .clip(CircleShape)
                    .background(MaterialTheme.colorScheme.tertiary.copy(alpha = 0.2f)),
                contentAlignment = Alignment.Center
            ) {
                Icon(
                    imageVector = Icons.Default.HourglassEmpty,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.tertiary,
                    modifier = Modifier.size(20.dp)
                )
            }
            Spacer(modifier = Modifier.width(12.dp))
            Text(
                text = message,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onTertiaryContainer
            )
        }
    }
}

private data class Tuple4<A, B, C, D>(val a: A, val b: B, val c: C, val d: D)
