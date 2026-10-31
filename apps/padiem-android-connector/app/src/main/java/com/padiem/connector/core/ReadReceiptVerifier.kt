package com.padiem.connector.core

import com.padiem.connector.contract.AndroidConnectorContract
import java.time.Instant
import java.time.format.DateTimeParseException

/** Why a dispatch material was refused. Never a partial execution: the phone reads nothing. */
class ReceiptRefusal(val code: String, message: String) : Exception(message)

/**
 * The verified intent of one approved Android TXT read.
 *
 * Everything here came from the server receipt; the phone recomputed the fingerprint and
 * compared it. It is the only value set the read step is allowed to use.
 */
data class ApprovedRead(
    val commandId: String,
    val requestId: String,
    val runId: String,
    val deviceId: String,
    val rootRef: String,
    val pathRelative: String,
    val requestedAt: String,
    val expiresAt: String,
    val evidenceRef: String,
    val fingerprint: String,
)

object ReadReceiptVerifier {

    private const val FORMAT = AndroidConnectorContract.RECEIPT_FORMAT

    /**
     * Verifies the closed receipt constants, the correlation, the expiry window and the SAF
     * read fingerprint, then returns the exact read to perform. `argv` is checked empty
     * because this lane sends no executable to the phone.
     */
    fun verify(
        material: Map<String, Any?>,
        receipt: Map<String, Any?>,
        declaredRootRefs: Set<String>,
        expectedCommandId: String,
        expectedRevisionRef: String,
        wireFingerprint: String,
        nowEpochSeconds: Long,
    ): ApprovedRead {
        if (receipt["format"] != FORMAT) throw ReceiptRefusal("receipt_format_unsupported", "unknown receipt format")
        if (receipt["local_policy_ref"] != AndroidConnectorContract.LOCAL_POLICY_REF) {
            throw ReceiptRefusal("receipt_policy_mismatch", "receipt is not under the Android SAF read policy")
        }
        if (receipt["command_id"] != expectedCommandId) {
            throw ReceiptRefusal("receipt_command_mismatch", "receipt does not name this command")
        }
        val requestId = receipt["request_id"] as? String
        if (!AndroidConnectorContract.isOpaqueRef(requestId)) throw ReceiptRefusal("receipt_request_missing", "receipt has no request ref")

        val pause = receipt["approval_pause"] as? Map<*, *>
        val decision = receipt["approval_decision"] as? Map<*, *>
        val intent = receipt["exact_tool_arguments"] as? Map<*, *>
        if (pause == null || decision == null || intent == null) {
            throw ReceiptRefusal("receipt_incomplete", "receipt is missing its pause, decision or intent")
        }
        if (pause["agent_runtime_id"] != AndroidConnectorContract.AGENT_RUNTIME_ID ||
            pause["tool_id"] != AndroidConnectorContract.TOOL_ID ||
            pause["requirement"] != AndroidConnectorContract.REQUIREMENT_USER_CONFIRMATION
        ) {
            throw ReceiptRefusal("receipt_runtime_mismatch", "receipt is not an Android SAF text read")
        }
        if (decision["outcome"] != "approved" ||
            decision["authority_ref"] != AndroidConnectorContract.APPROVAL_AUTHORITY_REF
        ) {
            throw ReceiptRefusal("receipt_not_approved", "receipt decision is not an approved owner confirmation")
        }
        val evidenceRef = receipt["evidence_ref"] as? String
        if (evidenceRef != decision["evidence_ref"] || !AndroidConnectorContract.isOpaqueRef(evidenceRef)) {
            throw ReceiptRefusal("receipt_evidence_mismatch", "receipt evidence correlation is not exact")
        }
        if (intent["operation"] != AndroidConnectorContract.READ_OPERATION ||
            intent["directory_enumeration"] != false ||
            intent["recursive_delete"] != false ||
            intent["admin_elevation"] != false
        ) {
            throw ReceiptRefusal("receipt_operation_unsupported", "receipt does not name a single TXT read")
        }
        if (material["argv"] != emptyList<Any?>()) {
            throw ReceiptRefusal("receipt_argv_not_empty", "this lane never carries an executable")
        }
        if (material["shell_authority"] != false || material["admin_elevation"] != false ||
            material["environment_payload"] != null || material["provider_authority"] != null
        ) {
            throw ReceiptRefusal("receipt_authority_present", "receipt carries execution authority")
        }

        val runId = intent["run_id"] as? String ?: throw ReceiptRefusal("receipt_run_missing", "receipt has no run")
        val deviceId = intent["device_id"] as? String ?: throw ReceiptRefusal("receipt_device_missing", "receipt has no device")
        val rootRef = intent["root_ref"] as? String ?: throw ReceiptRefusal("receipt_root_missing", "receipt has no SAF root")
        val pathRelative = intent["path_relative"] as? String
        if (pathRelative == null || !AndroidConnectorContract.isRelativeReadPath(pathRelative)) {
            throw ReceiptRefusal("receipt_path_invalid", "receipt path is not a relative TXT path")
        }
        if (!declaredRootRefs.contains(rootRef)) {
            throw ReceiptRefusal("receipt_root_not_declared", "receipt root was never declared by this phone")
        }
        if (material["root_ref"] != rootRef || material["run_id"] != runId ||
            material["device_id"] != deviceId || material["request_id"] != requestId
        ) {
            throw ReceiptRefusal("receipt_material_mismatch", "material does not match the receipt intent")
        }

        val fingerprint = intent["request_fingerprint"] as? String
        val invocationSha = pause["invocation_sha256"] as? String
        if (!AndroidConnectorContract.isDigest(fingerprint) || invocationSha != fingerprint ||
            wireFingerprint != fingerprint
        ) {
            throw ReceiptRefusal("receipt_fingerprint_mismatch", "receipt fingerprint is not self-consistent")
        }
        if (!AndroidConnectorContract.isOpaqueRef(pause["pause_id"]) ||
            !AndroidConnectorContract.isOpaqueRef(decision["decision_id"]) ||
            pause["run_id"] != runId || decision["pause_id"] != pause["pause_id"]
        ) {
            throw ReceiptRefusal("receipt_correlation_invalid", "receipt pause/decision correlation is not exact")
        }
        if (expectedRevisionRef.isEmpty()) {
            throw ReceiptRefusal("receipt_revision_missing", "queued command carries no server revision")
        }

        val requestedAt = intent["requested_at"] as? String ?: material["requested_at"] as? String
        val expiresAt = receipt["expires_at"] as? String ?: pause["expires_at"] as? String
        if (requestedAt == null || expiresAt == null) {
            throw ReceiptRefusal("receipt_window_missing", "receipt carries no approval window")
        }
        if (!withinWindow(requestedAt, expiresAt, nowEpochSeconds)) {
            throw ReceiptRefusal("receipt_expired", "the approval window closed before execution")
        }
        val recomputed = SafReadFingerprint.compute(
            actionId = intent["action_id"] as? String ?: throw ReceiptRefusal("receipt_action_missing", "no action id"),
            runId = runId,
            deviceId = deviceId,
            rootRef = rootRef,
            pathRelative = pathRelative,
            requestedAt = requestedAt,
        )
        if (recomputed != fingerprint) {
            throw ReceiptRefusal("receipt_fingerprint_recompute", "recomputed SAF fingerprint does not match")
        }
        return ApprovedRead(
            commandId = expectedCommandId,
            requestId = requestId!!,
            runId = runId,
            deviceId = deviceId,
            rootRef = rootRef,
            pathRelative = pathRelative!!,
            requestedAt = requestedAt,
            expiresAt = expiresAt,
            evidenceRef = evidenceRef!!,
            fingerprint = fingerprint!!,
        )
    }

    private fun withinWindow(requestedAt: String, expiresAt: String, nowEpochSeconds: Long): Boolean {
        val expires = parse(expiresAt) ?: return false
        val requested = parse(requestedAt) ?: return false
        if (expires.epochSecond < requested.epochSecond) return false
        val window = expires.epochSecond - requested.epochSecond
        if (window > AndroidConnectorContract.APPROVAL_WINDOW_SECONDS + 1) return false
        return nowEpochSeconds < expires.epochSecond
    }

    private fun parse(value: String): Instant? = try {
        Instant.parse(value)
    } catch (error: DateTimeParseException) {
        null
    }
}
