"""#7447: a pc_read of an image rides the ASCII envelope, not a decode refusal.

The executor used to refuse any non-UTF-8 body as ``read_failed``; a PNG
screenshot could never cross the lane. Now image bytes (png/jpeg/gif/webp, by
magic) travel as one ``PADIEM_IMAGE_CONTENT=<mime>:<base64>`` envelope the
engine parses, and any other binary refuses as ``binary_not_supported``.

Offline: a stub read port feeds the bytes; no MeshCentral, no queue, no
credential. unittest style: the lane's suite runs on unittest discovery.
"""
from __future__ import annotations

import base64
import unittest

from kagent.local_agent_oracle_mesh_executor import (
    OracleMeshDispatch,
    OracleMeshExecutor,
    PC_FILE_BINARY_NOT_SUPPORTED_MARKER,
    PC_IMAGE_ENVELOPE_PREFIX,
    _sniff_image_mime,
)

SECRET = "deployment-channel-secret-value-261017"
NODE = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
FILE_PATH = "C:\\Users\\sji\\cgi-work\\screenshot.png"

PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108020000009077"
    "53de0000000c4944415408d763f8cfc00000030101"
) + b"\x00\x00\x00\x00IEND\xaeB`\x82"


class _FixedPort:
    """Returns the one body every read asks for; records nothing else."""

    def __init__(self, body: bytes):
        self.body = body

    def read_bytes(self, *, node_ref, file_path, timeout_seconds=60, max_bytes=None):  # noqa: D102
        return self.body


def _read_outcome(body: bytes):
    executor = OracleMeshExecutor(
        chat_origin="https://chat.padiem.net", channel_secret=SECRET,
        read_port=_FixedPort(body), timeout_seconds=None,
    )
    return executor._execute_read(OracleMeshDispatch(
        dispatch_id="dsp-7447", nonce="n" * 32, node_ref=NODE,
        file_path=FILE_PATH, command_id="cmd-7447", run_id="run-7447",
    ))


class PcReadImageEnvelopeTests(unittest.TestCase):
    def test_an_image_read_returns_the_ascii_envelope(self):
        outcome = _read_outcome(PNG_BYTES)
        self.assertEqual(outcome.exit_code, 0)
        text = outcome.body.decode("utf-8")
        self.assertTrue(text.startswith(PC_IMAGE_ENVELOPE_PREFIX))
        head, _, encoded = text[len(PC_IMAGE_ENVELOPE_PREFIX):].partition(":")
        self.assertEqual(head, "image/png")
        self.assertEqual(base64.b64decode(encoded), PNG_BYTES)

    def test_a_non_image_binary_refuses_with_its_own_marker(self):
        outcome = _read_outcome(b"\xc3\x28\x00binary that is not utf-8")
        self.assertEqual(outcome.exit_code, 1)
        self.assertEqual(outcome.body, PC_FILE_BINARY_NOT_SUPPORTED_MARKER.encode("utf-8"))

    def test_a_text_read_keeps_its_utf8_body(self):
        outcome = _read_outcome("평범한 텍스트 파일".encode("utf-8"))
        self.assertEqual(outcome.exit_code, 0)
        self.assertEqual(outcome.body, "평범한 텍스트 파일".encode("utf-8"))


class ImageSniffTests(unittest.TestCase):
    def test_the_sniffer_names_only_declared_image_formats(self):
        self.assertEqual(_sniff_image_mime(PNG_BYTES), "image/png")
        self.assertEqual(_sniff_image_mime(b"\xff\xd8\xff\xe0rest"), "image/jpeg")
        self.assertEqual(_sniff_image_mime(b"GIF87a0101"), "image/gif")
        self.assertEqual(_sniff_image_mime(b"GIF89a0101"), "image/gif")
        webp = b"RIFF" + b"\x10\x00\x00\x00" + b"WEBP" + b"VP8 rest"
        self.assertEqual(_sniff_image_mime(webp), "image/webp")
        riff_without_webp = b"RIFF" + b"\x10\x00\x00\x00" + b"WAVE" + b"fmt rest"
        self.assertIsNone(_sniff_image_mime(riff_without_webp))
        self.assertIsNone(_sniff_image_mime(b"just text"))


if __name__ == "__main__":
    unittest.main()
