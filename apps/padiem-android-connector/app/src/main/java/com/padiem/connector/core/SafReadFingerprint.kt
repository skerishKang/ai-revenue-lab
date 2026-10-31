package com.padiem.connector.core

import com.padiem.connector.contract.AndroidConnectorContract
import com.padiem.connector.contract.Json
import java.security.MessageDigest
import java.text.Normalizer

/**
 * The canonical SAF read fingerprint from #5163 §6.1. The phone recomputes it over the
 * receipt's own intent and requires it to match both `approval_pause.invocation_sha256`
 * and `exact_tool_arguments.request_fingerprint` before touching a document, so a
 * re-packaged or stale receipt cannot be executed as if it were the approved read.
 */
object SafReadFingerprint {

    fun compute(
        actionId: String,
        runId: String,
        deviceId: String,
        rootRef: String,
        pathRelative: String,
        requestedAt: String,
    ): String = sha256Hex(
        canonicalTranscript(actionId, runId, deviceId, rootRef, pathRelative, requestedAt)
            .toByteArray(Charsets.UTF_8),
    )

    /** The exact bytes that are hashed, so a mismatch is a diffable string rather than a mystery. */
    fun canonicalTranscript(
        actionId: String,
        runId: String,
        deviceId: String,
        rootRef: String,
        pathRelative: String,
        requestedAt: String,
    ): String = Json.encodeCanonical(
        mapOf(
            "v" to 1L,
            "action_id" to actionId,
            "run_id" to runId,
            "device_id" to deviceId,
            "root_ref" to rootRef,
            "operation" to AndroidConnectorContract.READ_OPERATION,
            "path_relative" to Normalizer.normalize(pathRelative, Normalizer.Form.NFC),
            "requested_at" to requestedAt,
        ),
    )

    fun sha256Hex(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(bytes).toHex()

    fun hmacSha256Hex(key: ByteArray, message: ByteArray): String {
        val mac = javax.crypto.Mac.getInstance("HmacSHA256")
        mac.init(javax.crypto.spec.SecretKeySpec(key, "HmacSHA256"))
        return mac.doFinal(message).toHex()
    }

    private fun ByteArray.toHex(): String {
        val builder = StringBuilder(size * 2)
        for (byte in this) {
            builder.append(Character.forDigit((byte.toInt() shr 4) and 0x0F, 16))
            builder.append(Character.forDigit(byte.toInt() and 0x0F, 16))
        }
        return builder.toString()
    }
}
