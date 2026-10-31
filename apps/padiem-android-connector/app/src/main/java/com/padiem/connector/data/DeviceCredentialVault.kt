package com.padiem.connector.data

/**
 * Where the one device credential lives on the phone.
 *
 * `saveAndConfirm` is the platform-store readback the installation ack requires
 * (`protected_store_save_readback`): it returns the proof only when the value written to the
 * secure store is read back byte-identically. A `false` here is never upgraded to a success by
 * any caller.
 */
interface DeviceCredentialVault {
    fun saveAndConfirm(credential: ByteArray): Boolean
    fun read(): ByteArray?
    fun clear(): Boolean
}
