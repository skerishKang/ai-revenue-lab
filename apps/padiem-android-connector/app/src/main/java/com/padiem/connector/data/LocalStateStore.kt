package com.padiem.connector.data

/** One small app-local text blob. Device state only — no credential, no customer content. */
interface LocalStateStore {
    fun load(): String?
    fun save(text: String)
    fun clear()
}
