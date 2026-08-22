package com.muzermat.muztools.data.local

object Credentials {
    private val usernameRegex = Regex("^[A-Za-z0-9_]{6,18}$")

    fun validateUsername(username: String): String? {
        val name = username.trim()
        if (!usernameRegex.matches(name)) {
            return "账号须为 6～18 位字母、数字或下划线"
        }
        return null
    }

    fun validatePassword(password: String): String? {
        if (password.length !in 6..18) return "密码须为 6～18 位"
        if (!password.any { it.isDigit() }) return "密码必须包含数字"
        if (!password.any { it.isLowerCase() }) return "密码必须包含小写字母"
        if (!password.any { it.isUpperCase() }) return "密码必须包含大写字母"
        return null
    }
}
