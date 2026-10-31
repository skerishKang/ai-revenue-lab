package com.padiem.connector.connector

import com.padiem.connector.broker.ExecutionLedger
import com.padiem.connector.broker.ReadStage
import com.padiem.connector.broker.RunnerOutcome
import com.padiem.connector.data.SafRootRegistry
import com.padiem.connector.support.ConnectorHarness
import com.padiem.connector.support.InMemoryLocalStateStore
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * #5163 §9 from the phone side: offline, retry and duplicate must not become a second execution,
 * and no step may run before the step that authorizes it.
 */
class DuplicateAndOfflineTest {

    @Test
    fun `a delivered command on a re-poll adds nothing but the poll itself`() {
        val harness = ConnectorHarness()
        val surface = harness.surface
        harness.gateway.put(harness.declaredRootRef(), "notes/report.txt", "first")
        harness.runner.openSession(surface.sessionId)
        harness.runner.declareFolders(surface.sessionId)
        surface.enqueue(rootRef = harness.declaredRootRef())
        assertEquals(1, harness.runner.runPass(surface.sessionId, 0).executedCount)

        val callsBefore = surface.calls.size
        val second = harness.runner.runPass(surface.sessionId, 0)

        assertEquals(RunnerOutcome.Idle, second.outcome)
        assertEquals(1, harness.gateway.readCount)
        assertEquals(listOf("/poll"), surface.calls.drop(callsBefore))
    }

    @Test
    fun `a command the ledger already delivered is skipped even when the queue offers it again`() {
        val harness = ConnectorHarness()
        val surface = harness.surface
        harness.gateway.put(harness.declaredRootRef(), "notes/report.txt", "replayed")
        harness.runner.openSession(surface.sessionId)
        harness.runner.declareFolders(surface.sessionId)
        val command = surface.enqueue(rootRef = harness.declaredRootRef())
        harness.runner.runPass(surface.sessionId, 0)
        // A broker that re-offers a finished command (state replay, lost terminal write).
        command.state = "queued"

        val pass = harness.runner.runPass(surface.sessionId, 0)

        assertEquals(RunnerOutcome.Skipped(command.commandId, "result already delivered"), pass.outcome)
        assertEquals(1, harness.gateway.readCount)
    }

    @Test
    fun `a restart with the same persisted ledger does not re-execute an offered command`() {
        val harness = ConnectorHarness()
        val surface = harness.surface
        harness.gateway.put(harness.declaredRootRef(), "notes/report.txt", "first")
        harness.runner.openSession(surface.sessionId)
        harness.runner.declareFolders(surface.sessionId)
        val command = surface.enqueue(rootRef = harness.declaredRootRef())
        harness.runner.runPass(surface.sessionId, 0)
        command.state = "queued"

        // Same persisted ledger, no in-memory read cache: exactly a process restart.
        val pass = harness.restartedRunner().runPass(surface.sessionId, 0)

        assertEquals(RunnerOutcome.Skipped(command.commandId, "result already delivered"), pass.outcome)
        assertEquals(1, harness.gateway.readCount)
        assertEquals(ReadStage.RESULT_DELIVERED, ExecutionLedger(harness.ledgerState).stage(command.commandId))
    }

    @Test
    fun `offline at the pending step reads nothing and resumes cleanly`() {
        val harness = ConnectorHarness()
        val surface = harness.surface
        harness.gateway.put(harness.declaredRootRef(), "notes/report.txt", "later")
        harness.runner.openSession(surface.sessionId)
        harness.runner.declareFolders(surface.sessionId)
        surface.enqueue(rootRef = harness.declaredRootRef())
        harness.transport.offlineRoutes = setOf("/text-result")

        val stalled = harness.runner.runPass(surface.sessionId, 0)

        assertTrue(stalled.outcome is RunnerOutcome.Offline)
        // The contract orders the pending intent before the read, so an unreachable broker means
        // the owner's document was never opened.
        assertEquals(0, harness.gateway.readCount)
        assertEquals("admitted", surface.deliveredCommands.single().state)

        harness.transport.offlineRoutes = emptySet()
        val resumed = harness.runner.runPass(surface.sessionId, 0)

        assertEquals(1, resumed.executedCount)
        assertEquals(1, harness.gateway.readCount)
        assertEquals("delivered", surface.deliveredCommands.single().state)
    }

    @Test
    fun `offline at the poll step reports no execution and no fabricated result`() {
        val harness = ConnectorHarness()
        val surface = harness.surface
        harness.gateway.put(harness.declaredRootRef(), "notes/report.txt", "queued")
        harness.runner.openSession(surface.sessionId)
        harness.runner.declareFolders(surface.sessionId)
        surface.enqueue(rootRef = harness.declaredRootRef())
        harness.transport.offlineRoutes = setOf("/poll")

        val pass = harness.runner.runPass(surface.sessionId, 0)

        assertEquals(RunnerOutcome.Offline("poll unreachable"), pass.outcome)
        assertEquals(0, pass.executedCount)
        assertEquals(0, harness.gateway.readCount)
        assertEquals("queued", surface.deliveredCommands.single().state)
        assertFalse(surface.deliveredCommands.single().pendingStaged)
    }

    @Test
    fun `a lost content response retries without a second read or a second acknowledgement`() {
        val harness = ConnectorHarness()
        val surface = harness.surface
        harness.gateway.put(harness.declaredRootRef(), "notes/report.txt", "retry-me")
        harness.runner.openSession(surface.sessionId)
        harness.runner.declareFolders(surface.sessionId)
        surface.enqueue(rootRef = harness.declaredRootRef())
        surface.contentFailuresLeft = 1

        val stalled = harness.runner.runPass(surface.sessionId, 0)
        assertEquals(
            RunnerOutcome.Refused("andcmd-mock-1", "local_agent_http_dependency_unavailable"),
            stalled.outcome,
        )

        val resumed = harness.runner.runPass(surface.sessionId, 0)

        assertEquals(1, resumed.executedCount)
        assertEquals("one document read across the retry", 1, harness.gateway.readCount)
        assertEquals("one acknowledgement across the retry", 1, surface.deliveredCommands.single().acknowledgeCount)
        assertEquals(ReadStage.RESULT_DELIVERED, harness.ledger.stage("andcmd-mock-1"))
    }

    @Test
    fun `a lost acknowledgement is retried as the same terminal fact`() {
        val harness = ConnectorHarness()
        val surface = harness.surface
        harness.gateway.put(harness.declaredRootRef(), "notes/report.txt", "ack-retry")
        harness.runner.openSession(surface.sessionId)
        harness.runner.declareFolders(surface.sessionId)
        surface.enqueue(rootRef = harness.declaredRootRef())
        surface.acknowledgeFailuresLeft = 1

        val stalled = harness.runner.runPass(surface.sessionId, 0)
        assertEquals(
            RunnerOutcome.Refused("andcmd-mock-1", "local_agent_http_dependency_unavailable"),
            stalled.outcome,
        )

        val resumed = harness.runner.runPass(surface.sessionId, 0)

        assertEquals(1, resumed.executedCount)
        assertEquals(1, surface.deliveredCommands.single().acknowledgeCount)
        assertEquals(1, harness.gateway.readCount)
    }

    @Test
    fun `a command id that changes fingerprint is refused instead of re-executed`() {
        val harness = ConnectorHarness()
        val surface = harness.surface
        harness.gateway.put(harness.declaredRootRef(), "notes/report.txt", "clash")
        harness.runner.openSession(surface.sessionId)
        harness.runner.declareFolders(surface.sessionId)
        harness.ledger.record("andcmd-mock-1", "b".repeat(64), ReadStage.PENDING_SENT)
        surface.enqueue(rootRef = harness.declaredRootRef())

        val pass = harness.runner.runPass(surface.sessionId, 0)

        assertEquals(RunnerOutcome.Refused("andcmd-mock-1", "ledger_fingerprint_conflict"), pass.outcome)
        assertEquals(0, harness.gateway.readCount)
    }

    @Test
    fun `an empty declaration withdraws the set and the broker accepts the replacement`() {
        val harness = ConnectorHarness()
        val surface = harness.surface
        harness.runner.openSession(surface.sessionId)
        harness.runner.declareFolders(surface.sessionId)
        assertEquals(1, surface.folderCount)

        harness.registry.withdrawAll()
        val withdrawn = harness.runner.declareFolders(surface.sessionId)

        assertEquals(RunnerOutcome.Declared(0), withdrawn)
        assertEquals(0, surface.folderCount)
        assertEquals(0, harness.registry.declaredRootRefs().size)
    }

    @Test
    fun `a read for a withdrawn root is refused by the broker-side check on the next pass`() {
        val harness = ConnectorHarness()
        val surface = harness.surface
        harness.runner.openSession(surface.sessionId)
        harness.runner.declareFolders(surface.sessionId)
        val declared = harness.declaredRootRef()
        harness.registry.withdrawAll()
        harness.runner.declareFolders(surface.sessionId)
        surface.enqueue(rootRef = declared)

        val pass = harness.runner.runPass(surface.sessionId, 0)

        assertEquals(RunnerOutcome.Refused("andcmd-mock-1", "receipt_root_not_declared"), pass.outcome)
        assertEquals(0, harness.gateway.readCount)
    }

    @Test
    fun `the declared root set survives a restart unchanged`() {
        val store = InMemoryLocalStateStore()
        val registry = SafRootRegistry(store)
        registry.replace(listOf("content://tree/one" to "One", "content://tree/two" to "Two"))
        val refs = registry.declaration().map { it["root_ref"] }

        val reloaded = SafRootRegistry(store)

        assertEquals(refs, reloaded.declaration().map { it["root_ref"] })
        assertEquals("content://tree/one", reloaded.treeUriOf(refs.first() as String))
    }

    @Test
    fun `the ledger never records a stage going backwards`() {
        val ledger = ExecutionLedger(InMemoryLocalStateStore())
        ledger.record("andcmd-x", "a".repeat(64), ReadStage.RESULT_DELIVERED)
        ledger.record("andcmd-x", "a".repeat(64), ReadStage.PENDING_SENT)

        assertEquals(ReadStage.RESULT_DELIVERED, ledger.stage("andcmd-x"))
    }
}
