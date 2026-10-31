package com.padiem.connector.core

import java.io.ByteArrayInputStream
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TextContentLoaderTest {

    @Test
    fun readsKoreanUtf8Text() {
        val source = "안녕하세요\nPADIEM Connector".toByteArray(Charsets.UTF_8)

        val content = TextContentLoader.readUtf8(ByteArrayInputStream(source))

        assertEquals("안녕하세요\nPADIEM Connector", content.text)
        assertEquals(source.size, content.byteCount)
        assertFalse(content.truncated)
    }

    @Test
    fun stripsUtf8Bom() {
        val bom = byteArrayOf(0xEF.toByte(), 0xBB.toByte(), 0xBF.toByte())
        val source = bom + "TXT".toByteArray(Charsets.UTF_8)

        val content = TextContentLoader.readUtf8(ByteArrayInputStream(source))

        assertEquals("TXT", content.text)
        assertFalse(content.text.startsWith("\uFEFF"))
    }

    @Test
    fun reportsTruncationAndDropsPartialTrailingCharacter() {
        val source = "가".repeat(10).toByteArray(Charsets.UTF_8)

        val content = TextContentLoader.readUtf8(ByteArrayInputStream(source), maxBytes = 4)

        assertTrue(content.truncated)
        assertEquals("가", content.text)
        assertEquals(3, content.byteCount)
        assertFalse(content.text.contains('\uFFFD'))
    }

    @Test
    fun dropsACharacterSplitAcrossTwoBytes() {
        val source = "가".toByteArray(Charsets.UTF_8)

        val content = TextContentLoader.readUtf8(ByteArrayInputStream(source), maxBytes = 2)

        assertTrue(content.truncated)
        assertEquals("", content.text)
        assertEquals(0, content.byteCount)
    }

    @Test
    fun exactByteLimitIsNotTruncated() {
        val source = "abcd".toByteArray(Charsets.UTF_8)

        val content = TextContentLoader.readUtf8(ByteArrayInputStream(source), maxBytes = 4)

        assertFalse(content.truncated)
        assertEquals("abcd", content.text)
    }

    @Test
    fun extraBytesAreReportedAsTruncated() {
        val source = "abcde".toByteArray(Charsets.UTF_8)

        val content = TextContentLoader.readUtf8(ByteArrayInputStream(source), maxBytes = 4)

        assertTrue(content.truncated)
        assertEquals("abcd", content.text)
    }

    @Test
    fun emptyStreamProducesEmptyText() {
        val content = TextContentLoader.readUtf8(ByteArrayInputStream(byteArrayOf()))

        assertEquals("", content.text)
        assertEquals(0, content.byteCount)
        assertFalse(content.truncated)
    }

    @Test
    fun invalidUtf8IsReplacedInsteadOfFailing() {
        val content = TextContentLoader.readUtf8(
            ByteArrayInputStream(byteArrayOf(0x41, 0xFF.toByte(), 0x42)),
        )

        assertEquals("A\uFFFDB", content.text)
    }

    @Test
    fun completeMultibyteTailIsKept() {
        val source = "가나".toByteArray(Charsets.UTF_8)

        val trimmed = TextContentLoader.dropIncompleteTrailingCodePoint(source)

        assertEquals(source.size, trimmed.size)
    }
}
