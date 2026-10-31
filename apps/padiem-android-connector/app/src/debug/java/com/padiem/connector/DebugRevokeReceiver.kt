package com.padiem.connector

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.util.Log
import com.padiem.connector.data.FolderSelectionStore
import com.padiem.connector.data.SafRepository

class DebugRevokeReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val saved = FolderSelectionStore(context).load() ?: return
        SafRepository(context.contentResolver)
            .releasePersistableReadPermission(Uri.parse(saved.uri))
        Log.i(TAG, "Released the saved persisted read grant for a revocation test.")
    }

    private companion object {
        const val TAG = "PadiemDebug"
    }
}
