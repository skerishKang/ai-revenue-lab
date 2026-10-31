package com.padiem.connector.contract

import com.google.gson.JsonElement
import com.google.gson.JsonParser

/**
 * Decoded JSON is deliberately plain: `Map<String, Any?>`, `List<Any?>`, `String`,
 * `Boolean`, `Long`, `Double` and `null`. The wire contract is validated against those
 * values in one place instead of across generated model classes, so an unexpected key is
 * visible as a shape failure rather than being silently dropped.
 *
 * Parsing reuses Gson (adopted dependency); serialization is written here because the
 * SAF read fingerprint must be byte-identical to the server's
 * `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"))`.
 */
object Json {

    fun parse(text: String): Any? {
        if (text.isEmpty()) return null
        return try {
            JsonParser.parseString(text).toValue()
        } catch (error: RuntimeException) {
            null
        }
    }

    fun parseObject(text: String): Map<String, Any?>? {
        val value = parse(text)
        return value as? Map<String, Any?>
    }

    fun encode(value: Any?): String {
        val builder = StringBuilder()
        write(builder, value)
        return builder.toString()
    }

    /** Sorted-key, no-whitespace form used by the canonical fingerprint transcript. */
    fun encodeCanonical(value: Map<String, Any?>): String {
        val builder = StringBuilder()
        write(builder, value.toSortedMap())
        return builder.toString()
    }

    private fun write(builder: StringBuilder, value: Any?) {
        when (value) {
            null -> builder.append("null")
            is String -> writeString(builder, value)
            is Boolean -> builder.append(if (value) "true" else "false")
            is Int -> builder.append(value.toString())
            is Long -> builder.append(value.toString())
            is Double -> builder.append(numberText(value))
            is Map<*, *> -> writeObject(builder, value)
            is List<*> -> writeArray(builder, value)
            else -> throw IllegalArgumentException("unsupported JSON value: " + value::class.java.name)
        }
    }

    private fun writeObject(builder: StringBuilder, value: Map<*, *>) {
        builder.append('{')
        var first = true
        for ((key, item) in value) {
            require(key is String) { "object keys must be strings" }
            if (!first) builder.append(',')
            first = false
            writeString(builder, key)
            builder.append(':')
            write(builder, item)
        }
        builder.append('}')
    }

    private fun writeArray(builder: StringBuilder, value: List<*>) {
        builder.append('[')
        value.forEachIndexed { index, item ->
            if (index > 0) builder.append(',')
            write(builder, item)
        }
        builder.append(']')
    }

    /** Python's `ensure_ascii=False` escaping: no slash escaping, raw non-ASCII UTF-8. */
    private fun writeString(builder: StringBuilder, value: String) {
        builder.append('"')
        for (character in value) {
            when (character) {
                '"' -> builder.append("\\\"")
                '\\' -> builder.append("\\\\")
                '\b' -> builder.append("\\b")
                '\u000C' -> builder.append("\\f")
                '\n' -> builder.append("\\n")
                '\r' -> builder.append("\\r")
                '\t' -> builder.append("\\t")
                else -> if (character.code < 0x20) {
                    builder.append("\\u").append(String.format("%04x", character.code))
                } else {
                    builder.append(character)
                }
            }
        }
        builder.append('"')
    }

    private fun numberText(value: Double): String =
        if (value.isFinite() && value == Math.floor(value) && kotlin.math.abs(value) < 9.0E15) {
            value.toLong().toString()
        } else {
            value.toString()
        }

    private fun JsonElement?.toValue(): Any? {
        if (this == null || isJsonNull) return null
        if (isJsonObject) {
            val fields = LinkedHashMap<String, Any?>()
            for ((key, item) in asJsonObject.entrySet()) {
                fields[key] = item.toValue()
            }
            return fields
        }
        if (isJsonArray) {
            return asJsonArray.map { it.toValue() }
        }
        val primitive = asJsonPrimitive
        if (primitive.isBoolean) return primitive.asBoolean
        if (primitive.isString) return primitive.asString
        return numberFrom(primitive.asString)
    }

    private fun numberFrom(literal: String): Any {
        val normalized = if (literal.startsWith("+")) literal.substring(1) else literal
        return if (
            !normalized.contains('.') && !normalized.contains('e') && !normalized.contains('E')
        ) {
            normalized.toLong()
        } else {
            normalized.toDouble()
        }
    }
}
