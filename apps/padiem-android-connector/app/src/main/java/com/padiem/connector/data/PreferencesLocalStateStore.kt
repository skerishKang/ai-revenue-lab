package com.padiem.connector.data

import android.content.Context

/**
 * App-local device state in `no_backup` shared preferences: the stable device handle, the
 * declared SAF root set and the execution ledger. `allowBackup` is already false in the
 * manifest, and none of these blobs hold a credential or customer content.
 */
class PreferencesLocalStateStore(
    context: Context,
    private val key: String,
    fileName: String,
) : LocalStateStore {

    private val preferences = context.getSharedPreferences(fileName, Context.MODE_PRIVATE)

    override fun load(): String? = preferences.getString(key, null)

    override fun save(text: String) {
        preferences.edit().putString(key, text).apply()
    }

    override fun clear() {
        preferences.edit().remove(key).apply()
    }
}
