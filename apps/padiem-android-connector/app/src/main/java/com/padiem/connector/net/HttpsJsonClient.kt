package com.padiem.connector.net

import com.padiem.connector.contract.AndroidConnectorContract
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.nio.charset.StandardCharsets

/**
 * One HTTPS JSON POST seam, shared by the private broker device surface and the existing
 * connector enrollment API. Cleartext, userinfo, query-carried secrets and redirects are
 * refused at construction or per call: a redirected POST would re-send the device credential
 * to a target this client never validated.
 */
class HttpsJsonClient(
    endpoint: String,
    private val connectTimeoutMillis: Int = 10_000,
    private val readTimeoutMillis: Int = 30_000,
) : JsonClient {

    private val base: String = normalize(endpoint)

    override fun post(path: String, bodyJson: String): DeviceHttpResponse {
        val payload = bodyJson.toByteArray(Charsets.UTF_8)
        if (payload.size > AndroidConnectorContract.MAX_REQUEST_BODY_BYTES) {
            throw DeviceProtocolException("request exceeds the JSON body bound")
        }
        val connection = open(base + path.removePrefix("/"))
        return try {
            connection.outputStream.use { it.write(payload) }
            val status = connection.responseCode
            DeviceHttpResponse(status, readBounded(connection, status >= 400))
        } catch (error: IOException) {
            throw DeviceOfflineException("endpoint unreachable", error)
        } finally {
            connection.disconnect()
        }
    }

    private fun open(target: String): HttpURLConnection =
        (URL(target).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            doOutput = true
            instanceFollowRedirects = false
            connectTimeout = connectTimeoutMillis
            readTimeout = readTimeoutMillis
            setRequestProperty("Content-Type", "application/json")
            setRequestProperty("Accept", "application/json")
            setRequestProperty("Cache-Control", "no-store")
        }

    private fun readBounded(connection: HttpURLConnection, isError: Boolean): String {
        val stream = if (isError) connection.errorStream else connection.inputStream
        if (stream == null) return ""
        stream.use { input ->
            val collected = ByteArrayOutputStream(16_384)
            val chunk = ByteArray(8_192)
            var overflowed = false
            while (true) {
                val read = input.read(chunk)
                if (read == -1) break
                if (collected.size() + read > AndroidConnectorContract.MAX_RESPONSE_BODY_BYTES) {
                    overflowed = true
                    continue
                }
                collected.write(chunk, 0, read)
            }
            if (overflowed) throw DeviceProtocolException("response exceeds the JSON body bound")
            return String(collected.toByteArray(), StandardCharsets.UTF_8)
        }
    }

    private companion object {
        fun normalize(endpoint: String): String {
            val url = try {
                URL(endpoint)
            } catch (error: java.net.MalformedURLException) {
                throw DeviceProtocolException("endpoint is not a valid URL", error)
            }
            val cleared = url.toExternalForm()
            if (url.protocol.lowercase() != "https" || url.host.isEmpty() || url.userInfo != null ||
                url.query != null || url.ref != null
            ) {
                throw DeviceProtocolException("endpoint must be an HTTPS origin without credentials or a query")
            }
            return if (cleared.endsWith("/")) cleared else cleared + "/"
        }
    }
}
