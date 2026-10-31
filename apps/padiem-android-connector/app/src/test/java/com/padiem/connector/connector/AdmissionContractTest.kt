package com.padiem.connector.connector

import com.padiem.connector.broker.RunnerOutcome
import com.padiem.connector.net.DeviceProtocolException
import com.padiem.connector.net.QueuedCommand
import com.padiem.connector.support.ConnectorHarness
import org.junit.Assert.*
import org.junit.Test

class AdmissionContractTest {
    private fun ready(): ConnectorHarness {
        val h = ConnectorHarness()
        h.gateway.put(h.declaredRootRef(), "notes/report.txt", "test")
        h.runner.openSession(h.surface.sessionId)
        h.runner.declareFolders(h.surface.sessionId)
        h.surface.enqueue(rootRef = h.declaredRootRef())
        return h
    }

    @Test fun admissionSuccessRunsAndAcknowledges() {
        val h = ready()
        assertTrue(h.runner.runPass(h.surface.sessionId, 0).outcome is RunnerOutcome.Executed)
        assertTrue(h.surface.calls.indexOf("/admission") < h.surface.calls.indexOf("/acknowledge"))
        assertEquals(1, h.gateway.readCount)
        assertEquals(1, h.surface.deliveredCommands.single().acknowledgeCount)
    }

    @Test fun deniedAdmissionNeverReadsOrAcknowledges() {
        val h = ready()
        h.surface.admissionDenied = true
        assertTrue(h.runner.runPass(h.surface.sessionId, 0).outcome is RunnerOutcome.Refused)
        assertEquals(0, h.gateway.readCount)
        assertFalse(h.surface.calls.contains("/acknowledge"))
    }

    @Test fun noAdmissionResponseNeverReadsOrAcknowledges() {
        val h = ready()
        h.surface.admissionNoResponse = true
        assertTrue(h.runner.runPass(h.surface.sessionId, 0).outcome is RunnerOutcome.Offline)
        assertEquals(0, h.gateway.readCount)
        assertFalse(h.surface.calls.contains("/acknowledge"))
    }

    @Test fun noReferencesCannotBeAcknowledged() {
        val h = ready()
        val command = QueuedCommand("cmd", "run", "tool", 1L, "a".repeat(64), "rev", "req", "queued")
        try {
            h.client.acknowledge(h.surface.sessionId, command)
            fail("acknowledgement without admission must fail")
        } catch (_: DeviceProtocolException) { }
        assertFalse(h.surface.calls.contains("/acknowledge"))
    }
}
