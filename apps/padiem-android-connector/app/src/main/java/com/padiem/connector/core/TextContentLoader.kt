package com.padiem.connector.core

import java.io.ByteArrayOutputStream
import java.io.InputStream

data class TextContent(
    val text: String,
    val byteCount: Int,
    val truncated: Boolean,
)

object TextContentLoader {
    const val DEFAULT_MAX_BYTES = 128 * 1024

    fun readUtf8(input: InputStream, maxBytes: Int = DEFAULT_MAX_BYTES): TextContent {
        require(maxBytes > 0) { "maxBytes must be positive" }

        val output = ByteArrayOutputStream(minOf(maxBytes, 8192))
        val buffer = ByteArray(8192)
        var truncated = false

        while (true) {
            val read = input.read(buffer)
            if (read == -1) break

            val remaining = maxBytes - output.size()
            if (read > remaining) {
                output.write(buffer, 0, remaining)
                truncated = true
                break
            }

            output.write(buffer, 0, read)
            if (output.size() == maxBytes) {
                truncated = input.read() != -1
                break
            }
        }

        var bytes = output.toByteArray()
        if (truncated) {
            bytes = dropIncompleteTrailingCodePoint(bytes)
        }

        val text = String(bytes, Charsets.UTF_8).removePrefix("\uFEFF")
        return TextContent(text = text, byteCount = bytes.size, truncated = truncated)
    }

    internal fun dropIncompleteTrailingCodePoint(bytes: ByteArray): ByteArray {
        if (bytes.isEmpty()) return bytes

        var leadIndex = bytes.lastIndex
        while (leadIndex >= 0 && (bytes[leadIndex].toInt() and 0xC0) == 0x80) {
            leadIndex--
        }
        if (leadIndex < 0) return bytes

        val lead = bytes[leadIndex].toInt() and 0xFF
        val expectedLength = when {
            lead and 0x80 == 0 -> 1
            lead and 0xE0 == 0xC0 -> 2
            lead and 0xF0 == 0xE0 -> 3
            lead and 0xF8 == 0xF0 -> 4
            else -> return bytes
        }
        val actualLength = bytes.size - leadIndex
        return if (expectedLength > 1 && actualLength < expectedLength) {
            bytes.copyOf(leadIndex)
        } else {
            bytes
        }
    }
}
