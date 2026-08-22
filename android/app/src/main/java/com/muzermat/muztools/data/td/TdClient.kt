package com.muzermat.muztools.data.td

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive
import java.io.DataInputStream
import java.io.DataOutputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.nio.charset.StandardCharsets
import java.util.Calendar
import java.util.TimeZone

data class TdMachine(
    val id: Int,
    val sn: String,
    val location: String,
)

data class TdStepResult(
    val success: Boolean,
    val message: String,
    val count: Int?,
    val timestampMs: Long,
    val location: String,
)

data class TdManualResult(
    val success: Boolean,
    val message: String,
    val count: Int?,
    val entrance: TdStepResult?,
    val exit: TdStepResult?,
)

object TdClient {
    const val SERVER_HOST = "10.212.28.38"
    const val SERVER_PORT = 8888
    private const val CHECK_TYPE = 80
    private const val PHOTO_TYPE = 100
    private const val TIMEOUT_MS = 10_000

    private val json = Json { ignoreUnknownKeys = true }
    private val windows = listOf(
        7 * 60 + 30 to 10 * 60,
        11 * 60 + 30 to 14 * 60,
        15 * 60 + 30 to 20 * 60,
    )
    private val countRegex = Regex("本学期锻炼次数\\s*[:：]\\s*(\\d+)")

    private val machines = mapOf(
        "学院路" to (
            listOf(
                TdMachine(2, "20211025001", "北航本部TD入口1"),
                TdMachine(4, "20230417001", "北航本部TD入口2"),
                TdMachine(3, "20220301004", "北航本部TD入口3"),
            ) to listOf(
                TdMachine(6, "20210420002", "北航本部TD出口1"),
                TdMachine(5, "20210421003", "北航本部TD出口2"),
                TdMachine(7, "20220301003", "北航本部TD出口3"),
            )
        ),
        "沙河" to (
            listOf(
                TdMachine(8, "20210511001", "北航沙河TD入口1"),
                TdMachine(9, "20210511002", "北航沙河TD入口2"),
                TdMachine(10, "20210511003", "北航沙河TD入口3"),
            ) to listOf(
                TdMachine(11, "20220218001", "北航沙河TD出口1"),
                TdMachine(12, "20220218002", "北航沙河TD出口2"),
                TdMachine(13, "20220218003", "北航沙河TD出口3"),
            )
        ),
    )

    fun defaultMachines(campus: String): Pair<TdMachine, TdMachine> {
        val pair = machines[campus] ?: machines.getValue("学院路")
        return pair.first.first() to pair.second.first()
    }

    fun cardIdFromStudent(studentId: String): String =
        studentId.trim().toLong().toString(16).uppercase()

    fun planTimestamps(gapSeconds: Int, nowMs: Long = System.currentTimeMillis()): Pair<Long, Long> {
        if (windowIndex(beijingMinutes(nowMs)) == null) {
            error("当前时间不在 TD 打卡窗口内（07:30-10:00 / 11:30-14:00 / 15:30-20:00），且需连接校园网")
        }
        val gap = gapSeconds.coerceIn(60, 3600)
        val exitMs = nowMs + gap * 1000L
        if (windowIndex(beijingMinutes(exitMs)) == null) {
            error("伪造出口时间超出合法打卡窗口，请缩短时间差")
        }
        return nowMs to exitMs
    }

    fun manualCheck(
        studentId: String,
        campus: String,
        entrancePhoto: ByteArray,
        exitPhoto: ByteArray,
        gapSeconds: Int = 240,
        entranceMachineId: Int? = null,
        exitMachineId: Int? = null,
    ): TdManualResult {
        if (studentId.isBlank()) error("尚未绑定学号")
        if (entrancePhoto.isEmpty() || exitPhoto.isEmpty()) error("请先选择入口图和出口图")

        val (defaultIn, defaultOut) = defaultMachines(campus)
        val entranceMachine = findMachine(campus, entranceMachineId, defaultIn, entrance = true)
        val exitMachine = findMachine(campus, exitMachineId, defaultOut, entrance = false)
        val (entranceTs, exitTs) = planTimestamps(gapSeconds)

        val entrance = checkAndUpload(studentId, entranceMachine, entrancePhoto, entranceTs)
        if (!entrance.success) {
            return TdManualResult(
                success = false,
                message = "入口打卡失败：${entrance.message}",
                count = entrance.count,
                entrance = entrance,
                exit = null,
            )
        }
        val exit = checkAndUpload(studentId, exitMachine, exitPhoto, exitTs)
        return TdManualResult(
            success = exit.success,
            message = if (exit.success) "TD 手动打卡完成" else "出口打卡失败：${exit.message}",
            count = exit.count ?: entrance.count,
            entrance = entrance,
            exit = exit,
        )
    }

    private fun findMachine(campus: String, id: Int?, fallback: TdMachine, entrance: Boolean): TdMachine {
        if (id == null) return fallback
        val pair = machines[campus] ?: machines.getValue("学院路")
        val list = if (entrance) pair.first else pair.second
        return list.firstOrNull { it.id == id } ?: fallback
    }

    private fun checkAndUpload(
        studentId: String,
        machine: TdMachine,
        photo: ByteArray,
        timestampMs: Long,
    ): TdStepResult {
        val payload = """
            {"cardno":"${cardIdFromStudent(studentId)}","userno":"${studentId.uppercase()}","timestamp":"$timestampMs","type":1,"eventno":"802","ln":"${machine.id}","sn":"${machine.sn}","schoolno":"10006"}
        """.trimIndent().toByteArray(StandardCharsets.UTF_8)
        val response = tcpRequest(payload, CHECK_TYPE)
        val message = clean(response["srvresp"] ?: "")
        val success = (response["srvresp"] ?: "").contains("成功")
        if (response["status"] != "success") {
            error("TD 打卡请求失败：${response["status"]}")
        }
        if (success && photo.isNotEmpty()) {
            val photoPayload = "${machine.sn}_$timestampMs".toByteArray(StandardCharsets.UTF_8) + photo
            val upload = tcpRequest(photoPayload, PHOTO_TYPE)
            if (upload["status"] != "success") {
                error("TD 照片上传失败：${upload["status"]}")
            }
        }
        return TdStepResult(
            success = success,
            message = message,
            count = countRegex.find(message)?.groupValues?.getOrNull(1)?.toIntOrNull(),
            timestampMs = timestampMs,
            location = machine.location,
        )
    }

    private fun tcpRequest(payload: ByteArray, type: Int): Map<String, String> {
        Socket().use { socket ->
            socket.connect(InetSocketAddress(SERVER_HOST, SERVER_PORT), TIMEOUT_MS)
            socket.soTimeout = TIMEOUT_MS
            val output = DataOutputStream(socket.getOutputStream())
            output.writeInt(payload.size)
            output.writeByte(type)
            output.write(payload)
            output.flush()
            val input = DataInputStream(socket.getInputStream())
            val length = input.readInt()
            input.readUnsignedByte()
            if (length <= 0) error("TD 服务器返回空响应")
            val body = ByteArray(length)
            input.readFully(body)
            val parsed = json.parseToJsonElement(body.toString(StandardCharsets.UTF_8))
            if (parsed !is JsonObject) error("TD 服务器返回无效 JSON")
            return parsed.entries.associate { (key, value) ->
                key to (value.jsonPrimitive.contentOrNull ?: value.toString())
            }
        }
    }

    private fun clean(message: String): String =
        message.trim().replace("\n \n", "\n").replace("\n", ", ")

    private fun beijingMinutes(tsMs: Long): Int {
        val calendar = Calendar.getInstance(TimeZone.getTimeZone("GMT+08:00"))
        calendar.timeInMillis = tsMs
        return calendar.get(Calendar.HOUR_OF_DAY) * 60 + calendar.get(Calendar.MINUTE)
    }

    private fun windowIndex(minutes: Int): Int? =
        windows.indexOfFirst { minutes in it.first..it.second }.takeIf { it >= 0 }
}
