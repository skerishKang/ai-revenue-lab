package com.padiem.connector.support

import com.padiem.connector.broker.AndroidReadRunner
import com.padiem.connector.broker.ExecutionLedger
import com.padiem.connector.data.DeviceCredentialVault
import com.padiem.connector.data.DeviceIdentityStore
import com.padiem.connector.data.LocalStateStore
import com.padiem.connector.data.SafRootRegistry
import com.padiem.connector.net.BrokerDeviceClient
import com.padiem.connector.net.DeviceIdentity
import com.padiem.connector.net.DeviceOfflineException
import com.padiem.connector.net.DeviceTransport
import com.padiem.connector.saf.ReadOutcome
import com.padiem.connector.saf.SafReadFailed
import com.padiem.connector.saf.SafTextReadGateway
import java.nio.charset.StandardCharsets

/**
 * Test transport: hands the client's serialized request to [MockBrokerSurface] and returns its
 * status and JSON body. A route listed in [offlineRoutes] raises the same
 * [DeviceOfflineException] the production transport throws when a socket cannot be opened.
 */
class MockTransport(private val surface: MockBrokerSurface) : DeviceTransport {
    var offlineRoutes: Set<String> = emptySet()

    override fun post(route: String, bodyJson: String) =
        if (route in offlineRoutes) {
            throw DeviceOfflineException("mock offline")
        } else {
            surface.handle(route, "POST", "application/json", bodyJson)
        }
}

class InMemoryLocalStateStore : LocalStateStore {
    private var text: String? = null
    override fun load(): String? = text
    override fun save(value: String) {
        text = value
    }

    override fun clear() {
        text = null
    }
}

/** Records whether the platform-store save/readback confirmation is honoured. */
class ConfirmingVault(
    private var credential: ByteArray? = null,
    var confirmReadback: Boolean = true,
) : DeviceCredentialVault {
    var saves = 0
    var reads = 0

    override fun saveAndConfirm(value: ByteArray): Boolean {
        saves += 1
        if (!confirmReadback) return false
        credential = value.copyOf()
        return credential!!.contentEquals(value)
    }

    override fun read(): ByteArray? {
        reads += 1
        return credential?.copyOf()
    }

    override fun clear(): Boolean {
        credential = null
        return true
    }
}

/** The fake SAF side: counts document touches so a duplicate execution is observable. */
class FakeSafGateway : SafTextReadGateway {
    val documents = LinkedHashMap<String, ByteArray>()
    var readCount = 0
    var failWith: String? = null

    fun put(rootRef: String, pathRelative: String, content: String) {
        documents["$rootRef|$pathRelative"] = content.toByteArray(StandardCharsets.UTF_8)
    }

    override fun readText(rootRef: String, pathRelative: String, maxBytes: Int): ReadOutcome {
        readCount += 1
        failWith?.let { throw SafReadFailed(it, "fake gateway refuses the read") }
        val stored = documents["$rootRef|$pathRelative"]
            ?: throw SafReadFailed("document_not_found", "fake gateway has no such document")
        val bounded = if (stored.size <= maxBytes) stored else stored.copyOf(maxBytes)
        return ReadOutcome(text = String(bounded, StandardCharsets.UTF_8), bytes = bounded)
    }
}

/** One wired connector: mock surface plus runner, with the queue state exposed to assertions. */
class ConnectorHarness(
    val surface: MockBrokerSurface = MockBrokerSurface(),
) {
    val gateway = FakeSafGateway()
    val state = InMemoryLocalStateStore()
    val ledgerState = InMemoryLocalStateStore()
    val registry = SafRootRegistry(state)
    val ledger = ExecutionLedger(ledgerState)
    val identities = DeviceIdentityStore(InMemoryLocalStateStore(), ::fixedHex)
    val transport = MockTransport(surface)
    val identity = DeviceIdentity(
        bindingRef = surface.bindingRef,
        deviceId = surface.deviceId,
        accountRef = surface.accountRef,
        workspaceRef = surface.workspaceRef,
        credentialB64 = surface.credentialB64(),
        credentialGeneration = 1L,
    )
    val client = BrokerDeviceClient(
        transport = transport,
        identity = identity,
        clock = { REQUEST_STAMP },
    )
    val runner = AndroidReadRunner(
        client = client,
        gateway = gateway,
        roots = registry,
        ledger = ledger,
        identities = identities,
        nowEpochSeconds = { nowEpochSeconds },
    )

    /** A fresh runner over the same persisted ledger: the process-restart case. */
    fun restartedRunner(): AndroidReadRunner = AndroidReadRunner(
        client = BrokerDeviceClient(transport, identity) { REQUEST_STAMP },
        gateway = gateway,
        roots = registry,
        ledger = ExecutionLedger(ledgerState),
        identities = identities,
        nowEpochSeconds = { nowEpochSeconds },
    )

    /** Inside the receipt's five-minute approval window. */
    val nowEpochSeconds: Long = java.time.Instant.parse("2026-10-19T06:02:00Z").epochSecond

    init {
        registry.replace(listOf(TREE_URI to "Documents"))
    }

    fun declaredRootRef(): String = registry.declaration().first()["root_ref"] as String

    private companion object {
        const val REQUEST_STAMP = "2026-10-19T06:02:00Z"
        const val TREE_URI = "content://com.android.externalstorage.documents/tree/primary%3ADocuments"

        fun fixedHex(length: Int): String = "0123456789abcdef".repeat(length / 16 + 1).substring(0, length)
    }
}
