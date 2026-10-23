package com.padiem.connector.data

import java.io.FileNotFoundException
import java.io.IOException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Test

class SafErrorsTest {

    @Test
    fun listingSecurityExceptionMeansPermissionRevoked() {
        val failure = SafErrors.forListing(SecurityException("denied"))

        assertEquals(FailureKind.PERMISSION_REVOKED, failure.kind)
    }

    @Test
    fun readingSecurityExceptionMeansPermissionRevoked() {
        val failure = SafErrors.forReading(SecurityException("denied"))

        assertEquals(FailureKind.PERMISSION_REVOKED, failure.kind)
    }

    @Test
    fun listingFileNotFoundMeansFolderMissing() {
        val failure = SafErrors.forListing(FileNotFoundException("gone"))

        assertEquals(FailureKind.FOLDER_MISSING, failure.kind)
    }

    @Test
    fun readingFileNotFoundMeansFileMissing() {
        val failure = SafErrors.forReading(FileNotFoundException("gone"))

        assertEquals(FailureKind.FILE_MISSING, failure.kind)
    }

    @Test
    fun readingIOExceptionMeansReadFailed() {
        val failure = SafErrors.forReading(IOException("broken"))

        assertEquals(FailureKind.READ_FAILED, failure.kind)
    }

    @Test
    fun unexpectedListingErrorMeansReadFailed() {
        val failure = SafErrors.forListing(IllegalStateException("provider bug"))

        assertEquals(FailureKind.READ_FAILED, failure.kind)
    }

    @Test
    fun existingFailureIsPassedThrough() {
        val original = SafFailure(FailureKind.FILE_MISSING, "gone")

        val failure = SafErrors.forReading(original)

        assertSame(original, failure)
    }
}
