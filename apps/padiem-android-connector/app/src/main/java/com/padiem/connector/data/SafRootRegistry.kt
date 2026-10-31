package com.padiem.connector.data

import com.padiem.connector.contract.AndroidConnectorContract
import com.padiem.connector.contract.Json
import java.security.MessageDigest

/** One SAF tree the owner selected, addressed by the opaque handle the server sees. */
data class SafRoot(
    val rootRef: String,
    val treeUri: String,
    val displayName: String,
)

/**
 * The phone's own SAF root registry.
 *
 * A `root_ref` is minted here from the tree URI and is the only thing that ever leaves the
 * device: `content://` URIs, tree document IDs and filesystem paths stay local, which is the
 * rule #5163 §4 states for the declaration and §1 repeats for the whole lane. Re-selecting the
 * same folder yields the same handle, so a redeployed app does not silently re-name a grant the
 * owner already confirmed.
 */
class SafRootRegistry(private val persistor: LocalStateStore) {

    private val roots: MutableList<SafRoot> = mutableListOf()

    init {
        reload()
    }

    fun replace(treeUriToDisplayName: List<Pair<String, String>>): List<SafRoot> {
        val declared = ArrayList<SafRoot>(treeUriToDisplayName.size)
        for ((treeUri, displayName) in treeUriToDisplayName) {
            require(displayNameIsValid(displayName)) { "folder display name is not declarable" }
            require(treeUri.isNotEmpty()) { "tree uri is required" }
            if (declared.any { it.treeUri == treeUri && it.displayName == displayName }) continue
            declared += SafRoot(handleFor(treeUri, displayName, declared.map { it.rootRef }.toSet()), treeUri, displayName)
        }
        require(declared.size <= AndroidConnectorContract.MAX_DECLARED_FOLDERS) {
            "at most ${AndroidConnectorContract.MAX_DECLARED_FOLDERS} folders may be declared"
        }
        roots.clear()
        roots += declared
        persist()
        return declared.toList()
    }

    /** The truthful "owner withdrew SAF access" state: an empty declaration replaces the set. */
    fun withdrawAll() {
        roots.clear()
        persistor.clear()
    }

    fun treeUriOf(rootRef: String): String? = roots.firstOrNull { it.rootRef == rootRef }?.treeUri

    fun declaredRootRefs(): Set<String> = roots.map { it.rootRef }.toSet()

    /** Exactly the closed `{root_ref, display_name}` shape the broker accepts. */
    fun declaration(): List<Map<String, Any?>> = roots.map { root ->
        linkedMapOf<String, Any?>("root_ref" to root.rootRef, "display_name" to root.displayName)
    }

    private fun reload() {
        val stored = persistor.load() ?: return
        val rows = Json.parse(stored) as? List<*> ?: return
        roots.clear()
        for (row in rows) {
            val fields = row as? Map<*, *> ?: continue
            val rootRef = fields["root_ref"] as? String ?: continue
            val treeUri = fields["tree_uri"] as? String ?: continue
            val displayName = fields["display_name"] as? String ?: continue
            if (AndroidConnectorContract.isOpaqueRef(rootRef) && displayNameIsValid(displayName)) {
                roots += SafRoot(rootRef, treeUri, displayName)
            }
        }
    }

    private fun persist() {
        Json.encode(roots.map { root ->
            linkedMapOf<String, Any?>(
                "root_ref" to root.rootRef,
                "tree_uri" to root.treeUri,
                "display_name" to root.displayName,
            )
        }).let(persistor::save)
    }

    private fun handleFor(treeUri: String, displayName: String, taken: Set<String>): String {
        // A readable, opaque handle ("safroot-documents") is what the contract declares; the tree
        // URI never leaves the phone, and appears only as a hash suffix when two grants would
        // otherwise share one handle.
        val slug = displayName.lowercase()
            .map { if (it.code < 128 && it.isLetterOrDigit()) it else ' ' }
            .joinToString("")
            .split(' ')
            .filter { it.isNotEmpty() }
            .joinToString("-")
            .take(40)
        val prefix = if (slug.isEmpty()) "safroot" else "safroot-$slug"
        if (slug.isNotEmpty() && prefix !in taken) return prefix
        return "$prefix-" + sha256Hex(treeUri).substring(0, 12)
    }

    private fun sha256Hex(text: String): String =
        MessageDigest.getInstance("SHA-256").digest(text.toByteArray(Charsets.UTF_8))
            .joinToString("") { byte -> ((byte.toInt() and 0xFF) + 256).toString(16).substring(1) }

    private fun displayNameIsValid(value: String): Boolean =
        value.length in 1..AndroidConnectorContract.MAX_FOLDER_DISPLAY_NAME &&
            value.none { it.code < 32 || it.code == 127 } &&
            !value.contains('/') && !value.contains('\\') &&
            value == value.trim()
}
