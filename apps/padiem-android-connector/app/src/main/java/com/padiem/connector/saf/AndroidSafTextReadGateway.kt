package com.padiem.connector.saf

import android.content.ContentResolver
import android.net.Uri
import android.provider.DocumentsContract
import android.provider.DocumentsContract.Document
import com.padiem.connector.contract.AndroidConnectorContract
import com.padiem.connector.core.TextContentLoader
import com.padiem.connector.data.SafRepository
import com.padiem.connector.data.SafRootRegistry

/**
 * Resolves one approved relative path inside one declared SAF tree and reads that document only.
 *
 * Each segment is looked up by exact display name with a selection bound on the provider side,
 * and a directory is never returned to the caller: the receipt names `directory_enumeration:
 * false`, and this class has no method that produces a listing. A path that would leave the
 * selected root is refused before any query runs, so a receipt cannot steer the app into a tree
 * the owner never approved. Read-permission and UTF-8 bounds reuse the existing SAF repository
 * and text loader rather than re-implementing either.
 */
class AndroidSafTextReadGateway(
    private val resolver: ContentResolver,
    private val repository: SafRepository,
    private val roots: SafRootRegistry,
) : SafTextReadGateway {

    override fun readText(rootRef: String, pathRelative: String, maxBytes: Int): ReadOutcome {
        if (!AndroidConnectorContract.isRelativeReadPath(pathRelative)) {
            throw SafReadFailed("path_invalid", "the approved path is not a relative TXT path")
        }
        val treeUriString = roots.treeUriOf(rootRef)
            ?: throw SafReadFailed("root_not_declared", "the receipt root was never declared by this phone")
        val treeUri = Uri.parse(treeUriString)
        if (!repository.hasPersistedReadPermission(treeUri)) {
            throw SafReadFailed("root_revoked", "SAF read permission for that root is no longer held")
        }

        val segments = pathRelative.split("/").filter { it.isNotEmpty() }
        val documentId = resolveDocumentId(treeUri, segments)
            ?: throw SafReadFailed("document_not_found", "the approved document is not present under that root")
        val documentUri = DocumentsContract.buildDocumentUriUsingTree(treeUri, documentId)
        val mime = queryColumn(documentUri, Document.COLUMN_MIME_TYPE)
        if (mime == Document.MIME_TYPE_DIR) {
            throw SafReadFailed("is_a_directory", "the approved path names a folder, not a document")
        }

        val stream = try {
            resolver.openInputStream(documentUri)
        } catch (error: Exception) {
            throw SafReadFailed("read_denied", "the document provider refused the read")
        } ?: throw SafReadFailed("read_denied", "the document provider returned no stream")

        return stream.use { input ->
            val content = TextContentLoader.readUtf8(input, maxBytes)
            val encoded = content.text.toByteArray(Charsets.UTF_8)
            val bounded = if (encoded.size <= maxBytes) {
                encoded
            } else {
                TextContentLoader.dropIncompleteTrailingCodePoint(encoded.copyOf(maxBytes))
            }
            // The body sent to the broker is re-encoded from exactly these bytes, so the
            // SHA-256 and content_bytes describe what travels rather than what was read.
            ReadOutcome(text = String(bounded, Charsets.UTF_8), bytes = bounded)
        }
    }

    private fun resolveDocumentId(treeUri: Uri, segments: List<String>): String? {
        var parentId = DocumentsContract.getTreeDocumentId(treeUri)
        for (index in segments.indices) {
            val leaf = index == segments.lastIndex
            val found = findChildId(treeUri, parentId, segments[index], requireDirectory = !leaf)
                ?: return null
            parentId = found
        }
        return parentId
    }

    private fun findChildId(treeUri: Uri, parentId: String, name: String, requireDirectory: Boolean): String? {
        val children = DocumentsContract.buildChildDocumentsUriUsingTree(treeUri, parentId)
        return try {
            resolver.query(
                children,
                arrayOf(Document.COLUMN_DOCUMENT_ID, Document.COLUMN_MIME_TYPE),
                "${Document.COLUMN_DISPLAY_NAME} = ?",
                arrayOf(name),
                null,
            )?.use { cursor ->
                val idIndex = cursor.getColumnIndex(Document.COLUMN_DOCUMENT_ID)
                val mimeIndex = cursor.getColumnIndex(Document.COLUMN_MIME_TYPE)
                if (idIndex < 0 || mimeIndex < 0) return@use null
                while (cursor.moveToNext()) {
                    val mime = cursor.getString(mimeIndex) ?: continue
                    val isDirectory = mime == Document.MIME_TYPE_DIR
                    if (isDirectory == requireDirectory) {
                        return@use cursor.getString(idIndex)
                    }
                }
                null
            }
        } catch (error: Exception) {
            null
        }
    }

    private fun queryColumn(uri: Uri, column: String): String? = try {
        resolver.query(uri, arrayOf(column), null, null, null)?.use { cursor ->
            val index = cursor.getColumnIndex(column)
            if (index < 0 || !cursor.moveToFirst()) null else cursor.getString(index)
        }
    } catch (error: Exception) {
        null
    }
}
