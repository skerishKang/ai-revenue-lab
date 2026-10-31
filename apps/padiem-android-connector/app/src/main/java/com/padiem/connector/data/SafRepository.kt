package com.padiem.connector.data

import android.content.ContentResolver
import android.content.Intent
import android.net.Uri
import android.provider.DocumentsContract
import android.provider.DocumentsContract.Document
import com.padiem.connector.core.FileRules
import com.padiem.connector.core.TextContent
import com.padiem.connector.core.TextContentLoader
import java.io.FileNotFoundException

class SafRepository(private val resolver: ContentResolver) {

    fun hasPersistedReadPermission(uri: Uri): Boolean {
        return try {
            resolver.persistedUriPermissions.any { it.uri == uri && it.isReadPermission }
        } catch (error: SecurityException) {
            false
        }
    }

    fun takePersistableReadPermission(uri: Uri) {
        resolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }

    fun releasePersistableReadPermission(uri: Uri) {
        try {
            resolver.releasePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
        } catch (error: SecurityException) {
            // The grant may already have been revoked by the system or the user.
        } catch (error: IllegalArgumentException) {
            // The provider no longer exists; there is nothing left to release.
        }
    }

    fun describeTree(treeUri: Uri): TreeDescription? {
        return try {
            val treeDocumentId = DocumentsContract.getTreeDocumentId(treeUri)
            val documentUri = DocumentsContract.buildDocumentUriUsingTree(treeUri, treeDocumentId)
            val displayName = resolver.query(
                documentUri,
                arrayOf(Document.COLUMN_DISPLAY_NAME),
                null,
                null,
                null,
            )?.use { cursor ->
                if (cursor.moveToFirst()) cursor.getString(0) else null
            }
            TreeDescription(displayName = displayName, pathHint = treeDocumentId)
        } catch (error: RuntimeException) {
            null
        }
    }

    fun listFiles(treeUri: Uri): DirectoryListing {
        try {
            val treeDocumentId = DocumentsContract.getTreeDocumentId(treeUri)
            val childrenUri = DocumentsContract.buildChildDocumentsUriUsingTree(treeUri, treeDocumentId)
            val cursor = resolver.query(childrenUri, PROJECTION, null, null, null)
                ?: throw FileNotFoundException("The document provider returned no listing.")

            val entries = ArrayList<DirectoryEntry>()
            var truncated = false

            cursor.use {
                val idIndex = it.getColumnIndexOrThrow(Document.COLUMN_DOCUMENT_ID)
                val nameIndex = it.getColumnIndexOrThrow(Document.COLUMN_DISPLAY_NAME)
                val mimeIndex = it.getColumnIndexOrThrow(Document.COLUMN_MIME_TYPE)
                val sizeIndex = it.getColumnIndexOrThrow(Document.COLUMN_SIZE)

                while (it.moveToNext()) {
                    if (entries.size >= MAX_LISTED_FILES) {
                        truncated = true
                        break
                    }

                    val mimeType = it.getString(mimeIndex) ?: ""
                    if (mimeType == Document.MIME_TYPE_DIR) continue

                    val documentId = it.getString(idIndex)
                    val displayName = it.getString(nameIndex) ?: documentId
                    val sizeBytes = if (it.isNull(sizeIndex)) null else it.getLong(sizeIndex)
                    val documentUri = DocumentsContract.buildDocumentUriUsingTree(treeUri, documentId)

                    entries += DirectoryEntry(
                        documentId = documentId,
                        displayName = displayName,
                        mimeType = mimeType,
                        sizeBytes = sizeBytes,
                        isTxt = FileRules.isTxtFile(displayName),
                        uri = documentUri,
                    )
                }
            }

            entries.sortWith(compareBy(String.CASE_INSENSITIVE_ORDER) { entry -> entry.displayName })
            return DirectoryListing(entries = entries, truncated = truncated)
        } catch (error: Exception) {
            throw SafErrors.forListing(error)
        }
    }

    fun readText(uri: Uri): TextContent {
        try {
            val stream = resolver.openInputStream(uri)
                ?: throw FileNotFoundException("The document provider returned no stream.")
            return stream.use { TextContentLoader.readUtf8(it) }
        } catch (error: Exception) {
            throw SafErrors.forReading(error)
        }
    }

    companion object {
        const val MAX_LISTED_FILES = 300
        private val PROJECTION = arrayOf(
            Document.COLUMN_DOCUMENT_ID,
            Document.COLUMN_DISPLAY_NAME,
            Document.COLUMN_MIME_TYPE,
            Document.COLUMN_SIZE,
        )
    }
}
