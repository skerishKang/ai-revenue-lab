package com.padiem.connector.broker

import com.padiem.connector.contract.AndroidConnectorContract
import com.padiem.connector.core.ApprovedRead
import com.padiem.connector.core.ReadReceiptVerifier
import com.padiem.connector.core.ReceiptRefusal
import com.padiem.connector.data.DeviceIdentityStore
import com.padiem.connector.data.SafRootRegistry
import com.padiem.connector.net.BrokerDeviceClient
import com.padiem.connector.net.DeviceOfflineException
import com.padiem.connector.net.DeviceProtocolException
import com.padiem.connector.net.DeviceReply
import com.padiem.connector.net.QueuedCommand
import com.padiem.connector.saf.ReadOutcome
import com.padiem.connector.saf.SafReadFailed
import com.padiem.connector.saf.SafTextReadGateway

/** What one runner step concluded. Every state is a separate claim, never collapsed into "ok". */
sealed interface RunnerOutcome {
    data object Idle : RunnerOutcome
    data class Declared(val folderCount: Int) : RunnerOutcome
    data class Executed(val commandId: String, val contentBytes: Int) : RunnerOutcome
    data class Skipped(val commandId: String, val reason: String) : RunnerOutcome
    data class Refused(val commandId: String?, val code: String) : RunnerOutcome
    data class Offline(val reason: String) : RunnerOutcome
}

/** One pass over the queue, plus the sequence the caller should poll after next. */
data class PassResult(val outcome: RunnerOutcome, val lastSequence: Long, val executedCount: Int)

/**
 * The #5163 §7 device state machine, in exactly this order:
 *
 * ```text
 * /poll -> /material -> verify receipt -> /admission -> /text-result{pending}
 *       -> SAF read (<= 768 UTF-8 bytes) -> /acknowledge{exited,0}
 *       -> /text-result{content, sha256, bytes}
 * ```
 *
 * Rules this class owns:
 *
 * * the `pending` intent is sent **before** the document is touched, so a read that never
 *   completes cannot be mistaken for a staged result;
 * * a failed read is never acknowledged as success — the command stays un-terminal and the
 *   conversation stays unchanged, which is §8 point 1;
 * * the ledger is consulted before each step, so a restart, a re-poll or a lost response cannot
 *   turn into a second execution of one command;
 * * a refusal is reported with the broker's own code. The phone mints no command, admission ref,
 *   evidence ref or revision — it echoes only what the server sent.
 */
class AndroidReadRunner(
    private val client: BrokerDeviceClient,
    private val gateway: SafTextReadGateway,
    private val roots: SafRootRegistry,
    private val ledger: ExecutionLedger,
    private val identities: DeviceIdentityStore,
    private val nowEpochSeconds: () -> Long = { System.currentTimeMillis() / 1000L },
) {

    private val readCache = LinkedHashMap<String, ReadOutcome>()

    /** Content held for one command inside this process, never across a restart. */
    private fun rememberedContent(commandId: String): ReadOutcome? = readCache[commandId]

    fun openSession(sessionId: String): RunnerOutcome = try {
        refused(client.openSession(sessionId, SESSION_TTL_SECONDS)) { RunnerOutcome.Idle }
    } catch (error: DeviceOfflineException) {
        RunnerOutcome.Offline("session open unreachable")
    }

    fun declareFolders(sessionId: String): RunnerOutcome = try {
        refused(client.declareFolders(sessionId, roots.declaration())) {
            RunnerOutcome.Declared(roots.declaration().size)
        }
    } catch (error: DeviceOfflineException) {
        RunnerOutcome.Offline("profile declaration unreachable")
    }

    fun runPass(sessionId: String, afterSequence: Long, limit: Int = 1): PassResult {
        val reply: DeviceReply
        val commands: List<QueuedCommand>
        try {
            val polled = client.poll(sessionId, afterSequence, limit)
            reply = polled.first
            commands = polled.second
        } catch (error: DeviceOfflineException) {
            return PassResult(RunnerOutcome.Offline("poll unreachable"), afterSequence, 0)
        } catch (error: DeviceProtocolException) {
            return PassResult(RunnerOutcome.Refused(null, "poll_protocol_error"), afterSequence, 0)
        }
        if (reply is DeviceReply.Refused) {
            return PassResult(RunnerOutcome.Refused(null, reply.code), afterSequence, 0)
        }
        val actionable = commands.filter { it.state in ACTIONABLE_STATES }
        if (actionable.isEmpty()) return PassResult(RunnerOutcome.Idle, afterSequence, 0)

        var lastSequence = afterSequence
        var executed = 0
        var outcome: RunnerOutcome = RunnerOutcome.Idle
        for (command in actionable) {
            val handled = handle(sessionId, command)
            outcome = handled
            if (handled is RunnerOutcome.Executed) executed += 1
            if (handled is RunnerOutcome.Offline || handled is RunnerOutcome.Refused) break
            if (command.sequence > lastSequence) lastSequence = command.sequence
        }
        return PassResult(outcome, lastSequence, executed)
    }

    private fun handle(sessionId: String, command: QueuedCommand): RunnerOutcome {
        val recorded = ledger.stage(command.commandId)
        if (recorded == ReadStage.RESULT_DELIVERED) {
            return RunnerOutcome.Skipped(command.commandId, "result already delivered")
        }
        val remembered = ledger.fingerprint(command.commandId)
        if (remembered != null && remembered != command.requestFingerprint) {
            return RunnerOutcome.Refused(command.commandId, "ledger_fingerprint_conflict")
        }

        val prepared = prepare(sessionId, command)
        if (prepared is PreparedOutcome.Failed) return prepared.outcome
        val approved = (prepared as PreparedOutcome.Ready).approved

        if (command.requestId.isNotEmpty() && command.requestId != approved.requestId) {
            return RunnerOutcome.Refused(command.commandId, "request_id_mismatch")
        }
        val admission = try {
            client.admit(sessionId, command.copy(requestId = approved.requestId))
        } catch (error: DeviceOfflineException) {
            return RunnerOutcome.Offline("admission unreachable")
        } catch (error: DeviceProtocolException) {
            return RunnerOutcome.Refused(command.commandId, "admission_protocol_error")
        }
        if (admission.first is DeviceReply.Refused) {
            return RunnerOutcome.Refused(command.commandId, (admission.first as DeviceReply.Refused).code)
        }
        val admitted = admission.second
            ?: return RunnerOutcome.Refused(command.commandId, "command_not_admitted")

        if (recorded == null || recorded < ReadStage.PENDING_SENT) {
            val failure = send(command.commandId, "pending intent") { client.pendingIntent(admitted) }
            if (failure != null) return failure
            ledger.record(command.commandId, command.requestFingerprint, ReadStage.PENDING_SENT)
        }

        val content: ReadOutcome = rememberedContent(command.commandId) ?: run {
            val freshly = try {
                gateway.readText(
                    rootRef = approved.rootRef,
                    pathRelative = approved.pathRelative,
                    maxBytes = AndroidConnectorContract.MAX_TEXT_RESULT_BYTES,
                )
            } catch (error: SafReadFailed) {
                // No terminal fact is created; the command stays un-acknowledged.
                return RunnerOutcome.Refused(command.commandId, "saf_read_" + error.code)
            } catch (error: RuntimeException) {
                return RunnerOutcome.Refused(command.commandId, "saf_read_failed")
            }
            if (freshly.bytes.size > AndroidConnectorContract.MAX_TEXT_RESULT_BYTES) {
                return RunnerOutcome.Refused(command.commandId, "saf_read_too_large")
            }
            // Held for this process only: a retried acknowledgement must not read the owner's
            // document a second time, and customer text is never persisted to app storage.
            if (readCache.size >= READ_CACHE_BOUND) readCache.clear()
            readCache[command.commandId] = freshly
            freshly
        }

        val current = ledger.stage(command.commandId)
        if (current == null || current < ReadStage.ACKNOWLEDGED) {
            val failure = send(command.commandId, "acknowledge") { client.acknowledge(sessionId, admitted) }
            if (failure != null) return failure
            ledger.record(command.commandId, command.requestFingerprint, ReadStage.ACKNOWLEDGED)
        }

        val deliveryFailure = send(command.commandId, "content result") {
            client.contentResult(admitted, content.text, content.bytes)
        }
        if (deliveryFailure != null) return deliveryFailure
        ledger.record(command.commandId, command.requestFingerprint, ReadStage.RESULT_DELIVERED)
        // The verified text has now reached the broker; no copy is kept on the phone.
        readCache.remove(command.commandId)
        return RunnerOutcome.Executed(command.commandId, content.bytes.size)
    }

    private sealed interface PreparedOutcome {
        class Ready(val approved: ApprovedRead) : PreparedOutcome
        class Failed(val outcome: RunnerOutcome) : PreparedOutcome
    }

    private fun prepare(sessionId: String, command: QueuedCommand): PreparedOutcome {
        val reply = try {
            client.material(sessionId, identities.newRequestRef(), command)
        } catch (error: DeviceOfflineException) {
            return PreparedOutcome.Failed(RunnerOutcome.Offline("material unreachable"))
        } catch (error: DeviceProtocolException) {
            return PreparedOutcome.Failed(RunnerOutcome.Refused(command.commandId, "material_protocol_error"))
        }
        if (reply is DeviceReply.Refused) {
            return PreparedOutcome.Failed(RunnerOutcome.Refused(command.commandId, reply.code))
        }
        val accepted = reply as DeviceReply.Accepted
        val wire = accepted.body["material"] as? Map<*, *>
            ?: return PreparedOutcome.Failed(RunnerOutcome.Refused(command.commandId, "material_wire_missing"))
        if (wire["contract_version"] != AndroidConnectorContract.COMMAND_MATERIAL_CONTRACT_VERSION ||
            wire["command_id"] != command.commandId ||
            wire["request_fingerprint"] != command.requestFingerprint
        ) {
            return PreparedOutcome.Failed(RunnerOutcome.Refused(command.commandId, "material_wire_mismatch"))
        }
        @Suppress("UNCHECKED_CAST")
        val material = wire["material"] as? Map<String, Any?>
            ?: return PreparedOutcome.Failed(RunnerOutcome.Refused(command.commandId, "material_missing"))
        val revisionRef = wire["revision_ref"] as? String
            ?: return PreparedOutcome.Failed(RunnerOutcome.Refused(command.commandId, "revision_missing"))
        @Suppress("UNCHECKED_CAST")
        val receipt = material["p01_approval_payload"] as? Map<String, Any?>
            ?: return PreparedOutcome.Failed(RunnerOutcome.Refused(command.commandId, "receipt_missing"))
        return try {
            PreparedOutcome.Ready(
                ReadReceiptVerifier.verify(
                    material = material,
                    receipt = receipt,
                    declaredRootRefs = roots.declaredRootRefs(),
                    expectedCommandId = command.commandId,
                    expectedRevisionRef = revisionRef,
                    wireFingerprint = command.requestFingerprint,
                    nowEpochSeconds = nowEpochSeconds(),
                ),
            )
        } catch (error: ReceiptRefusal) {
            PreparedOutcome.Failed(RunnerOutcome.Refused(command.commandId, error.code))
        } catch (error: IllegalArgumentException) {
            PreparedOutcome.Failed(RunnerOutcome.Refused(command.commandId, "receipt_unverifiable"))
        }
    }

    /** `null` means the broker accepted the call; otherwise the caller returns this outcome. */
    private fun send(commandId: String, label: String, call: () -> DeviceReply): RunnerOutcome? = try {
        val reply = call()
        if (reply is DeviceReply.Refused) RunnerOutcome.Refused(commandId, reply.code) else null
    } catch (error: DeviceOfflineException) {
        RunnerOutcome.Offline("$label unreachable")
    } catch (error: DeviceProtocolException) {
        RunnerOutcome.Refused(commandId, "$label" + "_protocol_error")
    }

    private fun refused(reply: DeviceReply, onAccepted: () -> RunnerOutcome): RunnerOutcome = when (reply) {
        is DeviceReply.Accepted -> onAccepted()
        is DeviceReply.Refused -> RunnerOutcome.Refused(null, reply.code)
    }

    private companion object {
        /**
         * A command the broker has admitted or acknowledged is still actionable here: #5163 §9
         * requires a lost content response to be retried, and the acknowledgement is already
         * durable, so only the delivery is missing.
         */
        val ACTIONABLE_STATES = setOf("queued", "admitted", "acknowledged")
        const val SESSION_TTL_SECONDS = 900L

        /** At most one bounded document body is held; anything older is dropped. */
        const val READ_CACHE_BOUND = 2
    }
}
