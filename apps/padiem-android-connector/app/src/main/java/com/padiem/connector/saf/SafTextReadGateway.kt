package com.padiem.connector.saf

/** One bounded document read. `bytes` is never larger than the requested bound. */
data class ReadOutcome(val text: String, val bytes: ByteArray)

/** The requested document is not reachable under the approved SAF root. */
class SafReadFailed(val code: String, message: String) : Exception(message)

/**
 * Reads exactly one approved `.txt` document under one declared root.
 *
 * Kept as a seam so the command runner, the dedup ledger and the offline behaviour are
 * verifiable without a device, while the SAF traversal itself stays in one Android-only
 * implementation.
 */
interface SafTextReadGateway {
    fun readText(rootRef: String, pathRelative: String, maxBytes: Int): ReadOutcome
}
