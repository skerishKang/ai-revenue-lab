package com.padiem.connector.net

/**
 * One JSON POST to a fixed path, returning the status and body text.
 *
 * `HttpsJsonClient` is the production implementation; a test surface implements the same seam so
 * the enrollment and profile contract paths can be exercised without a deployed endpoint. Keeping
 * this narrow means the client's request shapes are verified without pretending to own transport
 * security, which lives in `HttpsJsonClient`.
 */
fun interface JsonClient {
    fun post(path: String, bodyJson: String): DeviceHttpResponse
}
