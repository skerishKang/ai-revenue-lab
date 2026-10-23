package com.padiem.connector.support

import com.padiem.connector.contract.Json
import com.padiem.connector.net.DeviceHttpResponse
import com.padiem.connector.net.DeviceTransport
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.util.Base64

/**
 * A JVM stand-in for the private broker device surface and the connector enrollment endpoint.
 *
 * It re-implements the SERVER-SIDE rules the #5163 contract states, so a client that guesses a
 * shape is refused rather than tolerated: route set, POST-only, `application/json`, size bounds,
 * closed request key sets, `binding_ref`/`credential_b64` authentication, session currency,
 * pending-before-content ordering, the 768-byte text bound, the SHA-256 match, idempotent
 * acknowledgement, and the secret-free enrollment receipt.
 *
 * It is driven through the real `DeviceTransport` seam: the client serializes actual JSON bytes
 * and interprets the actual status and body back. What it does not exercise is the TLS and HTTP
 * framing of a deployed endpoint — that stays a live-verification item, not a claim made here.
 *
 * The SAF read fingerprint it publishes is the pinned vector from the contract document
 * (`fb438c4d...`, reproduced by the server's own `saf_read_fingerprint`), never a value computed
 * by the client under test — otherwise a canonical-JSON bug would agree with itself.
 */
class MockBrokerSurface(
    private val credential: ByteArray = "device-credential-for-mock-tests".toByteArray(StandardCharsets.UTF_8),
) {

    val calls = mutableListOf<String>()
    val requestBodies = mutableListOf<Map<String, Any?>>()
    var bindingRef = "binding.android.1"
    var deviceId = "device.android.vector.1"
    var accountRef = "account.android.1"
    var workspaceRef = "workspace.android.1"
    var sessionId = "session.android.1"
    var enrollmentGatewayTrusts = true
    var lastAndroidProfile: Map<String, Any?>? = null
    var lastTextResult: Map<String, Any?>? = null
    var acknowledgeFailuresLeft = 0
    var contentFailuresLeft = 0

    val pinnedFingerprint = "fb438c4de05d28b5c840a7af23b3eab9dbd223139ba92f2c88cfdf050a994e79"
    val pinnedRequestedAt = "2026-10-19T06:00:00Z"
    val pinnedExpiresAt = "2026-10-19T06:05:00Z"

    private val commands = LinkedHashMap<String, CommandState>()
    private var sessionOpen = false
    private var declaredFolders: List<Map<String, Any?>> = emptyList()

    val folderCount: Int get() = declaredFolders.size
    val deliveredCommands: List<CommandState> get() = commands.values.toList()

    /** The device-side seam: a real request in, a real status and JSON body out. */
    fun enrollmentClient(): com.padiem.connector.net.JsonClient =
        com.padiem.connector.net.JsonClient { path, body -> handle(path, "POST", "application/json", body) }

    class CommandState(
        val commandId: String,
        val runId: String,
        val rootRef: String,
        val pathRelative: String,
        val material: Map<String, Any?>,
        var sequence: Long,
        var state: String = STATE_QUEUED,
        var admissionRef: String? = null,
        var evidenceRef: String? = null,
        var revisionRef: String = "revision.android.1",
        var requestId: String = "andreq-mock-1",
        var acknowledgeCount: Int = 0,
        var pendingStaged: Boolean = false,
        var contentStaged: Boolean = false,
    )

    fun enqueue(
        commandId: String = "andcmd-mock-1",
        runId: String = "run.android.vector.1",
        rootRef: String = declaredFolders.firstOrNull()?.get("root_ref") as? String ?: "safroot-documents",
        pathRelative: String = "notes/report.txt",
        actionId: String = "andact-vector-1",
        receiptOverride: Map<String, Any?>? = null,
    ): CommandState {
        val material = linkedMapOf<String, Any?>(
            "request_id" to "andreq-mock-1",
            "run_id" to runId,
            "device_id" to deviceId,
            "root_ref" to rootRef,
            "argv" to emptyList<Any?>(),
            "cwd_relative" to ".",
            "requested_at" to pinnedRequestedAt,
            "timeout_seconds" to 30L,
            "shell_authority" to false,
            "admin_elevation" to false,
            "environment_payload" to null,
            "provider_authority" to null,
            "p01_approval_payload" to (receiptOverride ?: receipt(commandId, runId, rootRef, pathRelative, actionId)),
        )
        val state = CommandState(
            commandId = commandId,
            runId = runId,
            rootRef = rootRef,
            pathRelative = pathRelative,
            material = material,
            sequence = (commands.values.maxOfOrNull { it.sequence } ?: 0L) + 1L,
        )
        commands[commandId] = state
        return state
    }

    fun credentialB64(): String = Base64.getEncoder().encodeToString(credential)

    /**
     * A receipt with one reviewed field changed, so a refusal test proves the phone checks that
     * field rather than trusting the whole object.
     */
    @Suppress("UNCHECKED_CAST")
    fun receiptVariant(
        commandId: String = "andcmd-mock-1",
        runId: String = "run.android.vector.1",
        rootRef: String = "safroot-documents",
        pathRelative: String = "notes/report.txt",
        actionId: String = "andact-vector-1",
        format: String? = null,
        pauseHash: String? = null,
        expiresAt: String? = null,
        policyRef: String? = null,
    ): Map<String, Any?> {
        val base = LinkedHashMap(receipt(commandId, runId, rootRef, pathRelative, actionId))
        val pause = LinkedHashMap(base["approval_pause"] as Map<String, Any?>)
        if (pauseHash != null) pause["invocation_sha256"] = pauseHash
        if (expiresAt != null) pause["expires_at"] = expiresAt
        base["approval_pause"] = pause
        if (format != null) base["format"] = format
        if (expiresAt != null) base["expires_at"] = expiresAt
        if (policyRef != null) base["local_policy_ref"] = policyRef
        return base
    }

    fun handle(
        path: String,
        method: String,
        contentType: String,
        body: String,
    ): DeviceHttpResponse {
        val (status, payload) = when {
            path == ENROLL_REDEEM -> enrollmentRedeem(body)
            ROUTES.contains(path) -> deviceRoute(path, method, contentType, body)
            else -> 404 to errorBody("local_agent_http_route_not_found")
        }
        return DeviceHttpResponse(status, Json.encode(payload))
    }

    // ---- enrollment -------------------------------------------------------

    private fun enrollmentRedeem(body: String): Pair<Int, Map<String, Any?>> {
        calls.add(ENROLL_REDEEM)
        val payload = Json.parseObject(body) ?: return 400 to errorBody("invalid_json")
        requestBodies.add(payload)
        if (payload.keys != setOf("challenge_id", "device_id", "proof_ref")) {
            return 400 to errorBody("connector_enrollment_invalid_request")
        }
        if (!enrollmentGatewayTrusts) return 403 to errorBody("connector_enrollment_device_gateway_denied")
        val proof = payload["proof_ref"] as? String
        if (proof == null || !PROOF_REF.matches(proof)) return 400 to errorBody("invalid_pairing_proof")
        if (payload["device_id"] != deviceId) return 403 to errorBody("enrollment_device_swap_denied")
        // The public receipt is secret-free by construction: no raw credential is ever returned.
        return 200 to linkedMapOf(
            "ok" to true,
            "enrollment" to linkedMapOf<String, Any?>(
                "binding_ref" to bindingRef,
                "device_id" to deviceId,
                "account_ref" to accountRef,
                "workspace_ref" to workspaceRef,
                "consent_id" to "consent.android.1",
                "credential_generation" to 1L,
                "credential_expires_at" to FAR_FUTURE,
                "credential_installed_by_canonical_handoff" to true,
                "raw_device_credential" to false,
                "lifecycle" to "paired_offline",
                "dispatch_authorized" to false,
                "grants_read" to false,
                "grants_write" to false,
            ),
        )
    }

    // ---- device routes ----------------------------------------------------

    private fun deviceRoute(
        route: String,
        method: String,
        contentType: String,
        body: String,
    ): Pair<Int, Map<String, Any?>> {
        calls.add(route)
        if (method != "POST") return 405 to errorBody("local_agent_http_post_required")
        if (!contentType.startsWith("application/json")) return 415 to errorBody("local_agent_http_json_required")
        if (body.toByteArray(StandardCharsets.UTF_8).size > MAX_BODY) return 413 to errorBody("local_agent_http_body_too_large")
        val payload = Json.parseObject(body) ?: return 400 to errorBody("local_agent_http_invalid_json")
        requestBodies.add(payload)
        if (payload["binding_ref"] != bindingRef || !credentialMatches(payload)) {
            return 401 to errorBody("local_agent_http_auth_required")
        }
        return when (route) {
            "/session" -> session(payload)
            "/android-profile" -> androidProfile(payload)
            "/poll" -> poll(payload)
            "/material" -> material(payload)
            "/acknowledge" -> acknowledge(payload)
            "/text-result" -> textResult(payload)
            else -> 404 to errorBody("local_agent_http_route_not_found")
        }
    }

    private fun session(payload: Map<String, Any?>): Pair<Int, Map<String, Any?>> {
        if (!exact(payload, SESSION_KEYS)) return 400 to errorBody("local_agent_http_invalid_request")
        if (payload["session_id"] != sessionId) return 403 to errorBody("local_agent_http_scope_mismatch")
        if (payload["account_ref"] != accountRef || payload["workspace_ref"] != workspaceRef) {
            return 403 to errorBody("local_agent_http_scope_mismatch")
        }
        val ttl = payload["ttl_seconds"] as? Long
        if (ttl == null || ttl < 60 || ttl > 3600) return 400 to errorBody("local_agent_http_invalid_request")
        sessionOpen = true
        return 200 to linkedMapOf(
            "ok" to true,
            "session" to linkedMapOf<String, Any?>(
                "session_id" to sessionId,
                "binding_ref" to bindingRef,
                "device_id" to deviceId,
                "account_ref" to accountRef,
                "workspace_ref" to workspaceRef,
                "credential_generation" to 1L,
                "issued_at" to pinnedRequestedAt,
                "expires_at" to pinnedExpiresAt,
                "raw_session_secret" to false,
            ),
        )
    }

    private fun androidProfile(payload: Map<String, Any?>): Pair<Int, Map<String, Any?>> {
        if (!exact(payload, ANDROID_PROFILE_KEYS)) return 400 to errorBody("local_agent_http_invalid_request")
        if (!sessionOpen ||
            payload["contract_version"] != "claw-local-android-saf-profile.v1" ||
            payload["profile_ref"] != "profile.android.saf-txt.v1" ||
            payload["session_id"] != sessionId
        ) {
            return 409 to errorBody("android_profile_refused")
        }
        val folders = payload["folders"] as? List<*> ?: return 409 to errorBody("android_profile_refused")
        if (folders.size > 8) return 409 to errorBody("android_profile_refused")
        for (row in folders) {
            val folder = row as? Map<*, *> ?: return 409 to errorBody("android_profile_refused")
            if (folder.keys != setOf("root_ref", "display_name")) return 409 to errorBody("android_profile_refused")
            val ref = folder["root_ref"] as? String ?: return 409 to errorBody("android_profile_refused")
            val name = folder["display_name"] as? String ?: return 409 to errorBody("android_profile_refused")
            if (!ROOT_REF.matches(ref)) return 409 to errorBody("android_profile_refused")
            if (name.isEmpty() || name.length > 80 || name != name.trim() ||
                name.contains('/') || name.contains('\\') || name.any { it.code < 32 || it.code == 127 }
            ) {
                return 409 to errorBody("android_profile_refused")
            }
        }
        @Suppress("UNCHECKED_CAST")
        declaredFolders = folders.map { it as Map<String, Any?> }
        lastAndroidProfile = payload
        return 200 to linkedMapOf(
            "ok" to true,
            "android_profile" to linkedMapOf<String, Any?>(
                "accepted" to true,
                "profile_ref" to "profile.android.saf-txt.v1",
                "platform" to "android",
                "folder_count" to declaredFolders.size.toLong(),
                "credential_generation" to 1L,
                "raw_device_credential" to false,
                "saf_uri_exposed" to false,
            ),
        )
    }

    private fun poll(payload: Map<String, Any?>): Pair<Int, Map<String, Any?>> {
        if (!exact(payload, POLL_KEYS)) return 400 to errorBody("local_agent_http_invalid_request")
        if (!sessionOpen) return 401 to errorBody("local_agent_http_session_required")
        val after = payload["after_sequence"] as? Long ?: return 400 to errorBody("local_agent_http_invalid_request")
        val limit = ((payload["limit"] as? Long) ?: 0L).toInt()
        if (limit < 1) return 400 to errorBody("local_agent_http_invalid_request")
        val visible = commands.values.filter { it.sequence > after }.sortedBy { it.sequence }.take(limit)
        return 200 to linkedMapOf("ok" to true, "commands" to visible.map { projection(it) })
    }

    private fun material(payload: Map<String, Any?>): Pair<Int, Map<String, Any?>> {
        if (!exact(payload, MATERIAL_KEYS)) return 400 to errorBody("local_agent_http_invalid_request")
        if (!OPAQUE_REF.matches((payload["request_ref"] as? String).orEmpty())) {
            return 400 to errorBody("local_agent_http_invalid_request")
        }
        val command = commands[payload["command_id"]]
            ?: return 409 to errorBody("local_agent_material_command_not_current")
        if (payload["request_fingerprint"] != pinnedFingerprint || command.state == STATE_DONE) {
            return 409 to errorBody("local_agent_material_command_mismatch")
        }
        // The owner already confirmed this read, so the broker admits it when the phone pulls the
        // material. The device never mints an admission or evidence reference of its own.
        command.admissionRef = "admission.android.1"
        command.evidenceRef = "evidence.android.1"
        if (command.state == STATE_QUEUED) command.state = STATE_ADMITTED
        return 200 to linkedMapOf(
            "ok" to true,
            "material" to linkedMapOf<String, Any?>(
                "contract_version" to "claw-local-command-material.v2",
                "command_id" to command.commandId,
                "binding_ref" to bindingRef,
                "sequence" to command.sequence,
                "request_fingerprint" to pinnedFingerprint,
                "revision_ref" to command.revisionRef,
                "material" to command.material,
            ),
        )
    }

    private fun acknowledge(payload: Map<String, Any?>): Pair<Int, Map<String, Any?>> {
        if (!exact(payload, ACK_KEYS)) return 400 to errorBody("local_agent_http_invalid_request")
        val command = commands[payload["command_id"]]
            ?: return 409 to errorBody("local_agent_http_command_unavailable")
        if (payload["termination"] != "exited" || payload["exit_code"] != 0L) {
            return 400 to errorBody("local_agent_http_invalid_request")
        }
        if (command.admissionRef != payload["admission_ref"] ||
            command.evidenceRef != payload["evidence_ref"] ||
            command.revisionRef != payload["revision_ref"] ||
            command.requestId != payload["request_id"]
        ) {
            return 409 to errorBody("local_agent_http_correlation_mismatch")
        }
        if (command.state != STATE_ADMITTED && command.state != STATE_ACKNOWLEDGED) {
            return 409 to errorBody("local_agent_http_not_admitted")
        }
        if (acknowledgeFailuresLeft > 0) {
            acknowledgeFailuresLeft -= 1
            return 503 to errorBody("local_agent_http_dependency_unavailable")
        }
        // A resent acknowledgement is the same terminal fact, never a second execution.
        command.acknowledgeCount += 1
        command.state = STATE_ACKNOWLEDGED
        return 200 to linkedMapOf("ok" to true, "command" to projection(command))
    }

    private fun textResult(payload: Map<String, Any?>): Pair<Int, Map<String, Any?>> {
        if (!exactEither(payload, TEXT_PENDING_KEYS, TEXT_CONTENT_KEYS)) {
            return 400 to errorBody("local_agent_http_invalid_request")
        }
        if (payload["contract_version"] != "claw-local-agent-text-result.v1" ||
            payload["request_fingerprint"] != pinnedFingerprint
        ) {
            return 409 to errorBody("text_result_refused")
        }
        val command = commands[payload["command_id"]] ?: return 409 to errorBody("text_result_refused")
        lastTextResult = payload
        if (payload["state"] == "pending") {
            if (command.state != STATE_ADMITTED && command.state != STATE_ACKNOWLEDGED) {
                return 409 to errorBody("text_result_refused")
            }
            command.pendingStaged = true
            return 200 to resultBody("pending", command.commandId)
        }
        if (payload["state"] != "content") return 409 to errorBody("text_result_refused")
        if (command.state != STATE_ACKNOWLEDGED || !command.pendingStaged) {
            return 409 to errorBody("text_result_refused")
        }
        val text = payload["content_utf8"] as? String ?: return 409 to errorBody("text_result_refused")
        val bytes = text.toByteArray(StandardCharsets.UTF_8)
        if (bytes.size > 768 || payload["content_bytes"] != bytes.size.toLong()) {
            return 409 to errorBody("text_result_refused")
        }
        if (payload["content_sha256"] != sha256Hex(bytes)) return 409 to errorBody("text_result_refused")
        if (contentFailuresLeft > 0) {
            contentFailuresLeft -= 1
            return 503 to errorBody("local_agent_http_dependency_unavailable")
        }
        command.contentStaged = true
        command.state = STATE_DONE
        return 200 to resultBody("content", command.commandId)
    }

    private fun resultBody(state: String, commandId: String) = linkedMapOf(
        "ok" to true,
        "text_result" to linkedMapOf<String, Any?>(
            "state" to state,
            "command_id" to commandId,
            "raw_device_credential" to false,
        ),
    )

    private fun receipt(
        commandId: String,
        runId: String,
        rootRef: String,
        path: String,
        actionId: String,
    ): Map<String, Any?> = linkedMapOf(
        "format" to "claw-android-saf-txt-read-approval.v1",
        "evidence_ref" to "andevidence-mock-1",
        "command_id" to commandId,
        "request_id" to "andreq-mock-1",
        "approval_pause" to linkedMapOf<String, Any?>(
            "pause_id" to "andpause-mock-1",
            "run_id" to runId,
            "agent_runtime_id" to "claw_android_saf_txt_v1",
            "tool_id" to "local.filesystem.read",
            "invocation_sha256" to pinnedFingerprint,
            "requirement" to "user_confirmation",
            "step_index" to 1L,
            "created_at" to pinnedRequestedAt,
            "expires_at" to pinnedExpiresAt,
            "approval_scope" to listOf("filesystem.read"),
        ),
        "approval_decision" to linkedMapOf<String, Any?>(
            "decision_id" to "anddecision-mock-1",
            "pause_id" to "andpause-mock-1",
            "outcome" to "approved",
            "authority_ref" to "claw_connector_android_txt_request_v1",
            "evidence_ref" to "andevidence-mock-1",
            "decided_at" to pinnedRequestedAt,
        ),
        "exact_tool_arguments" to linkedMapOf<String, Any?>(
            "action_id" to actionId,
            "run_id" to runId,
            "device_id" to deviceId,
            "root_ref" to rootRef,
            "operation" to "read",
            "path_relative" to path,
            "requested_at" to pinnedRequestedAt,
            "request_fingerprint" to pinnedFingerprint,
            "content_bytes" to 0L,
            "content_sha256" to null,
            "directory_enumeration" to false,
            "recursive_delete" to false,
            "admin_elevation" to false,
        ),
        "local_policy_ref" to "padiem_android_saf_selected_root_read_policy_v1",
        "expires_at" to pinnedExpiresAt,
    )

    private fun projection(command: CommandState): Map<String, Any?> = linkedMapOf<String, Any?>(
        "command_id" to command.commandId,
        "run_id" to command.runId,
        "tool_request_ref" to "andtool-mock-1",
        "binding_ref" to bindingRef,
        "credential_generation" to 1L,
        "sequence" to command.sequence,
        "request_fingerprint" to pinnedFingerprint,
        "issued_at" to pinnedRequestedAt,
        "expires_at" to pinnedExpiresAt,
        "state" to command.state,
        "admission_ref" to command.admissionRef,
        "evidence_ref" to command.evidenceRef,
        "admitted_session_id" to if (command.admissionRef == null) null else sessionId,
        "admitted_at" to if (command.admissionRef == null) null else pinnedRequestedAt,
        "acknowledged_at" to if (command.state == STATE_ACKNOWLEDGED) pinnedExpiresAt else null,
        "revision_ref" to command.revisionRef,
        "termination" to if (command.state == STATE_ACKNOWLEDGED) "exited" else null,
        "request_id" to command.requestId,
        "exit_code" to if (command.state == STATE_ACKNOWLEDGED) 0L else null,
        "raw_argv" to false,
        "raw_file_content" to false,
        "raw_device_credential" to false,
        "p01_approval_payload" to false,
    )

    private fun credentialMatches(payload: Map<String, Any?>): Boolean {
        val encoded = payload["credential_b64"] as? String ?: return false
        val decoded = try {
            Base64.getDecoder().decode(encoded)
        } catch (error: IllegalArgumentException) {
            return false
        }
        return decoded.contentEquals(credential)
    }

    private fun exact(payload: Map<String, Any?>, required: Set<String>) = payload.keys == required

    private fun exactEither(payload: Map<String, Any?>, first: Set<String>, second: Set<String>) =
        payload.keys == first || payload.keys == second

    private fun errorBody(code: String) = linkedMapOf(
        "ok" to false,
        "error" to linkedMapOf<String, Any?>("code" to code, "message" to code),
    )

    private companion object {
        const val ENROLL_REDEEM = "/api/claw/connector/enrollments/redeem"
        const val MAX_BODY = 262_144
        const val FAR_FUTURE = "2099-01-01T00:00:00Z"
        const val STATE_QUEUED = "queued"
        const val STATE_ADMITTED = "admitted"
        const val STATE_ACKNOWLEDGED = "acknowledged"
        const val STATE_DONE = "delivered"
        val PROOF_REF = Regex("^pairing-proof:[0-9a-f]{64}$")
        val OPAQUE_REF = Regex("^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$")
        val ROOT_REF = Regex("^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$")
        val ROUTES = setOf(
            "/session", "/poll", "/material", "/heartbeat", "/acknowledge",
            "/text-result", "/android-profile",
        )
        val SESSION_KEYS = setOf(
            "session_id", "binding_ref", "credential_b64", "account_ref",
            "workspace_ref", "now", "ttl_seconds",
        )
        val POLL_KEYS = setOf(
            "session_id", "binding_ref", "credential_b64", "after_sequence", "now", "limit",
        )
        val MATERIAL_KEYS = setOf(
            "request_ref", "session_id", "binding_ref", "credential_b64",
            "command_id", "request_fingerprint", "now",
        )
        val ACK_KEYS = setOf(
            "session_id", "binding_ref", "credential_b64", "command_id", "admission_ref",
            "evidence_ref", "revision_ref", "termination", "request_id", "exit_code", "now",
        )
        val TEXT_PENDING_KEYS = setOf(
            "contract_version", "command_id", "run_id", "request_fingerprint", "state",
            "binding_ref", "credential_b64",
        )
        val TEXT_CONTENT_KEYS = TEXT_PENDING_KEYS + setOf("content_utf8", "content_sha256", "content_bytes")
        val ANDROID_PROFILE_KEYS = setOf(
            "contract_version", "session_id", "profile_ref", "folders",
            "binding_ref", "credential_b64",
        )

        fun sha256Hex(bytes: ByteArray): String =
            MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") {
                ((it.toInt() and 0xFF) + 256).toString(16).substring(1)
            }
    }
}
