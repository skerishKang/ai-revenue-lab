package com.padiem.connector.core

import com.padiem.connector.enrollment.PairingProof
import java.text.Normalizer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

/**
 * The pinned vectors are the only thing that proves the Kotlin canonical-JSON form agrees with
 * the server's `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.
 * Every expectation below was produced by the server implementation itself, so a client-side
 * escaping, key-order or normalization change fails here instead of on a phone.
 *
 * Non-ASCII input is written only as `\u` escapes: whether a source file stores a composed or a
 * decomposed form is exactly what these tests control, so it must not depend on how the file
 * itself happens to be encoded.
 */
class SafReadFingerprintTest {

    @Test
    fun `reproduces the contract pinned vector`() {
        assertEquals(
            "fb438c4de05d28b5c840a7af23b3eab9dbd223139ba92f2c88cfdf050a994e79",
            SafReadFingerprint.compute(
                actionId = "andact-vector-1",
                runId = "run.android.vector.1",
                deviceId = "device.android.vector.1",
                rootRef = "safroot-documents",
                pathRelative = "notes/report.txt",
                requestedAt = "2026-10-19T06:00:00Z",
            ),
        )
    }

    @Test
    fun `keeps Korean file names as raw UTF-8 instead of escaped ascii`() {
        assertEquals(
            "59fce93978068b23c965b11c2329d5df84fae9a4592daca73a707eaaa64dc0d5",
            SafReadFingerprint.compute(
                actionId = "andact-2",
                runId = "run.2",
                deviceId = "device.android.2",
                rootRef = "safroot-abc",
                pathRelative = "\ub178\ud2b8/\ud55c\uae00 \ud30c\uc77c.txt",
                requestedAt = "2026-10-19T06:00:00Z",
            ),
        )
    }

    @Test
    fun `writes the canonical transcript the server hashes`() {
        assertEquals(
            "{\"action_id\":\"andact-4\",\"device_id\":\"dev\\t4\",\"operation\":\"read\"," +
                "\"path_relative\":\"\u00e9\u4e2d\u6587 \uc5b4\ubc00.txt\"," +
                "\"requested_at\":\"2026-10-19T06:00:00Z\",\"root_ref\":\"safroot-\u00e9\"," +
                "\"run_id\":\"run/4\",\"v\":1}",
            SafReadFingerprint.canonicalTranscript(
                actionId = "andact-4",
                runId = "run/4",
                deviceId = "dev\t4",
                rootRef = "safroot-\u00e9",
                pathRelative = "\u00e9\u4e2d\u6587 \uc5b4\ubc00.txt",
                requestedAt = "2026-10-19T06:00:00Z",
            ),
        )
        assertEquals(
            "35301f79aee0ad04238d3f33db31c6aedd2c172a29f002526907d27cbeb43530",
            SafReadFingerprint.compute(
                actionId = "andact-4",
                runId = "run/4",
                deviceId = "dev\t4",
                rootRef = "safroot-\u00e9",
                pathRelative = "\u00e9\u4e2d\u6587 \uc5b4\ubc00.txt",
                requestedAt = "2026-10-19T06:00:00Z",
            ),
        )
    }

    @Test
    fun `a decomposed path normalizes to the same digest the server hashes`() {
        val composed = "\u00e9\u4e2d\u6587 \uc5b4\ubc00.txt"

        assertEquals(
            SafReadFingerprint.compute(
                actionId = "andact-4",
                runId = "run/4",
                deviceId = "dev\t4",
                rootRef = "safroot-\u00e9",
                pathRelative = composed,
                requestedAt = "2026-10-19T06:00:00Z",
            ),
            SafReadFingerprint.compute(
                actionId = "andact-4",
                runId = "run/4",
                deviceId = "dev\t4",
                rootRef = "safroot-\u00e9",
                pathRelative = Normalizer.normalize(composed, Normalizer.Form.NFD),
                requestedAt = "2026-10-19T06:00:00Z",
            ),
        )
    }

    @Test
    fun `escapes quote, backslash, tab and slash exactly as the server does`() {
        assertEquals(
            "f2aa15f633c2f432abd33aad08b91440a3a15852671dab0ab8d725b26ce5427c",
            SafReadFingerprint.compute(
                actionId = "andact-3",
                runId = "run.3",
                deviceId = "device.android.3",
                rootRef = "safroot-documents",
                pathRelative = "quo\"te\\back\tname.txt",
                requestedAt = "2026-10-19T06:00:00Z",
            ),
        )
    }

    @Test
    fun `a changed approval instant changes the digest`() {
        val base = SafReadFingerprint.compute(
            actionId = "andact-vector-1",
            runId = "run.android.vector.1",
            deviceId = "device.android.vector.1",
            rootRef = "safroot-documents",
            pathRelative = "notes/report.txt",
            requestedAt = "2026-10-19T06:00:00Z",
        )
        val moved = SafReadFingerprint.compute(
            actionId = "andact-vector-1",
            runId = "run.android.vector.1",
            deviceId = "device.android.vector.1",
            rootRef = "safroot-documents",
            pathRelative = "notes/report.txt",
            requestedAt = "2026-10-19T06:00:01Z",
        )

        assertEquals(64, base.length)
        assertFalse(base == moved)
    }

    @Test
    fun `recomputes the HMAC transcripts enrollment and installation require`() {
        assertEquals(
            "pairing-proof:1efe228ceb49152cf72c445393ab0fbef33054fa87a4444afb2786a0587f7663",
            PairingProof.proofRef(
                pairingCode = "CODE-2026-10-19-AAAA",
                challengeId = "challenge.android.1",
                deviceId = "device.android.1",
            ),
        )
        assertEquals(
            "1eb0cfe1d64f6d31b9aa6a9f5df2baeb8d00e33a360e908888ab4eb44481db97",
            PairingProof.installAckProof(
                credential = "c".repeat(32).toByteArray(Charsets.UTF_8),
                challengeId = "challenge.android.1",
                deviceId = "device.android.1",
                bindingRef = "binding.android.1",
                credentialGeneration = 1L,
            ),
        )
    }
}
