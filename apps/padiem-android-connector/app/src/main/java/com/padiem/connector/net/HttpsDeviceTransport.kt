package com.padiem.connector.net

import com.padiem.connector.contract.AndroidConnectorContract

/**
 * The production device surface: HTTPS POST per broker route, route-allowlisted. The broker
 * trusts TLS termination at its own edge, so a cleartext endpoint is refused here rather than
 * negotiated.
 */
class HttpsDeviceTransport(private val client: HttpsJsonClient) : DeviceTransport {

    constructor(endpoint: String) : this(HttpsJsonClient(endpoint))

    override fun post(route: String, bodyJson: String): DeviceHttpResponse {
        if (!AndroidConnectorContract.DEVICE_ROUTES.contains(route)) {
            throw DeviceProtocolException("unknown device route")
        }
        return client.post(route, bodyJson)
    }
}
