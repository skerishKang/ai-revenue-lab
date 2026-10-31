package com.padiem.connector.data

import com.padiem.connector.contract.AndroidConnectorContract
import com.padiem.connector.contract.Json
import java.security.SecureRandom

/**
 * The phone's own stable device handle, plus the live broker session identifier.
 *
 * `device_id` is minted once and persisted, because enrollment, consent and the declared folder
 * set are all bound to it: a new value every launch would look like a new device to the owner's
 * consent row. A session id is deliberately NOT persisted — it is one live session, and the
 * broker decides whether it is current.
 */
class DeviceIdentityStore(
    private val store: LocalStateStore,
    private val random: (Int) -> String = { length -> randomHex(length) },
) {

    private var cachedDeviceId: String? = null

    fun deviceId(): String {
        cachedDeviceId?.let { return it }
        val stored = store.load()?.let { Json.parse(it) as? Map<*, *> }
        val existing = stored?.get("device_id") as? String
        if (existing != null && AndroidConnectorContract.isOpaqueRef(existing)) {
            cachedDeviceId = existing
            return existing
        }
        val minted = "device.android." + random(24)
        store.save(Json.encode(linkedMapOf<String, Any?>("device_id" to minted)))
        cachedDeviceId = minted
        return minted
    }

    fun newSessionId(): String = "session.android." + random(24)

    /** One `/material` correlation ref. The broker stores it; nothing derives authority from it. */
    fun newRequestRef(): String = REQUEST_REF_PREFIX + random(24)

    private companion object {
        const val REQUEST_REF_PREFIX = "andreq-"

        fun randomHex(length: Int): String {
            val bytes = ByteArray(length / 2)
            SecureRandom().nextBytes(bytes)
            return bytes.joinToString("") { byte ->
                ((byte.toInt() and 0xFF) + 256).toString(16).substring(1)
            }
        }
    }
}
