package com.padiem.connector.data

import android.content.Context

data class SavedFolder(
    val uri: String,
    val displayName: String?,
    val pathHint: String?,
    val selectedAtEpochMillis: Long,
)

class FolderSelectionStore(context: Context) {
    private val preferences = context.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)

    fun load(): SavedFolder? {
        val uri = preferences.getString(KEY_URI, null) ?: return null
        return SavedFolder(
            uri = uri,
            displayName = preferences.getString(KEY_DISPLAY_NAME, null),
            pathHint = preferences.getString(KEY_PATH_HINT, null),
            selectedAtEpochMillis = preferences.getLong(KEY_SELECTED_AT, 0L),
        )
    }

    fun save(folder: SavedFolder) {
        preferences.edit()
            .putString(KEY_URI, folder.uri)
            .putString(KEY_DISPLAY_NAME, folder.displayName)
            .putString(KEY_PATH_HINT, folder.pathHint)
            .putLong(KEY_SELECTED_AT, folder.selectedAtEpochMillis)
            .apply()
    }

    fun clear() {
        preferences.edit().clear().apply()
    }

    private companion object {
        const val PREFERENCES_NAME = "padiem_connector_selection"
        const val KEY_URI = "folder_tree_uri"
        const val KEY_DISPLAY_NAME = "folder_display_name"
        const val KEY_PATH_HINT = "folder_path_hint"
        const val KEY_SELECTED_AT = "folder_selected_at"
    }
}
