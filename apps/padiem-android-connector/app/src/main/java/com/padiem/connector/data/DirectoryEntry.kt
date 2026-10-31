package com.padiem.connector.data

import android.net.Uri

data class DirectoryEntry(
    val documentId: String,
    val displayName: String,
    val mimeType: String,
    val sizeBytes: Long?,
    val isTxt: Boolean,
    val uri: Uri,
)

data class DirectoryListing(
    val entries: List<DirectoryEntry>,
    val truncated: Boolean,
)

data class TreeDescription(
    val displayName: String?,
    val pathHint: String?,
)
