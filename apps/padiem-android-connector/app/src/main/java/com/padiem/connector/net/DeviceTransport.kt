package com.padiem.connector.net

/** One device-surface reply: the broker status code and the JSON text it returned. */
data class DeviceHttpResponse(val status: Int, val body: String)

/**
 * The phone's only network seam. `route` is a broker route (`/poll`, `/material`, ...) and
 * `bodyJson` is the exact bytes to send, so a retry can resend a byte-identical request.
 */
interface DeviceTransport {
    fun post(route: String, bodyJson: String): DeviceHttpResponse

    companion object {
        /**
         * A transport that reports every call as offline. It is the value the runner holds
         * before a device-surface endpoint exists in this deployment, so "no network" stays
         * an explicit state instead of a silent `null`.
         */
        fun unavailable(): DeviceTransport = object : DeviceTransport {
            override fun post(route: String, bodyJson: String): DeviceHttpResponse =
                throw DeviceOfflineException("device surface is not configured")
        }
    }
}

/** No terminal fact was learned: the caller must keep its state and retry the same command. */
class DeviceOfflineException(message: String, cause: Throwable? = null) : Exception(message, cause)

/** The reply could not be read, was oversized, or was not the JSON object the contract promises. */
class DeviceProtocolException(message: String, cause: Throwable? = null) : Exception(message, cause)
