package com.padiem.connector

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.DocumentsContract
import android.view.View
import android.view.WindowInsets
import android.widget.Toast
import com.padiem.connector.core.FileRules
import com.padiem.connector.core.TextContent
import com.padiem.connector.core.TextContentLoader
import com.padiem.connector.data.DirectoryEntry
import com.padiem.connector.data.DirectoryListing
import com.padiem.connector.data.FailureKind
import com.padiem.connector.data.FolderSelectionStore
import com.padiem.connector.data.SafFailure
import com.padiem.connector.data.SafRepository
import com.padiem.connector.data.SavedFolder
import com.padiem.connector.databinding.ActivityMainBinding
import com.padiem.connector.databinding.ItemFileBinding
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

class MainActivity : Activity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var repository: SafRepository
    private lateinit var store: FolderSelectionStore
    private val executor: ExecutorService = Executors.newSingleThreadExecutor()
    private val mainHandler = Handler(Looper.getMainLooper())

    private var currentFolder: SavedFolder? = null
    private var folderLoadGeneration = 0
    private var previewLoadGeneration = 0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        repository = SafRepository(contentResolver)
        store = FolderSelectionStore(this)

        applyEdgeToEdgeInsets()
        bindActions()
        renderEmptyState()
        restoreSavedFolder()
    }

    override fun onResume() {
        super.onResume()
        val saved = currentFolder ?: return
        val uri = parseUri(saved.uri) ?: return
        if (!repository.hasPersistedReadPermission(uri)) {
            renderPermissionRevoked(saved, resetPreview = true)
        }
    }

    override fun onDestroy() {
        folderLoadGeneration++
        previewLoadGeneration++
        mainHandler.removeCallbacksAndMessages(null)
        executor.shutdownNow()
        super.onDestroy()
    }

    @Suppress("DEPRECATION")
    private fun applyEdgeToEdgeInsets() {
        val basePadding = dp(20)
        binding.content.setPadding(basePadding, basePadding, basePadding, basePadding)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            window.setDecorFitsSystemWindows(false)
            binding.root.setOnApplyWindowInsetsListener { _, insets ->
                val bars = insets.getInsets(
                    WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout(),
                )
                binding.content.setPadding(
                    basePadding + bars.left,
                    basePadding + bars.top,
                    basePadding + bars.right,
                    basePadding + bars.bottom,
                )
                insets
            }
            binding.root.requestApplyInsets()
        }
    }

    private fun bindActions() {
        binding.selectFolderButton.setOnClickListener { openFolderPicker() }
        binding.clearFolderButton.setOnClickListener { clearFolderSelection() }
        binding.refreshButton.setOnClickListener { refreshFolder() }
    }

    private fun restoreSavedFolder() {
        val saved = store.load() ?: return
        val uri = parseUri(saved.uri)
        if (uri == null) {
            store.clear()
            return
        }

        currentFolder = saved
        renderFolderLabel(saved)
        binding.clearFolderButton.isEnabled = true

        if (!repository.hasPersistedReadPermission(uri)) {
            renderPermissionRevoked(saved, resetPreview = true)
            return
        }

        markPermissionAvailable()
        loadFolder(saved)
    }

    @Suppress("DEPRECATION")
    private fun openFolderPicker() {
        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).apply {
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            val currentUri = currentFolder?.uri?.let(::parseUri)
            if (currentUri != null && repository.hasPersistedReadPermission(currentUri)) {
                putExtra(DocumentsContract.EXTRA_INITIAL_URI, currentUri)
            }
        }

        try {
            startActivityForResult(intent, REQUEST_OPEN_TREE)
        } catch (error: ActivityNotFoundException) {
            showFolderError(getString(R.string.error_picker_unavailable))
        }
    }

    @Suppress("DEPRECATION")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != REQUEST_OPEN_TREE) return

        if (resultCode != RESULT_OK) {
            toast(getString(R.string.toast_selection_cancelled))
            return
        }

        val uri = data?.data
        if (uri == null || !DocumentsContract.isTreeUri(uri)) {
            showFolderError(getString(R.string.error_picker_unavailable))
            return
        }

        try {
            repository.takePersistableReadPermission(uri)
        } catch (error: SecurityException) {
            showFolderError(getString(R.string.error_persist_permission))
            return
        } catch (error: IllegalArgumentException) {
            showFolderError(getString(R.string.error_persist_permission))
            return
        }

        val previousFolder = currentFolder
        val description = repository.describeTree(uri)
        val saved = SavedFolder(
            uri = uri.toString(),
            displayName = description?.displayName,
            pathHint = description?.pathHint,
            selectedAtEpochMillis = System.currentTimeMillis(),
        )

        folderLoadGeneration++
        previewLoadGeneration++
        store.save(saved)
        currentFolder = saved
        renderFolderLabel(saved)
        binding.clearFolderButton.isEnabled = true
        binding.folderError.visibility = View.GONE
        markPermissionAvailable()
        resetPreview()

        if (previousFolder != null && previousFolder.uri != saved.uri) {
            parseUri(previousFolder.uri)?.let(repository::releasePersistableReadPermission)
        }

        loadFolder(saved)
    }

    private fun clearFolderSelection() {
        val saved = currentFolder
        folderLoadGeneration++
        previewLoadGeneration++
        currentFolder = null
        saved?.uri?.let(::parseUri)?.let(repository::releasePersistableReadPermission)
        store.clear()
        renderEmptyState()
        toast(getString(R.string.toast_selection_cleared))
        binding.scrollView.post {
            if (!isDestroyed) binding.scrollView.smoothScrollTo(0, 0)
        }
    }

    private fun refreshFolder() {
        val saved = currentFolder
        if (saved == null) {
            toast(getString(R.string.toast_no_folder))
            return
        }

        val uri = parseUri(saved.uri)
        if (uri == null || !repository.hasPersistedReadPermission(uri)) {
            renderPermissionRevoked(saved, resetPreview = true)
            return
        }

        markPermissionAvailable()
        loadFolder(saved)
    }

    private fun loadFolder(saved: SavedFolder) {
        val uri = parseUri(saved.uri)
        if (uri == null) {
            renderFolderFailure(FailureKind.FOLDER_MISSING)
            return
        }

        val generation = ++folderLoadGeneration
        binding.folderProgress.visibility = View.VISIBLE
        binding.folderError.visibility = View.GONE
        binding.refreshButton.isEnabled = false
        binding.filesEmpty.visibility = View.VISIBLE
        binding.filesEmpty.text = getString(R.string.folder_loading)
        binding.fileListContainer.removeAllViews()
        binding.fileCount.visibility = View.GONE
        binding.filesNote.visibility = View.GONE

        executor.execute {
            try {
                val listing = repository.listFiles(uri)
                mainHandler.post {
                    if (isDestroyed || generation != folderLoadGeneration) return@post
                    renderFolderLoaded(listing)
                }
            } catch (failure: SafFailure) {
                mainHandler.post {
                    if (isDestroyed || generation != folderLoadGeneration) return@post
                    renderFolderFailure(failure.kind)
                }
            }
        }
    }

    private fun renderFolderLoaded(listing: DirectoryListing) {
        binding.folderProgress.visibility = View.GONE
        binding.folderError.visibility = View.GONE
        markPermissionAvailable()
        binding.refreshButton.isEnabled = true
        binding.clearFolderButton.isEnabled = true
        binding.fileCount.visibility = View.VISIBLE
        binding.fileCount.text = getString(R.string.files_count, listing.entries.size)

        binding.fileListContainer.removeAllViews()
        if (listing.entries.isEmpty()) {
            binding.filesEmpty.visibility = View.VISIBLE
            binding.filesEmpty.text = getString(R.string.files_empty)
        } else {
            binding.filesEmpty.visibility = View.GONE
            listing.entries.forEach(::addFileRow)
        }

        val notes = buildList {
            if (listing.truncated) {
                add(getString(R.string.files_too_many, SafRepository.MAX_LISTED_FILES))
            }
            if (listing.entries.isNotEmpty()) {
                add(getString(R.string.files_subfolders_note))
            }
        }
        if (notes.isEmpty()) {
            binding.filesNote.visibility = View.GONE
        } else {
            binding.filesNote.text = notes.joinToString("\n")
            binding.filesNote.visibility = View.VISIBLE
        }
    }

    private fun renderFolderFailure(kind: FailureKind) {
        binding.fileListContainer.removeAllViews()
        binding.fileCount.visibility = View.GONE
        binding.filesEmpty.visibility = View.GONE
        binding.filesNote.visibility = View.GONE
        resetPreview()

        when (kind) {
            FailureKind.PERMISSION_REVOKED -> {
                renderPermissionRevoked(currentFolder, resetPreview = false)
            }

            FailureKind.FOLDER_MISSING -> {
                binding.folderProgress.visibility = View.GONE
                binding.refreshButton.isEnabled = true
                binding.clearFolderButton.isEnabled = true
                showFolderError(getString(R.string.error_folder_missing))
            }

            else -> {
                binding.folderProgress.visibility = View.GONE
                binding.refreshButton.isEnabled = true
                binding.clearFolderButton.isEnabled = true
                showFolderError(getString(R.string.error_folder_read_failed))
            }
        }
    }

    private fun renderPermissionRevoked(saved: SavedFolder?, resetPreview: Boolean) {
        folderLoadGeneration++
        binding.folderProgress.visibility = View.GONE
        binding.folderPermission.text = getString(R.string.folder_permission_revoked)
        binding.folderPermission.setTextColor(color(R.color.red))
        binding.folderPermission.setBackgroundResource(R.drawable.bg_badge_red)
        binding.folderPermission.setPadding(dp(8), dp(4), dp(8), dp(4))
        binding.refreshButton.isEnabled = false
        binding.clearFolderButton.isEnabled = saved != null || currentFolder != null
        binding.fileListContainer.removeAllViews()
        binding.fileCount.visibility = View.GONE
        binding.filesEmpty.visibility = View.GONE
        binding.filesNote.visibility = View.GONE
        showFolderError(getString(R.string.error_permission_revoked))
        if (resetPreview) resetPreview()
    }

    private fun markPermissionAvailable() {
        binding.folderPermission.text = getString(R.string.folder_permission_available)
        binding.folderPermission.setTextColor(color(R.color.green))
        binding.folderPermission.setBackgroundResource(R.drawable.bg_badge_green)
        binding.folderPermission.setPadding(dp(8), dp(4), dp(8), dp(4))
    }

    private fun addFileRow(entry: DirectoryEntry) {
        val row = ItemFileBinding.inflate(layoutInflater, binding.fileListContainer, false)
        val sizeText = FileRules.formatBytes(entry.sizeBytes) ?: getString(R.string.size_unknown)
        val kindText = getString(if (entry.isTxt) R.string.badge_txt else R.string.badge_other)

        row.fileName.text = entry.displayName
        row.fileMeta.text = getString(R.string.file_meta, sizeText, kindText)
        row.fileBadge.text = kindText
        if (entry.isTxt) {
            row.fileBadge.setBackgroundResource(R.drawable.bg_badge_txt)
            row.fileBadge.setTextColor(color(R.color.accent))
        } else {
            row.fileBadge.setBackgroundResource(R.drawable.bg_badge_other)
            row.fileBadge.setTextColor(color(R.color.text_secondary))
        }
        row.root.setOnClickListener { onFileSelected(entry) }
        binding.fileListContainer.addView(row.root)
    }

    private fun onFileSelected(entry: DirectoryEntry) {
        if (!entry.isTxt) {
            previewLoadGeneration++
            binding.previewMeta.text = entry.displayName
            showPreviewMessage(getString(R.string.preview_not_txt), isError = false)
            return
        }

        val folderUri = currentFolder?.uri?.let(::parseUri)
        if (folderUri != null && !repository.hasPersistedReadPermission(folderUri)) {
            renderPermissionRevoked(currentFolder, resetPreview = false)
            previewLoadGeneration++
            binding.previewMeta.text = entry.displayName
            showPreviewMessage(getString(R.string.error_preview_permission), isError = true)
            return
        }

        val generation = ++previewLoadGeneration
        binding.previewMeta.text = getString(R.string.preview_loading, entry.displayName)
        binding.previewBody.text = ""
        binding.previewBody.setTextColor(color(R.color.text_secondary))
        binding.previewNote.visibility = View.GONE

        executor.execute {
            try {
                val content = repository.readText(entry.uri)
                mainHandler.post {
                    if (isDestroyed || generation != previewLoadGeneration) return@post
                    renderText(entry, content)
                }
            } catch (failure: SafFailure) {
                mainHandler.post {
                    if (isDestroyed || generation != previewLoadGeneration) return@post
                    renderFileFailure(entry, failure.kind)
                }
            }
        }
    }

    private fun renderText(entry: DirectoryEntry, content: TextContent) {
        val sizeText = FileRules.formatBytes(entry.sizeBytes) ?: getString(R.string.size_unknown)
        binding.previewMeta.text = getString(R.string.preview_meta, entry.displayName, sizeText)
        binding.previewBody.setTextColor(color(R.color.text_primary))
        binding.previewBody.text = if (content.text.isEmpty()) {
            getString(R.string.preview_empty)
        } else {
            content.text
        }

        if (content.truncated) {
            val limitText = FileRules.formatBytes(TextContentLoader.DEFAULT_MAX_BYTES.toLong())
                ?: TextContentLoader.DEFAULT_MAX_BYTES.toString()
            binding.previewNote.text = getString(R.string.preview_truncated, limitText)
            binding.previewNote.visibility = View.VISIBLE
        } else {
            binding.previewNote.visibility = View.GONE
        }
        scrollToPreview()
    }

    private fun renderFileFailure(entry: DirectoryEntry, kind: FailureKind) {
        binding.previewMeta.text = entry.displayName
        when (kind) {
            FailureKind.PERMISSION_REVOKED -> {
                renderPermissionRevoked(currentFolder, resetPreview = false)
                showPreviewMessage(getString(R.string.error_preview_permission), isError = true)
            }

            FailureKind.FILE_MISSING -> {
                showPreviewMessage(getString(R.string.error_preview_file_missing), isError = true)
            }

            else -> {
                showPreviewMessage(getString(R.string.error_preview_read_failed), isError = true)
            }
        }
    }

    private fun showPreviewMessage(message: String, isError: Boolean) {
        binding.previewBody.setTextColor(color(if (isError) R.color.red else R.color.text_secondary))
        binding.previewBody.text = message
        binding.previewNote.visibility = View.GONE
        scrollToPreview()
    }

    private fun scrollToPreview() {
        binding.previewCard.post {
            if (!isDestroyed) {
                binding.scrollView.smoothScrollTo(0, binding.previewCard.top)
            }
        }
    }

    private fun renderEmptyState() {
        currentFolder = null
        binding.folderName.text = getString(R.string.folder_none_title)
        binding.folderPath.text = getString(R.string.folder_none_hint)
        binding.folderPath.visibility = View.VISIBLE
        binding.folderPermission.text = ""
        binding.folderPermission.setBackgroundResource(0)
        binding.folderPermission.setPadding(0, 0, 0, 0)
        binding.folderError.visibility = View.GONE
        binding.folderProgress.visibility = View.GONE
        binding.selectFolderButton.isEnabled = true
        binding.clearFolderButton.isEnabled = false
        binding.refreshButton.isEnabled = false
        binding.fileCount.visibility = View.GONE
        binding.filesNote.visibility = View.GONE
        binding.filesEmpty.visibility = View.VISIBLE
        binding.filesEmpty.text = getString(R.string.files_initial)
        binding.fileListContainer.removeAllViews()
        resetPreview()
    }

    private fun renderFolderLabel(saved: SavedFolder) {
        binding.folderName.text = saved.displayName ?: getString(R.string.folder_name_fallback)
        if (saved.pathHint == null) {
            binding.folderPath.visibility = View.GONE
        } else {
            binding.folderPath.visibility = View.VISIBLE
            binding.folderPath.text = getString(R.string.folder_path_label, saved.pathHint)
        }
    }

    private fun resetPreview() {
        previewLoadGeneration++
        binding.previewMeta.text = getString(R.string.preview_none)
        binding.previewBody.text = ""
        binding.previewBody.setTextColor(color(R.color.text_secondary))
        binding.previewNote.visibility = View.GONE
    }

    private fun showFolderError(message: String) {
        binding.folderError.text = message
        binding.folderError.visibility = View.VISIBLE
    }

    private fun parseUri(value: String): Uri? {
        return runCatching { Uri.parse(value) }.getOrNull()?.takeIf { it.scheme != null }
    }

    private fun color(resourceId: Int): Int = resources.getColor(resourceId, theme)

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    private fun toast(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show()
    }

    private companion object {
        const val REQUEST_OPEN_TREE = 5080
    }
}
