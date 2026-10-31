package com.padiem.connector.connector

import com.padiem.connector.contract.AndroidConnectorContract
import com.padiem.connector.contract.Json
import com.padiem.connector.data.DeviceIdentityStore
import com.padiem.connector.data.SafRootRegistry
import com.padiem.connector.enrollment.CanonicalCredentialHandoff
import com.padiem.connector.enrollment.ConnectorEnrollmentClient
import com.padiem.connector.enrollment.DeviceCredentialInstaller
import com.padiem.connector.enrollment.EnrollmentReceipt
import com.padiem.connector.enrollment.PairingProof
import com.padiem.connector.enrollment.UnconfiguredCanonicalCredentialHandoff
import com.padiem.connector.net.DeviceProtocolException
import com.padiem.connector.net.HttpsDeviceTransport
import com.padiem.connector.net.HttpsJsonClient
import com.padiem.connector.support.ConfirmingVault
import com.padiem.connector.support.InMemoryLocalStateStore
import com.padiem.connector.support.MockBrokerSurface
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Auto-enrollment and the SAF folder declaration, against the existing enrollment contract and
 * the mock's server-side rules.
 */
class EnrollmentAndProfileTest {

    @Test
    fun `redeem through the existing enrollment endpoint yields the secret-free receipt`() {
        val surface = MockBrokerSurface()
        val proof = PairingProof.proofRef("CODE-2026-10-19-AAAA", "challenge.android.1", surface.deviceId)

        val outcome = ConnectorEnrollmentClient(surface.enrollmentClient(), surface.deviceId)
            .redeem("challenge.android.1", proof)

        val redeemed = outcome as ConnectorEnrollmentClient.Outcome.Redeemed
        assertEquals(surface.bindingRef, redeemed.receipt.bindingRef)
        assertEquals(surface.accountRef, redeemed.receipt.accountRef)
        assertEquals(surface.workspaceRef, redeemed.receipt.workspaceRef)
        assertEquals(1L, redeemed.receipt.credentialGeneration)
        val body = surface.requestBodies.single()
        assertEquals(setOf("challenge_id", "device_id", "proof_ref"), body.keys)
        assertTrue((body["proof_ref"] as String).startsWith("pairing-proof:"))
        assertFalse(Json.encode(body).contains("CODE-2026-10-19-AAAA"))
    }

    @Test
    fun `an untrusted device gateway and a device swap are both refused`() {
        val surface = MockBrokerSurface()
        val proof = PairingProof.proofRef("code", "challenge.android.1", surface.deviceId)
        surface.enrollmentGatewayTrusts = false

        assertEquals(
            ConnectorEnrollmentClient.Outcome.Refused(403, "connector_enrollment_device_gateway_denied"),
            ConnectorEnrollmentClient(surface.enrollmentClient(), surface.deviceId)
                .redeem("challenge.android.1", proof),
        )

        surface.enrollmentGatewayTrusts = true
        assertEquals(
            ConnectorEnrollmentClient.Outcome.Refused(403, "enrollment_device_swap_denied"),
            ConnectorEnrollmentClient(surface.enrollmentClient(), "device.someone.else")
                .redeem("challenge.android.1", proof),
        )
    }

    @Test
    fun `an enrollment receipt that leaks a credential or wrong flags is refused`() {
        val good = linkedMapOf<String, Any?>(
            "binding_ref" to "binding.android.1", "device_id" to "device.android.1",
            "account_ref" to "account.android.1", "workspace_ref" to "workspace.android.1",
            "consent_id" to "consent.android.1", "credential_generation" to 1L,
            "credential_expires_at" to "2099-01-01T00:00:00Z",
            "credential_installed_by_canonical_handoff" to true,
            "raw_device_credential" to false, "lifecycle" to "paired_offline",
            "dispatch_authorized" to false, "grants_read" to false, "grants_write" to false,
        )
        assertNotNull(EnrollmentReceipt.parse(good, expectedDeviceId = "device.android.1"))

        assertNull(EnrollmentReceipt.parse(LinkedHashMap(good).apply { put("raw_device_credential", true) }, "device.android.1"))
        assertNull(EnrollmentReceipt.parse(LinkedHashMap(good).apply { put("grants_write", true) }, "device.android.1"))
        assertNull(EnrollmentReceipt.parse(LinkedHashMap(good).apply { put("lifecycle", "paired_online") }, "device.android.1"))
        assertNull(
            EnrollmentReceipt.parse(
                LinkedHashMap(good).apply { put("credential_expires_at", "2020-01-01T00:00:00Z") },
                "device.android.1",
            ),
        )
        assertNull(EnrollmentReceipt.parse(LinkedHashMap(good).apply { put("saf_uri", "content://t") }, "device.android.1"))
        assertNull(EnrollmentReceipt.parse(good, "device.other"))
    }

    @Test
    fun `installation is blocked while the canonical protected handoff is not wired`() {
        val vault = ConfirmingVault()

        val outcome = DeviceCredentialInstaller(vault, UnconfiguredCanonicalCredentialHandoff())
            .install(receiptSample(), "challenge.android.1")

        assertEquals(DeviceCredentialInstaller.Outcome.Blocked("credential_handoff_unavailable"), outcome)
        assertEquals("the vault is never written without a canonical credential", 0, vault.saves)
    }

    @Test
    fun `a confirmed platform-store write produces the closed eight-field install ack`() {
        val credential = "c".repeat(32).toByteArray(Charsets.UTF_8)
        val handoff = object : CanonicalCredentialHandoff {
            override fun ready(challengeId: String, deviceId: String) = true
            override fun deliverOnce(challengeId: String, deviceId: String) = credential
        }
        val vault = ConfirmingVault()

        val outcome = DeviceCredentialInstaller(vault, handoff).install(receiptSample(), "challenge.android.1")

        val installed = outcome as DeviceCredentialInstaller.Outcome.Installed
        assertEquals(
            setOf(
                "challenge_id", "device_id", "binding_ref", "credential_generation", "proof_kind",
                "transcript_version", "local_store_confirmed", "proof_hex",
            ),
            installed.ack.keys,
        )
        assertEquals("protected_store_save_readback", installed.ack["proof_kind"])
        assertEquals(
            "1eb0cfe1d64f6d31b9aa6a9f5df2baeb8d00e33a360e908888ab4eb44481db97",
            installed.ack["proof_hex"],
        )
        assertFalse(Json.encode(installed.ack).contains(String(credential)))
        assertEquals(1L, installed.credentialGeneration)
    }

    @Test
    fun `a store that cannot confirm its own readback never claims installation`() {
        val credential = "c".repeat(32).toByteArray(Charsets.UTF_8)
        val handoff = object : CanonicalCredentialHandoff {
            override fun ready(challengeId: String, deviceId: String) = true
            override fun deliverOnce(challengeId: String, deviceId: String) = credential
        }

        val outcome = DeviceCredentialInstaller(ConfirmingVault(confirmReadback = false), handoff)
            .install(receiptSample(), "challenge.android.1")

        assertEquals(DeviceCredentialInstaller.Outcome.Blocked("protected_store_readback_failed"), outcome)
    }

    @Test
    fun `the declaration never carries a SAF uri and the handle is stable across restarts`() {
        val store = InMemoryLocalStateStore()
        val registry = SafRootRegistry(store)
        val treeUri = "content://com.android.externalstorage.documents/tree/primary%3ADocuments"

        val first = registry.replace(listOf(treeUri to "Documents"))
        val reloaded = SafRootRegistry(store)

        assertEquals(first.map { it.rootRef }.toSet(), reloaded.declaredRootRefs())
        assertTrue(AndroidConnectorContract.isOpaqueRef(first.first().rootRef))
        assertFalse(first.first().rootRef.contains("content:"))
        val wire = Json.encode(registry.declaration())
        assertFalse(wire.contains("content://"))
        assertFalse(wire.contains("primary"))
        assertFalse(wire.contains("%3A"))
    }

    @Test
    fun `a declaration is replaced atomically and two same-named folders stay separate`() {
        val registry = SafRootRegistry(InMemoryLocalStateStore())
        val before = registry.replace(listOf("content://tree/a" to "Documents")).first().rootRef

        val renamed = registry.replace(listOf("content://tree/a" to "Renamed Label"))
        val twins = registry.replace(
            listOf("content://tree/a" to "Documents", "content://tree/b" to "Documents"),
        )

        // The handle is a label, so renaming the folder is a new declaration, not a silent alias.
        assertEquals(listOf("safroot-renamed-label"), renamed.map { it.rootRef })
        assertEquals(2, twins.size)
        assertEquals(1, twins.count { it.rootRef == "safroot-documents" })
        assertFalse(before in twins.map { it.rootRef }.drop(1))
        assertEquals("content://tree/b", registry.treeUriOf(twins.last().rootRef))
    }

    @Test
    fun `declarable folder rules match the broker refusal rules`() {
        val registry = SafRootRegistry(InMemoryLocalStateStore())
        val valid = (1..8).map { "content://tree/$it" to "Folder $it" }
        assertEquals(8, registry.replace(valid).size)

        for (bad in listOf("  Padded  ", "Has/Slash", "Has\\Backslash", "Cont\u0001rol", "")) {
            try {
                registry.replace(listOf("content://tree/x" to bad))
                throw AssertionError("a display name the broker refuses must not be declarable: [$bad]")
            } catch (expected: IllegalArgumentException) {
                assertTrue(expected.message!!.isNotEmpty())
            }
        }
        try {
            registry.replace(valid + listOf("content://tree/9" to "Nine"))
            throw AssertionError("more than eight roots must be refused")
        } catch (expected: IllegalArgumentException) {
            assertTrue(expected.message!!.contains("8"))
        }
    }

    @Test
    fun `the device identity is minted once and survives a restart`() {
        val store = InMemoryLocalStateStore()
        val first = DeviceIdentityStore(store) { length -> "ab".repeat(length / 2) }
        val minted = first.deviceId()

        assertEquals(minted, DeviceIdentityStore(store) { length -> "cd".repeat(length / 2) }.deviceId())
        assertTrue(AndroidConnectorContract.isOpaqueRef(minted))
        assertTrue(first.newRequestRef().startsWith("andreq-"))
        assertTrue(first.newSessionId().startsWith("session.android."))
    }

    @Test
    fun `production transports refuse a cleartext or malformed endpoint and an unknown route`() {
        for (bad in listOf(
            "http://connector.example.test/",
            "https://user:pass@connector.example.test/",
            "https://connector.example.test/?token=abc",
            "not a url",
        )) {
            try {
                HttpsJsonClient(bad)
                throw AssertionError("endpoint must be refused: $bad")
            } catch (expected: DeviceProtocolException) {
                assertTrue(expected.message!!.isNotEmpty())
            }
        }

        try {
            HttpsDeviceTransport("https://connector.example.test/").post("/admin-rpc", "{}")
            throw AssertionError("a route outside the device set must be refused")
        } catch (expected: DeviceProtocolException) {
            assertTrue(expected.message!!.contains("unknown device route"))
        }
    }

    @Test
    fun `the contract path rule mirrors the server for every shape it refuses`() {
        for (accepted in listOf("notes/report.txt", "a.txt", "노트/한글 파일.txt", "A.TXT")) {
            assertTrue("$accepted must be accepted", AndroidConnectorContract.isRelativeReadPath(accepted))
        }
        for (refused in listOf(
            "", "notes/", "notes//a.txt", "./a.txt", "../a.txt", "notes/../x/a.txt",
            "/abs/a.txt", "C:/x/a.txt", "content://tree/a.txt", "notes/a.docx",
            "notes/a\u0001b.txt", "a".repeat(1024) + ".txt",
        )) {
            assertFalse("$refused must be refused", AndroidConnectorContract.isRelativeReadPath(refused))
        }
    }

    private fun receiptSample() = EnrollmentReceipt(
        bindingRef = "binding.android.1",
        deviceId = "device.android.1",
        accountRef = "account.android.1",
        workspaceRef = "workspace.android.1",
        consentId = "consent.android.1",
        credentialGeneration = 1L,
        credentialExpiresAt = "2099-01-01T00:00:00Z",
    )
}
