package com.padiem.connector.data

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.io.File
import java.security.KeyStore
import javax.crypto.Cipher
import java.security.SecureRandom
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * The platform secure store: an AndroidKeyStore AES-GCM key that is non-exportable and
 * user-presence-free, wrapping the device credential into a private app file.
 *
 * This is the store the #5163 checklist names ("store the device credential with the platform
 * secure store"); it is not a new credential authority — the Broker binding remains the only
 * thing that decides whether a device may act. A raw credential is never logged, never placed
 * in a declaration, and never returned to a browser-facing response.
 */
class KeystoreDeviceCredentialVault(context: Context) : DeviceCredentialVault {

    private val directory: File = context.noBackupFilesDir
    private val blob = File(directory, FILE_NAME)

    override fun saveAndConfirm(credential: ByteArray): Boolean {
        if (credential.isEmpty() || credential.size > MAX_CREDENTIAL_BYTES) return false
        return try {
            val temporary = File(directory, FILE_NAME + ".writing")
            temporary.writeBytes(encrypt(credential))
            val readback = decrypt(temporary.readBytes())
            val confirmed = readback != null && readback.contentEquals(credential)
            if (confirmed) {
                if (!temporary.renameTo(blob)) {
                    temporary.copyTo(blob, overwrite = true)
                    temporary.delete()
                }
                true
            } else {
                temporary.delete()
                false
            }
        } catch (error: Exception) {
            false
        }
    }

    override fun read(): ByteArray? {
        val stored = try {
            if (!blob.isFile) return null else blob.readBytes()
        } catch (error: Exception) {
            return null
        }
        return try {
            decrypt(stored)
        } catch (error: Exception) {
            null
        }
    }

    override fun clear(): Boolean {
        val keyCleared = try {
            val store = keyStore()
            if (store.isKeyEntry(KEY_ALIAS)) store.deleteEntry(KEY_ALIAS)
            true
        } catch (error: Exception) {
            false
        }
        return keyCleared && (!blob.exists() || blob.delete())
    }

    private fun encrypt(credential: ByteArray): ByteArray {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, wrappingKey())
        val iv = cipher.iv
        require(iv.size == IV_BYTES) { "unexpected GCM IV length" }
        return iv + cipher.doFinal(credential)
    }

    private fun decrypt(stored: ByteArray): ByteArray? {
        if (stored.size <= IV_BYTES) return null
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(
            Cipher.DECRYPT_MODE,
            existingKey ?: return null,
            GCMParameterSpec(TAG_BITS, stored.copyOfRange(0, IV_BYTES)),
        )
        return cipher.doFinal(stored, IV_BYTES, stored.size - IV_BYTES)
    }

    private fun wrappingKey(): SecretKey = existingKey ?: mintKey()

    private val existingKey: SecretKey?
        get() = try {
            keyStore().getKey(KEY_ALIAS, null) as? SecretKey
        } catch (error: Exception) {
            null
        }

    private fun mintKey(): SecretKey {
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE)
        generator.init(
            KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .setRandomizedEncryptionRequired(true)
                .build(),
        )
        return generator.generateKey()
    }

    private fun keyStore(): KeyStore = KeyStore.getInstance(KEYSTORE).apply { load(null) }

    private companion object {
        const val KEYSTORE = "AndroidKeyStore"
        const val KEY_ALIAS = "padiem-connector-device-credential"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val TAG_BITS = 128
        const val IV_BYTES = 12
        const val MAX_CREDENTIAL_BYTES = 4096
        const val FILE_NAME = "device-credential.bin"

        @Suppress("unused")
        val RANDOM = SecureRandom()
    }
}
