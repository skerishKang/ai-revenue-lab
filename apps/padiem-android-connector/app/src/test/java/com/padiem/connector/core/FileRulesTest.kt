package com.padiem.connector.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class FileRulesTest {

    @Test
    fun recognizesTxtExtensionCaseInsensitively() {
        assertTrue(FileRules.isTxtFile("notes.txt"))
        assertTrue(FileRules.isTxtFile("NOTES.TXT"))
        assertTrue(FileRules.isTxtFile("메모.Txt"))
        assertFalse(FileRules.isTxtFile("notes.txt.bak"))
        assertFalse(FileRules.isTxtFile("notes"))
        assertFalse(FileRules.isTxtFile("txt"))
    }

    @Test
    fun formatsByteSizes() {
        assertNull(FileRules.formatBytes(null))
        assertNull(FileRules.formatBytes(-1))
        assertEquals("0 B", FileRules.formatBytes(0))
        assertEquals("1023 B", FileRules.formatBytes(1023))
        assertEquals("1.0 KB", FileRules.formatBytes(1024))
        assertEquals("1.5 KB", FileRules.formatBytes(1536))
        assertEquals("10 MB", FileRules.formatBytes(10L * 1024 * 1024))
        assertEquals("1.0 GB", FileRules.formatBytes(1024L * 1024 * 1024))
    }
}
