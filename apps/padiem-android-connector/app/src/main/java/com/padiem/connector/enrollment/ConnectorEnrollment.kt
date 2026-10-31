package com.padiem.connector.enrollment

import com.padiem.connector.contract.AndroidConnectorContract
import com.padiem.connector.contract.Json
import com.padiem.connector.core.SafReadFingerprint
import com.padiem.connector.data.DeviceCredentialVault
import com.padiem.connector.net.DeviceOfflineException
import com.padiem.connector.net.JsonClient
import java.time.Instant
import java.time.format.DateTimeParseException

/**
 * The existing connector enrollment API, spoken by the phone (#5163 §3).
 *
 * There is no Android enrollment route: the device redeems the owner-issued challenge through
 * the same canonical endpoint as every other device, and the public response is secret-free by
 * construction — `raw_device_credential` is `false`. The raw credential arrives only through the
 * canonical protected handoff, which is the seam [CanonicalCredentialHandoff] below. A client
 * that invents its own way to receive that secret would be a second credential authority, which
 * this lane is explicitly forbidden to create.
 */
class ConnectorEnrollmentClient(
    private val client: JsonClient,
    private val deviceId: String,
) {

    sealed interface Outcome {
        data class Redeemed(val receipt: EnrollmentReceipt) : Outcome
        data class Refused(val status: Int, val code: String) : Outcome

        /** Transport failure: the challenge stays unconsumed, so a retry is safe. */
        data class Offline(val reason: String) : Outcome
    }

    fun redeem(challengeId: String, proofRef: String): Outcome {
        val body = linkedMapOf<String, Any?>(
            "challenge_id" to challengeId,
            "device_id" to deviceId,
            "proof_ref" to proofRef,
        )
        val response = try {
            client.post(REDEEM_PATH, Json.encode(body))
        } catch (error: DeviceOfflineException) {
            return Outcome.Offline("enrollment endpoint unreachable")
        }
        val payload = Json.parseObject(response.body) ?: return Outcome.Refused(response.status, "invalid_json")
        if (response.status != 200 || payload["ok"] != true) {
            val error = payload["error"] as? Map<*, *>
            return Outcome.Refused(response.status, error?.get("code") as? String ?: "enrollment_refused")
        }
        val enrollment = payload["enrollment"] as? Map<*, *>
            ?: return Outcome.Refused(response.status, "enrollment_receipt_missing")
        return when (val receipt = EnrollmentReceipt.parse(enrollment, expectedDeviceId = deviceId)) {
            null -> Outcome.Refused(response.status, "enrollment_receipt_refused")
            else -> Outcome.Redeemed(receipt)
        }
    }

    companion object {
        const val REDEEM_PATH = "/api/claw/connector/enrollments/redeem"
    }
}

/** The public, secret-free enrollment receipt, verified field by field. */
data class EnrollmentReceipt(
    val bindingRef: String,
    val deviceId: String,
    val accountRef: String,
    val workspaceRef: String,
    val consentId: String,
    val credentialGeneration: Long,
    val credentialExpiresAt: String,
) {
    companion object {
        private val PUBLIC_FIELDS = setOf(
            "binding_ref", "device_id", "account_ref", "workspace_ref", "consent_id",
            "credential_generation", "credential_expires_at",
            "credential_installed_by_canonical_handoff", "raw_device_credential",
            "lifecycle", "dispatch_authorized", "grants_read", "grants_write",
        )

        @Suppress("UNCHECKED_CAST")
        fun parse(value: Map<*, *>, expectedDeviceId: String): EnrollmentReceipt? {
            if (value.keys != PUBLIC_FIELDS) return null
            if (value["credential_installed_by_canonical_handoff"] != true) return null
            if (value["raw_device_credential"] != false) return null
            if (value["lifecycle"] != "paired_offline") return null
            if (value["dispatch_authorized"] != false) return null
            if (value["grants_read"] != false) return null
            if (value["grants_write"] != false) return null
            val generation = value["credential_generation"] as? Long ?: return null
            if (generation < 1) return null
            val binding = value["binding_ref"] as? String ?: return null
            val device = value["device_id"] as? String ?: return null
            val account = value["account_ref"] as? String ?: return null
            val workspace = value["workspace_ref"] as? String ?: return null
            val consent = value["consent_id"] as? String ?: return null
            val expires = value["credential_expires_at"] as? String ?: return null
            if (!AndroidConnectorContract.isOpaqueRef(binding) || !AndroidConnectorContract.isOpaqueRef(account) ||
                !AndroidConnectorContract.isOpaqueRef(workspace) || !AndroidConnectorContract.isOpaqueRef(consent)
            ) {
                return null
            }
            // The device correlates its own request; a receipt naming another device is refused
            // rather than adopted.
            if (device != expectedDeviceId) return null
            val expiry = try {
                Instant.parse(expires)
            } catch (error: DateTimeParseException) {
                return null
            }
            if (expiry.isBefore(Instant.now())) return null
            return EnrollmentReceipt(binding, device, account, workspace, consent, generation, expires)
        }
    }
}

object PairingProof {

    /** HMAC over the canonical pairing transcript, keyed by the one-time pairing code. */
    fun proofRef(pairingCode: String, challengeId: String, deviceId: String): String {
        val transcript = AndroidConnectorContract.PAIRING_PROOF_TRANSCRIPT + "\n" + challengeId + "\n" + deviceId
        return AndroidConnectorContract.PAIRING_PROOF_REF_PREFIX +
            SafReadFingerprint.hmacSha256Hex(
                pairingCode.toByteArray(Charsets.UTF_8),
                transcript.toByteArray(Charsets.UTF_8),
            )
    }

    fun installAckProof(
        credential: ByteArray,
        challengeId: String,
        deviceId: String,
        bindingRef: String,
        credentialGeneration: Long,
    ): String {
        val transcript = listOf(
            AndroidConnectorContract.INSTALL_ACK_TRANSCRIPT_VERSION,
            challengeId, deviceId, bindingRef, credentialGeneration.toString(),
        ).joinToString("\n")
        return SafReadFingerprint.hmacSha256Hex(
            credential,
            transcript.toByteArray(Charsets.UTF_8),
        )
    }
}

/** The trusted delivery of the raw credential. Only the canonical handoff may provide it. */
interface CanonicalCredentialHandoff {
    fun ready(challengeId: String, deviceId: String): Boolean
    fun deliverOnce(challengeId: String, deviceId: String): ByteArray?
}

/**
 * The production state today: no reviewed authenticated transport is wired for this install
 * path, so the phone cannot obtain the raw credential and must say so. `ready` is false and
 * `deliverOnce` returns null — never a synthetic credential, never a locally generated
 * substitute, because possession of the canonical credential is exactly what the receipt proves.
 */
class UnconfiguredCanonicalCredentialHandoff : CanonicalCredentialHandoff {
    override fun ready(challengeId: String, deviceId: String): Boolean = false

    override fun deliverOnce(challengeId: String, deviceId: String): ByteArray? = null
}

/**
 * Builds the installation ack the gateway verifies: only after the platform secure store
 * confirms a save/readback, and only over the canonical handoff's credential.
 */
class DeviceCredentialInstaller(
    private val vault: DeviceCredentialVault,
    private val handoff: CanonicalCredentialHandoff,
) {

    sealed interface Outcome {
        /** Not installed, with the exact reason a reviewer can act on. */
        data class Blocked(val code: String) : Outcome
        data class Installed(val ack: Map<String, Any?>, val credentialGeneration: Long) : Outcome
    }

    fun install(
        receipt: EnrollmentReceipt,
        challengeId: String,
    ): Outcome {
        if (!handoff.ready(challengeId, receipt.deviceId)) return Outcome.Blocked("credential_handoff_unavailable")
        val credential = handoff.deliverOnce(challengeId, receipt.deviceId)
            ?: return Outcome.Blocked("credential_handoff_unavailable")
        if (credential.size < 16) return Outcome.Blocked("credential_too_short")
        if (!vault.saveAndConfirm(credential)) return Outcome.Blocked("protected_store_readback_failed")
        val readback = vault.read() ?: return Outcome.Blocked("protected_store_readback_failed")
        if (!readback.contentEquals(credential)) return Outcome.Blocked("protected_store_readback_failed")
        val ack = linkedMapOf<String, Any?>(
            "challenge_id" to challengeId,
            "device_id" to receipt.deviceId,
            "binding_ref" to receipt.bindingRef,
            "credential_generation" to receipt.credentialGeneration,
            "proof_kind" to AndroidConnectorContract.INSTALL_PROOF_KIND,
            "transcript_version" to AndroidConnectorContract.INSTALL_ACK_TRANSCRIPT_VERSION,
            "local_store_confirmed" to true,
            "proof_hex" to PairingProof.installAckProof(
                credential = credential,
                challengeId = challengeId,
                deviceId = receipt.deviceId,
                bindingRef = receipt.bindingRef,
                credentialGeneration = receipt.credentialGeneration,
            ),
        )
        return Outcome.Installed(ack, receipt.credentialGeneration)
    }
}
