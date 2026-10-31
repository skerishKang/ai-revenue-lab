package com.padiem.connector.contract

import java.text.Normalizer

/**
 * The #5163 Android connector wire contract, transcribed from
 * `docs/operations/ANDROID_CONNECTOR_SERVER_CONTRACT_20261019.md`.
 *
 * These are server-owned literals. A client-side edit here is a contract change and
 * needs the matching server revision, not the other way round.
 */
object AndroidConnectorContract {
    const val PROFILE_CONTRACT_VERSION = "claw-local-android-saf-profile.v1"
    const val PROFILE_REF = "profile.android.saf-txt.v1"
    const val TEXT_RESULT_CONTRACT_VERSION = "claw-local-agent-text-result.v1"
    const val COMMAND_MATERIAL_CONTRACT_VERSION = "claw-local-command-material.v2"

    const val RECEIPT_FORMAT = "claw-android-saf-txt-read-approval.v1"
    const val LOCAL_POLICY_REF = "padiem_android_saf_selected_root_read_policy_v1"
    const val APPROVAL_AUTHORITY_REF = "claw_connector_android_txt_request_v1"
    const val AGENT_RUNTIME_ID = "claw_android_saf_txt_v1"
    const val TOOL_ID = "local.filesystem.read"
    const val CAPABILITY = "local.filesystem.read"
    const val READ_OPERATION = "read"
    const val READ_SUFFIX = ".txt"
    const val REQUIREMENT_USER_CONFIRMATION = "user_confirmation"

    const val MAX_TEXT_RESULT_BYTES = 768
    const val MAX_DECLARED_FOLDERS = 8
    const val MAX_FOLDER_DISPLAY_NAME = 80
    const val MAX_PATH_CHARS = 1024
    const val APPROVAL_WINDOW_SECONDS = 300L
    const val MAX_REQUEST_BODY_BYTES = 262_144
    const val MAX_RESPONSE_BODY_BYTES = 262_144

    const val ROUTE_SESSION = "/session"
    const val ROUTE_POLL = "/poll"
    const val ROUTE_MATERIAL = "/material"
    const val ROUTE_HEARTBEAT = "/heartbeat"
    const val ROUTE_ACKNOWLEDGE = "/acknowledge"
    const val ROUTE_TEXT_RESULT = "/text-result"
    const val ROUTE_ANDROID_PROFILE = "/android-profile"

    const val STATE_PENDING = "pending"
    const val STATE_CONTENT = "content"
    const val TERMINATION_EXITED = "exited"

    const val PAIRING_PROOF_TRANSCRIPT = "claw-local-agent-pairing-proof.v1"
    const val PAIRING_PROOF_REF_PREFIX = "pairing-proof:"
    const val INSTALL_ACK_TRANSCRIPT_VERSION = "padiem.connector-device-install-ack.v1"
    const val INSTALL_PROOF_KIND = "protected_store_save_readback"

    /** Canonical broker route set for this device class; anything else fails closed. */
    val DEVICE_ROUTES = setOf(
        ROUTE_SESSION, ROUTE_POLL, ROUTE_MATERIAL, ROUTE_HEARTBEAT,
        ROUTE_ACKNOWLEDGE, ROUTE_TEXT_RESULT, ROUTE_ANDROID_PROFILE,
    )

    private val REF = Regex("^[A-Za-z0-9][A-Za-z0-9._:@+\\-]{0,255}$")
    private val HEX64 = Regex("^[0-9a-f]{64}$")

    fun isOpaqueRef(value: Any?): Boolean = value is String && REF.matches(value)

    fun isDigest(value: Any?): Boolean = value is String && HEX64.matches(value)

    /**
     * A relative display path the server accepts: at most [MAX_PATH_CHARS] characters,
     * already NFC, no surrounding whitespace, no control character, no URI, no drive
     * letter, no empty / `.` / `..` segment, and it names an exact `.txt` document.
     * Mirrors `connector_android_saf_approval_material._relative_txt_path` so the phone
     * refuses the same values the server refuses instead of attempting them.
     */
    fun isRelativeReadPath(value: Any?): Boolean {
        if (value !is String || value.isEmpty() || value.length > MAX_PATH_CHARS) return false
        if (Normalizer.normalize(value, Normalizer.Form.NFC) != value) return false
        if (value.trim { ch -> ch <= ' ' } != value) return false
        if (value.any { it.code < 32 || it.code == 127 }) return false
        if (value.contains("://") || value.lowercase().startsWith("content:")) return false
        val parts = value.replace('\\', '/').split("/")
        if (value.startsWith("/") || value.startsWith("\\")) return false
        if (value.length >= 2 && value[1] == ':') return false
        if (parts.first().contains(':')) return false
        if (parts.any { it.isEmpty() || it == "." || it == ".." }) return false
        return value.lowercase().endsWith(READ_SUFFIX)
    }
}
