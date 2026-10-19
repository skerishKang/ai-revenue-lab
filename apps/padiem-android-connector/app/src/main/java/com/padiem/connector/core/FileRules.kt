package com.padiem.connector.core

import java.util.Locale
import kotlin.math.roundToInt

object FileRules {
    fun isTxtFile(displayName: String): Boolean =
        displayName.endsWith(".txt", ignoreCase = true)

    fun formatBytes(bytes: Long?): String? {
        if (bytes == null || bytes < 0) return null
        if (bytes < 1024) return "$bytes B"

        val units = arrayOf("KB", "MB", "GB", "TB")
        var value = bytes / 1024.0
        var unitIndex = 0
        while (value >= 1024 && unitIndex < units.lastIndex) {
            value /= 1024
            unitIndex++
        }
        return if (value >= 10) {
            "${value.roundToInt()} ${units[unitIndex]}"
        } else {
            String.format(Locale.US, "%.1f %s", value, units[unitIndex])
        }
    }
}
