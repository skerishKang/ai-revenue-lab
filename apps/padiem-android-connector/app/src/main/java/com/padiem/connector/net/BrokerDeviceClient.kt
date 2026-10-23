package com.padiem.connector.net

import com.padiem.connector.contract.AndroidConnectorContract
import com.padiem.connector.contract.Json

/** A broker reply, narrowed to the two states the phone can act on. */
sealed interface DeviceReply {
    data class Accepted(val body: Map<String, Any?>) : DeviceReply

    /** Refused with a bounded code. The phone never retries a refusal as a success path. */
    data class Refused(val status: Int, val code: String) : DeviceReply
}

/** One queued command, read back from the server. The phone mints none of these refs. */
data class QueuedCommand(
    val commandId: String,
    val runId: String,
    val toolRequestRef: String,
    val sequence: Long,
    val requestFingerprint: String,
    val revisionRef: String,
    val requestId: String,
    val state: String,
    val admissionRef: String? = null,
    val evidenceRef: String? = null,
) {
    /** A command the broker has not admitted yet cannot be acknowledged. */
    val admitted: Boolean
        get() = AndroidConnectorContract.isOpaqueRef(admissionRef) &&
            AndroidConnectorContract.isOpaqueRef(evidenceRef)
}

/** The `/material` projection: the canonical wire plus the exact read it authorizes. */
data class CommandMaterial(
    val wire: Map<String, Any?>,
    val material: Map<String, Any?>,
    val sequence: Long,
    val revisionRef: String,
    val requestFingerprint: String,
    val commandId: String,
)

/**
 * The device side of the #5163 closed request sets. Every body carries exactly the keys the
 * broker accepts, plus `binding_ref` and `credential_b64`, which the dispatcher strips before
 * the route sees them. `now` is sent because the closed set requires it, but the broker keeps
 * its own clock authority: the phone never asks the server to trust a client timestamp.
 */
class BrokerDeviceClient(
    private val transport: DeviceTransport,
    private val identity: DeviceIdentity,
    private val clock: () -> String = { java.time.Instant.now().toString() },
) {

    fun openSession(sessionId: String, ttlSeconds: Long): DeviceReply = post(
        AndroidConnectorContract.ROUTE_SESSION,
        linkedMapOf<String, Any?>(
            "session_id" to sessionId,
            "account_ref" to identity.accountRef,
            "workspace_ref" to identity.workspaceRef,
            "now" to clock(),
            "ttl_seconds" to ttlSeconds,
        ),
    )

    fun declareFolders(sessionId: String, folders: List<Map<String, Any?>>): DeviceReply {
        val capped = folders.take(AndroidConnectorContract.MAX_DECLARED_FOLDERS)
        return post(
            AndroidConnectorContract.ROUTE_ANDROID_PROFILE,
            linkedMapOf<String, Any?>(
                "contract_version" to AndroidConnectorContract.PROFILE_CONTRACT_VERSION,
                "session_id" to sessionId,
                "profile_ref" to AndroidConnectorContract.PROFILE_REF,
                "folders" to capped.map { folder ->
                    linkedMapOf<String, Any?>(
                        "root_ref" to folder["root_ref"],
                        "display_name" to folder["display_name"],
                    )
                },
            ),
        )
    }

    fun poll(sessionId: String, afterSequence: Long, limit: Int): Pair<DeviceReply, List<QueuedCommand>> {
        val reply = post(
            AndroidConnectorContract.ROUTE_POLL,
            linkedMapOf<String, Any?>(
                "session_id" to sessionId,
                "after_sequence" to afterSequence,
                "now" to clock(),
                "limit" to limit.toLong(),
            ),
        )
        if (reply !is DeviceReply.Accepted) return reply to emptyList()
        val commands = reply.body["commands"]
        if (commands !is List<*>) throw DeviceProtocolException("broker poll returned no command list")
        return reply to commands.mapNotNull { row -> parseCommand(row as? Map<String, Any?>) }
    }

    /**
     * Reads back the same command at its exact sequence so the phone can see the admission
     * correlation the broker attached when the material was pulled.
     *
     * #5163 §7 hands the phone only `{command_id, run_id, tool_request_ref, sequence,
     * request_fingerprint, revision_ref}` at first poll, while `/acknowledge` requires
     * `admission_ref` and `evidence_ref`. Re-reading `/poll` is the only documented surface that
     * can supply them, so the phone echoes what the server published and mints nothing.
     */
    fun admittedCorrelation(sessionId: String, command: QueuedCommand): QueuedCommand? {
        val before = if (command.sequence > 0) command.sequence - 1 else 0
        val (reply, commands) = poll(sessionId, before, 1)
        if (reply !is DeviceReply.Accepted) return null
        return commands.firstOrNull { it.commandId == command.commandId && it.admitted }
    }

    fun material(sessionId: String, requestRef: String, command: QueuedCommand): DeviceReply = post(
        AndroidConnectorContract.ROUTE_MATERIAL,
        linkedMapOf<String, Any?>(
            "request_ref" to requestRef,
            "session_id" to sessionId,
            "command_id" to command.commandId,
            "request_fingerprint" to command.requestFingerprint,
            "now" to clock(),
        ),
    )

    fun acknowledge(sessionId: String, command: QueuedCommand): DeviceReply {
        if (!command.admitted) {
            throw DeviceProtocolException("an un-admitted command cannot be acknowledged")
        }
        return post(
            AndroidConnectorContract.ROUTE_ACKNOWLEDGE,
            linkedMapOf<String, Any?>(
                "session_id" to sessionId,
                "command_id" to command.commandId,
                "admission_ref" to command.admissionRef,
                "evidence_ref" to command.evidenceRef,
                "revision_ref" to command.revisionRef,
                "termination" to AndroidConnectorContract.TERMINATION_EXITED,
                "request_id" to command.requestId,
                "exit_code" to 0L,
                "now" to clock(),
            ),
        )
    }

    fun pendingIntent(command: QueuedCommand): DeviceReply = post(
        AndroidConnectorContract.ROUTE_TEXT_RESULT,
        textResultBase(command) + linkOf("state" to AndroidConnectorContract.STATE_PENDING),
    )

    fun contentResult(command: QueuedCommand, contentUtf8: String, contentBytes: ByteArray): DeviceReply {
        if (contentBytes.size > AndroidConnectorContract.MAX_TEXT_RESULT_BYTES) {
            throw DeviceProtocolException("verified text exceeds the 768-byte bound")
        }
        return post(
            AndroidConnectorContract.ROUTE_TEXT_RESULT,
            textResultBase(command) + linkOf(
                "state" to AndroidConnectorContract.STATE_CONTENT,
                "content_utf8" to contentUtf8,
                "content_sha256" to com.padiem.connector.core.SafReadFingerprint.sha256Hex(contentBytes),
                "content_bytes" to contentBytes.size.toLong(),
            ),
        )
    }

    private fun textResultBase(command: QueuedCommand): Map<String, Any?> = linkOf(
        "contract_version" to AndroidConnectorContract.TEXT_RESULT_CONTRACT_VERSION,
        "command_id" to command.commandId,
        "run_id" to command.runId,
        "request_fingerprint" to command.requestFingerprint,
    )

    private fun post(route: String, body: Map<String, Any?>): DeviceReply {
        // Every device route authenticates with the same two fields, and the dispatcher strips
        // them before the route sees the payload. Adding them here rather than in each builder
        // means no route can be called without them.
        val envelope = LinkedHashMap<String, Any?>(body.size + 2)
        envelope.putAll(body)
        envelope["binding_ref"] = identity.bindingRef
        envelope["credential_b64"] = identity.credentialB64
        val response = transport.post(route, Json.encode(envelope))
        val parsed = Json.parseObject(response.body)
            ?: throw DeviceProtocolException("device route $route returned no JSON object")
        if (response.status != 200 || parsed["ok"] !== true) {
            val error = parsed["error"] as? Map<*, *>
            val code = error?.get("code") as? String
            if (code == null || !AndroidConnectorContract.isOpaqueRef(code)) {
                throw DeviceProtocolException("device route $route refused without a bounded code")
            }
            return DeviceReply.Refused(response.status, code)
        }
        return DeviceReply.Accepted(parsed)
    }

    private fun parseCommand(row: Map<String, Any?>?): QueuedCommand? {
        if (row == null) return null
        val commandId = row["command_id"] as? String ?: return null
        val fingerprint = row["request_fingerprint"] as? String ?: return null
        val sequence = row["sequence"] as? Long ?: return null
        val state = row["state"] as? String ?: return null
        val revisionRef = row["revision_ref"] as? String ?: return null
        val requestId = row["request_id"] as? String ?: return null
        val admissionRef = row["admission_ref"]
        val evidenceRef = row["evidence_ref"]
        return QueuedCommand(
            commandId = commandId,
            runId = row["run_id"] as? String ?: return null,
            toolRequestRef = row["tool_request_ref"] as? String ?: return null,
            sequence = sequence,
            requestFingerprint = fingerprint,
            revisionRef = revisionRef,
            requestId = requestId,
            state = state,
            admissionRef = admissionRef as? String,
            evidenceRef = evidenceRef as? String,
        )
    }

    private fun linkOf(vararg pairs: Pair<String, Any?>): LinkedHashMap<String, Any?> =
        LinkedHashMap<String, Any?>(pairs.size).apply { pairs.forEach { put(it.first, it.second) } }
}

/** The authenticated device scope. Ownership never comes from a browser-supplied string. */
data class DeviceIdentity(
    val bindingRef: String,
    val deviceId: String,
    val accountRef: String,
    val workspaceRef: String,
    val credentialB64: String,
    val credentialGeneration: Long,
) {
    init {
        require(AndroidConnectorContract.isOpaqueRef(bindingRef)) { "binding_ref must be an opaque ref" }
        require(AndroidConnectorContract.isOpaqueRef(deviceId)) { "device_id must be an opaque ref" }
        require(credentialB64.isNotEmpty()) { "device credential is required" }
    }
}
