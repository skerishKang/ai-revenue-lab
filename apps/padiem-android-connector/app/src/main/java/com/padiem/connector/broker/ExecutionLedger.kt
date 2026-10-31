package com.padiem.connector.broker

import com.padiem.connector.contract.Json
import com.padiem.connector.data.LocalStateStore

/** How far one approved read actually got, as confirmed by a broker answer. */
enum class ReadStage {
    PENDING_SENT,
    READ_COMPLETED,
    ACKNOWLEDGED,
    RESULT_DELIVERED,
}

/**
 * The phone's own record of what it already did for a command.
 *
 * This is the duplicate-prevention half of #5163 §9: a re-poll, a process restart, or a lost
 * response must never turn into a second document read or a second staging of the same result.
 * A stage is recorded only after the broker accepted the call that produced it, so an
 * unconfirmed step is retried rather than skipped.
 */
class ExecutionLedger(private val store: LocalStateStore) {

    private val entries: LinkedHashMap<String, Entry> = LinkedHashMap()
    private var loaded = false

    fun stage(commandId: String): ReadStage? {
        ensureLoaded()
        return entries[commandId]?.stage
    }

    fun fingerprint(commandId: String): String? {
        ensureLoaded()
        return entries[commandId]?.fingerprint
    }

    fun record(commandId: String, fingerprint: String, stage: ReadStage) {
        ensureLoaded()
        val previous = entries[commandId]
        require(previous == null || previous.fingerprint == fingerprint) {
            "one command id may not carry two fingerprints"
        }
        if (previous != null && previous.stage.ordinal >= stage.ordinal) return
        entries[commandId] = Entry(fingerprint, stage)
        trim()
        persist()
    }

    private fun ensureLoaded() {
        if (loaded) return
        loaded = true
        val rows = store.load()?.let { Json.parse(it) } as? List<*> ?: return
        for (row in rows) {
            val fields = row as? Map<*, *> ?: continue
            val commandId = fields["command_id"] as? String ?: continue
            val fingerprint = fields["request_fingerprint"] as? String ?: continue
            val stageName = fields["stage"] as? String ?: continue
            val stage = ReadStage.values().firstOrNull { it.name == stageName } ?: continue
            entries[commandId] = Entry(fingerprint, stage)
        }
    }

    private fun trim() {
        while (entries.size > MAX_RETAINED) {
            val oldest = entries.entries.firstOrNull { it.value.stage == ReadStage.RESULT_DELIVERED }
                ?: entries.entries.first()
            entries.remove(oldest.key)
        }
    }

    private fun persist() {
        store.save(
            Json.encode(entries.map { (commandId, entry) ->
                linkedMapOf<String, Any?>(
                    "command_id" to commandId,
                    "request_fingerprint" to entry.fingerprint,
                    "stage" to entry.stage.name,
                )
            }),
        )
    }

    private data class Entry(val fingerprint: String, val stage: ReadStage)

    private companion object {
        const val MAX_RETAINED = 64
    }
}
