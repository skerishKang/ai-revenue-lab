package com.padiem.connector.connector

import com.padiem.connector.broker.RunnerOutcome
import com.padiem.connector.support.ConnectorHarness
import com.padiem.connector.support.MockBrokerSurface
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

/**
 * The #5163 §7 execution flow, driven against a mock that enforces the server's own closed
 * request shapes. Order matters as much as content: the pending intent must precede the document
 * read, and the acknowledgement must precede the content body.
 */
class ReadCommandFlowTest {

    @Test
    fun `one approved read travels the contract route order`() {
        val harness = ConnectorHarness()
        val surface = harness.surface
        harness.gateway.put(harness.declaredRootRef(), "notes/report.txt", "PADIEM MOCK TXT")
        assertEquals(RunnerOutcome.Idle, harness.runner.openSession(surface.sessionId))
        assertFalse(harness.runner.declareFolders(surface.sessionId) is RunnerOutcome.Refused)
        surface.enqueue(rootRef = harness.declaredRootRef())

        val pass = harness.runner.runPass(surface.sessionId, afterSequence = 0)

        assertEquals(
            listOf(
                "/session", "/android-profile", "/poll", "/material", "/poll",
                "/text-result", "/acknowledge", "/text-result",
            ),
            surface.calls,
        )
        assertEquals(1, harness.gateway.readCount)
        assertEquals("delivered", surface.deliveredCommands.single().state)
        val executed = pass.outcome as RunnerOutcome.Executed
        assertEquals("PADIEM MOCK TXT".toByteArray().size, executed.contentBytes)
        assertEquals(1, pass.lastSequence)
    }

    @Test
    fun `every request carries exactly the closed key set the broker accepts`() {
        val harness = ConnectorHarness()
        val surface = harness.surface
        harness.gateway.put(harness.declaredRootRef(), "notes/report.txt", "abc")
        harness.runner.openSession(surface.sessionId)
        harness.runner.declareFolders(surface.sessionId)
        surface.enqueue(rootRef = harness.declaredRootRef())
        harness.runner.runPass(surface.sessionId, afterSequence = 0)

        val byRoute = surface.calls.mapIndexed { index, route -> route to surface.requestBodies[index] }
            .groupBy({ it.first }, { it.second })

        assertEquals(
            setOf("session_id", "binding_ref", "credential_b64", "account_ref", "workspace_ref", "now", "ttl_seconds"),
            byRoute.getValue("/session").single().keys,
        )
        assertEquals(
            setOf("session_id", "binding_ref", "credential_b64", "after_sequence", "now", "limit"),
            byRoute.getValue("/poll").first().keys,
        )
        assertEquals(
            setOf(
                "request_ref", "session_id", "binding_ref", "credential_b64",
                "command_id", "request_fingerprint", "now",
            ),
            byRoute.getValue("/material").single().keys,
        )
        assertEquals(
            setOf(
                "session_id", "binding_ref", "credential_b64", "command_id", "admission_ref",
                "evidence_ref", "revision_ref", "termination", "request_id", "exit_code", "now",
            ),
            byRoute.getValue("/acknowledge").single().keys,
        )
        val ack = byRoute.getValue("/acknowledge").single()
        assertEquals("exited", ack["termination"])
        assertEquals(0L, ack["exit_code"])
        // The phone echoes server-owned correlation; it mints none of it.
        assertEquals("admission.android.1", ack["admission_ref"])
        assertEquals("evidence.android.1", ack["evidence_ref"])
        assertEquals("revision.android.1", ack["revision_ref"])
        assertEquals("andreq-mock-1", ack["request_id"])

        val pending = byRoute.getValue("/text-result")[0]
        assertEquals(
            setOf(
                "contract_version", "command_id", "run_id", "request_fingerprint", "state",
                "binding_ref", "credential_b64",
            ),
            pending.keys,
        )
        assertEquals("pending", pending["state"])

        val content = byRoute.getValue("/text-result")[1]
        assertEquals(
            setOf(
                "contract_version", "command_id", "run_id", "request_fingerprint", "state",
                "binding_ref", "credential_b64", "content_utf8", "content_sha256", "content_bytes",
            ),
            content.keys,
        )
        assertEquals("abc", content["content_utf8"])
        assertEquals(3L, content["content_bytes"])
        assertEquals("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", content["content_sha256"])
    }

    @Test
    fun `a declaration wire never carries a content uri`() {
        val harness = ConnectorHarness()
        harness.runner.openSession(harness.surface.sessionId)
        harness.runner.declareFolders(harness.surface.sessionId)

        val profile = harness.surface.requestBodies[1]
        assertFalse(profile.toString().contains("content://"))
        assertEquals(
            setOf("contract_version", "session_id", "profile_ref", "folders", "binding_ref", "credential_b64"),
            profile.keys,
        )
    }

    @Test
    fun `a receipt naming an undeclared root is refused before any document is touched`() {
        val harness = ConnectorHarness()
        val surface = harness.surface
        harness.runner.openSession(surface.sessionId)
        harness.runner.declareFolders(surface.sessionId)
        surface.enqueue(rootRef = "safroot-never-declared")

        val pass = harness.runner.runPass(surface.sessionId, afterSequence = 0)

        assertEquals(RunnerOutcome.Refused("andcmd-mock-1", "receipt_root_not_declared"), pass.outcome)
        assertEquals(0, harness.gateway.readCount)
        assertEquals(0, surface.deliveredCommands.single().acknowledgeCount)
    }

    @Test
    fun `a read failure never becomes an acknowledged success`() {
        val harness = ConnectorHarness()
        val surface = harness.surface
        harness.gateway.failWith = "root_revoked"
        harness.runner.openSession(surface.sessionId)
        harness.runner.declareFolders(surface.sessionId)
        surface.enqueue(rootRef = harness.declaredRootRef())

        val pass = harness.runner.runPass(surface.sessionId, afterSequence = 0)

        assertEquals(RunnerOutcome.Refused("andcmd-mock-1", "saf_read_root_revoked"), pass.outcome)
        assertEquals("admitted", surface.deliveredCommands.single().state)
        assertFalse(surface.deliveredCommands.single().contentStaged)
    }

    @Test
    fun `a tampered pause hash inside the receipt stops the read`() {
        val harness = ConnectorHarness()
        val surface = harness.surface
        harness.runner.openSession(surface.sessionId)
        harness.runner.declareFolders(surface.sessionId)
        surface.enqueue(
            rootRef = harness.declaredRootRef(),
            receiptOverride = surface.receiptVariant(pauseHash = "a".repeat(64)),
        )

        val pass = harness.runner.runPass(surface.sessionId, afterSequence = 0)

        assertEquals(RunnerOutcome.Refused("andcmd-mock-1", "receipt_fingerprint_mismatch"), pass.outcome)
        assertEquals(0, harness.gateway.readCount)
    }

    @Test
    fun `a foreign receipt format is refused for this lane`() {
        val harness = ConnectorHarness()
        val surface = harness.surface
        harness.runner.openSession(surface.sessionId)
        harness.runner.declareFolders(surface.sessionId)
        surface.enqueue(
            rootRef = harness.declaredRootRef(),
            receiptOverride = surface.receiptVariant(format = "claw-windows-command-approval.v1"),
        )

        val pass = harness.runner.runPass(surface.sessionId, afterSequence = 0)

        assertEquals(RunnerOutcome.Refused("andcmd-mock-1", "receipt_format_unsupported"), pass.outcome)
        assertEquals(0, harness.gateway.readCount)
    }

    @Test
    fun `an approval window that already closed is refused`() {
        val harness = ConnectorHarness()
        val surface = harness.surface
        harness.runner.openSession(surface.sessionId)
        harness.runner.declareFolders(surface.sessionId)
        surface.enqueue(
            rootRef = harness.declaredRootRef(),
            receiptOverride = surface.receiptVariant(expiresAt = "2026-10-19T06:01:00Z"),
        )

        val pass = harness.runner.runPass(surface.sessionId, afterSequence = 0)

        assertEquals(RunnerOutcome.Refused("andcmd-mock-1", "receipt_expired"), pass.outcome)
        assertEquals(0, harness.gateway.readCount)
    }

    @Test
    fun `a receipt from another policy is refused`() {
        val harness = ConnectorHarness()
        val surface = harness.surface
        harness.runner.openSession(surface.sessionId)
        harness.runner.declareFolders(surface.sessionId)
        surface.enqueue(
            rootRef = harness.declaredRootRef(),
            receiptOverride = surface.receiptVariant(policyRef = "padiem_windows_selected_folder_read_policy_v1"),
        )

        val pass = harness.runner.runPass(surface.sessionId, afterSequence = 0)

        assertEquals(RunnerOutcome.Refused("andcmd-mock-1", "receipt_policy_mismatch"), pass.outcome)
    }

    @Test
    fun `a path that would leave the approved root is refused before the read`() {
        val harness = ConnectorHarness()
        val surface = harness.surface
        harness.runner.openSession(surface.sessionId)
        harness.runner.declareFolders(surface.sessionId)
        surface.enqueue(rootRef = harness.declaredRootRef(), pathRelative = "notes/../../windows/system32.txt")

        val pass = harness.runner.runPass(surface.sessionId, afterSequence = 0)

        assertEquals(RunnerOutcome.Refused("andcmd-mock-1", "receipt_path_invalid"), pass.outcome)
        assertEquals(0, harness.gateway.readCount)
    }

    @Test
    fun `a command with no live session stops at the session boundary`() {
        val harness = ConnectorHarness()
        val surface = harness.surface
        surface.enqueue(rootRef = harness.declaredRootRef())

        val pass = harness.runner.runPass(surface.sessionId, afterSequence = 0)

        assertEquals(RunnerOutcome.Refused(null, "local_agent_http_session_required"), pass.outcome)
        assertEquals(0, harness.gateway.readCount)
    }
}
