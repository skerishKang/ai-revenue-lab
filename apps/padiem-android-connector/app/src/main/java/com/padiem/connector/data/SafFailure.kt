package com.padiem.connector.data

import java.io.FileNotFoundException
import java.io.IOException

enum class FailureKind {
    PERMISSION_REVOKED,
    FOLDER_MISSING,
    FILE_MISSING,
    READ_FAILED,
}

class SafFailure(
    val kind: FailureKind,
    val detail: String? = null,
    cause: Throwable? = null,
) : Exception(detail, cause)

object SafErrors {
    fun forListing(error: Throwable): SafFailure {
        if (error is SafFailure) return error
        return when (error) {
            is SecurityException -> SafFailure(FailureKind.PERMISSION_REVOKED, error.message, error)
            is FileNotFoundException -> SafFailure(FailureKind.FOLDER_MISSING, error.message, error)
            is IllegalArgumentException -> SafFailure(FailureKind.FOLDER_MISSING, error.message, error)
            is IOException -> SafFailure(FailureKind.READ_FAILED, error.message, error)
            else -> SafFailure(FailureKind.READ_FAILED, error.message, error)
        }
    }

    fun forReading(error: Throwable): SafFailure {
        if (error is SafFailure) return error
        return when (error) {
            is SecurityException -> SafFailure(FailureKind.PERMISSION_REVOKED, error.message, error)
            is FileNotFoundException -> SafFailure(FailureKind.FILE_MISSING, error.message, error)
            is IllegalArgumentException -> SafFailure(FailureKind.FILE_MISSING, error.message, error)
            is IOException -> SafFailure(FailureKind.READ_FAILED, error.message, error)
            else -> SafFailure(FailureKind.READ_FAILED, error.message, error)
        }
    }
}
