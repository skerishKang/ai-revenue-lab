"""Server-side STT transport contract (Groq Whisper + Gemini Live token).

Ported from ``netlify/functions/transcribe.mts`` (Groq) and the
``/api/live-token`` contract in ``hooks/useInterviewLive.ts`` (Gemini Live),
minus the Netlify runtime. Every rule here is pure and testable without the
Cloudflare Workers runtime.
"""

from __future__ import annotations

import base64
import datetime
import re

import pytest

import voice_stt_contract as c


def _data_url(mime: str, payload: bytes) -> str:
    return f"data:{mime};base64," + base64.b64encode(payload).decode("ascii")


def test_audio_ceiling_matches_global_classroom():
    assert c.MAX_AUDIO_BYTES == 3 * 1024 * 1024


def test_parse_audio_data_url_decodes_and_maps_extension():
    webm = c.parse_audio_data_url(_data_url("audio/webm;codecs=opus", b"\x00\x01\x02"))
    assert webm is not None and webm.mime_type == "audio/webm" and webm.extension == "webm"
    assert webm.data == b"\x00\x01\x02"

    m4a = c.parse_audio_data_url(_data_url("audio/mp4", b"abcd"))
    assert m4a is not None and m4a.extension == "m4a"

    wav = c.parse_audio_data_url(_data_url("audio/wav", b"abcd"))
    assert wav is not None and wav.extension == "wav"

    mp3 = c.parse_audio_data_url(_data_url("audio/mpeg", b"abcd"))
    assert mp3 is not None and mp3.extension == "mp3"


def test_parse_audio_data_url_rejects_bad_input():
    assert c.parse_audio_data_url(None) is None
    assert c.parse_audio_data_url(1234) is None
    assert c.parse_audio_data_url("https://example.test/audio.webm") is None
    assert c.parse_audio_data_url("data:audio/webm,notbase64") is None
    assert c.parse_audio_data_url(_data_url("image/png", b"abcd")) is None
    assert c.parse_audio_data_url(_data_url("audio/webm", b"")) is None
    # Invalid base64 payload.
    assert c.parse_audio_data_url("data:audio/webm;base64,@@@not-base64@@@") is None


def test_normalize_language():
    assert c.normalize_language(None) == "auto"
    assert c.normalize_language("") == "auto"
    assert c.normalize_language("ko") == "ko"
    assert c.normalize_language("EN") == "en"
    assert c.normalize_language("auto") == "auto"
    assert c.normalize_language("fr") is None
    assert c.normalize_language(5) is None


def test_validate_transcribe_request_happy_path():
    language, audio = c.validate_transcribe_request(
        {"audioDataUrl": _data_url("audio/webm", b"voice"), "language": "en", "utteranceId": "s:0:0"}
    )
    assert language == "en"
    assert audio.size == 5


def test_validate_transcribe_request_rejects_unknown_field():
    with pytest.raises(c.VoiceSttError) as exc:
        c.validate_transcribe_request(
            {"audioDataUrl": _data_url("audio/webm", b"voice"), "url": "https://evil.test"}
        )
    assert exc.value.code == "unsupported_field"


def test_validate_transcribe_request_rejects_bad_language_audio_and_size():
    with pytest.raises(c.VoiceSttError) as bad_lang:
        c.validate_transcribe_request({"audioDataUrl": _data_url("audio/webm", b"x"), "language": "fr"})
    assert bad_lang.value.code == "invalid_language"

    with pytest.raises(c.VoiceSttError) as bad_audio:
        c.validate_transcribe_request({"audioDataUrl": "nope", "language": "ko"})
    assert bad_audio.value.code == "invalid_audio"

    with pytest.raises(c.VoiceSttError) as too_big:
        c.validate_transcribe_request(
            {"audioDataUrl": _data_url("audio/webm", b"x" * (c.MAX_AUDIO_BYTES + 1))}
        )
    assert too_big.value.code == "audio_too_large"

    with pytest.raises(c.VoiceSttError) as not_json:
        c.validate_transcribe_request(["not", "a", "dict"])
    assert not_json.value.code == "invalid_json"


def test_groq_model_sequence_is_turbo_then_full():
    assert c.groq_model_sequence() == ("whisper-large-v3-turbo", "whisper-large-v3")
    assert c.GROQ_STT_ENDPOINT == "https://api.groq.com/openai/v1/audio/transcriptions"
    assert c.GROQ_STT_ALLOWED_HOST == "api.groq.com"


def test_multipart_body_carries_audio_model_and_language():
    audio = c.parse_audio_data_url(_data_url("audio/webm", b"\x00\x01\x02"))
    assert audio is not None
    content_type, body = c.build_groq_multipart_body("whisper-large-v3-turbo", audio, "ko", "BOUNDARY")
    assert content_type == "multipart/form-data; boundary=BOUNDARY"
    assert b'name="file"; filename="padiem-voice.webm"' in body
    assert b"Content-Type: audio/webm" in body
    assert b'name="model"' in body and b"whisper-large-v3-turbo" in body
    assert b'name="language"' in body and b"\r\nko\r\n" in body
    assert b'name="response_format"' in body and b"json" in body
    assert b'name="temperature"' in body and b"\r\n0\r\n" in body
    assert body.startswith(b"--BOUNDARY\r\n") and body.endswith(b"--BOUNDARY--\r\n")


def test_multipart_body_omits_language_when_auto():
    audio = c.parse_audio_data_url(_data_url("audio/webm", b"x"))
    assert audio is not None
    _ct, body = c.build_groq_multipart_body("whisper-large-v3", audio, "auto", "B")
    assert b'name="language"' not in body


def test_multipart_body_rejects_unregistered_model_and_language():
    audio = c.parse_audio_data_url(_data_url("audio/webm", b"x"))
    assert audio is not None
    with pytest.raises(ValueError):
        c.build_groq_multipart_body("whisper-tiny", audio, "ko", "B")
    with pytest.raises(ValueError):
        c.build_groq_multipart_body("whisper-large-v3", audio, "fr", "B")


def test_groq_response_parsing():
    assert c.parse_groq_transcription_response(200, {"text": "  안녕하세요 "}) == (True, "안녕하세요", "")
    assert c.parse_groq_transcription_response(200, {"text": "   "})[0] is False
    assert c.parse_groq_transcription_response(429, {"error": {"message": "quota"}})[0] is False
    assert c.parse_groq_transcription_response(200, None)[0] is False
    # A provider message is never echoed to the browser.
    ok, text, code = c.parse_groq_transcription_response(500, {"error": {"message": "secret-ish"}})
    assert (ok, text, code) == (False, "", "stt_failed")


def test_live_token_request_uses_rfc3339_absolute_timestamps():
    """#4644 P0-1: a duration string is not a timestamp the API accepts."""
    body = c.build_live_token_request_body(now_epoch_ms=1_800_000_000_000)
    rfc3339 = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,3})?Z$"
    assert re.fullmatch(rfc3339, body["expireTime"]), body["expireTime"]
    assert re.fullmatch(rfc3339, body["newSessionExpireTime"]), body["newSessionExpireTime"]
    for value in body.values():
        assert not (isinstance(value, str) and re.fullmatch(r"\d+s", value))
    assert body["expireTime"] == "2027-01-15T08:30:00Z"
    assert body["newSessionExpireTime"] == "2027-01-15T08:01:00Z"
    assert body["uses"] == 1


def test_live_token_locks_the_stt_model_via_live_connect_constraints():
    """The model is bound to ``liveConnectConstraints``, never sent top-level."""
    body = c.build_live_token_request_body(model="gemini-3.5-transcribe-live", now_epoch_ms=1_800_000_000_000)
    assert body["liveConnectConstraints"] == {"model": "gemini-3.5-transcribe-live"}
    assert "model" not in body
    assert set(body) == {"uses", "expireTime", "newSessionExpireTime", "liveConnectConstraints"}


def test_token_lifetimes_match_documented_defaults():
    assert c.GEMINI_LIVE_TOKEN_EXPIRE_MINUTES == 30
    assert c.GEMINI_LIVE_TOKEN_NEW_SESSION_EXPIRE_MINUTES == 1
    body = c.build_live_token_request_body(now_epoch_ms=1_800_000_000_000)
    expire = datetime.datetime.strptime(body["expireTime"], "%Y-%m-%dT%H:%M:%SZ")
    session = datetime.datetime.strptime(body["newSessionExpireTime"], "%Y-%m-%dT%H:%M:%SZ")
    assert expire.replace(tzinfo=datetime.timezone.utc) - session.replace(tzinfo=datetime.timezone.utc) == datetime.timedelta(minutes=29)


def test_live_token_endpoint_is_v1beta_per_official_documentation():
    assert c.GEMINI_LIVE_TOKEN_ENDPOINT.endswith("/v1beta/auth_tokens")
    assert "v1alpha" not in c.GEMINI_LIVE_TOKEN_ENDPOINT


def test_format_rfc3339_utc_renders_absolute_instants():
    assert c.format_rfc3339_utc(1_800_000_000_000) == "2027-01-15T08:00:00Z"
    assert c.format_rfc3339_utc(1_800_000_000_123) == "2027-01-15T08:00:00.123Z"
    for bad in (0, -1, None, True, 1.5):
        with pytest.raises(ValueError):
            c.format_rfc3339_utc(bad)


def test_live_token_contract_returns_only_an_ephemeral_token():
    assert c.build_live_token_request_body()["uses"] == 1
    assert c.extract_live_token({"name": "auth_tokens/abc"}) == "auth_tokens/abc"
    assert c.extract_live_token({"name": ""}) is None
    assert c.extract_live_token(None) is None
    assert c.GEMINI_LIVE_TOKEN_ENDPOINT.startswith("https://generativelanguage.googleapis.com/")


def test_public_session_config_carries_no_secret():
    public = c.LiveSessionConfig().to_public_dict()
    assert set(public) == {
        "model",
        "vad_silence_ms",
        "rotate_after_ms",
        "response_modalities",
        "input_audio_transcription_mode",
    }
    blob = repr(public).lower()
    for forbidden in ("key", "token", "secret", "bearer"):
        assert forbidden not in blob


def test_binding_names_are_declared_and_groq_is_marked_unverified():
    assert c.GEMINI_API_KEY_BINDING == "PADIEM_GEMINI_API_KEY"
    assert c.GROQ_API_KEY_BINDING == "PADIEM_GROQ_API_KEY"
    # Owner-reported only: the exact Groq secret_name is not in any repo config.
    # Declared != runtime verified.
    assert c.GROQ_API_KEY_BINDING_VERIFIED is False
    assert c.VOICE_STT_SERVICE_BINDING == "VOICE_STT_SERVICE"
    assert c.VOICE_STT_CALLER_GUARD_BINDING == "VOICE_STT_CALLER_GUARD"
    assert c.VOICE_STT_ENABLED_BINDING == "PADIEM_VOICE_STT_ENABLED"
    # P0-4: the Secrets Store resource id is NOT duplicated in this module.
    assert not [name for name in vars(c) if "STORE_ID" in name.upper()]


def test_upstream_timeouts_are_finite_and_ordered():
    assert 0 < c.LIVE_TOKEN_REQUEST_TIMEOUT_MS < c.GROQ_REQUEST_TIMEOUT_MS
    assert c.GROQ_REQUEST_TIMEOUT_MS == 25_000
    assert c.LIVE_TOKEN_REQUEST_TIMEOUT_MS == 8_000


def test_every_error_code_has_a_status():
    assert set(c.STATUS_BY_CODE) == set(c.VOICE_STT_CODES)
    assert all(400 <= status < 600 for status in c.STATUS_BY_CODE.values())


def test_voice_stt_error_rejects_unregistered_code():
    with pytest.raises(ValueError):
        c.VoiceSttError("definitely_not_registered")


# ---------------------------------------------------------------------------
# P0-3: declared Content-Length and incremental body reading
# ---------------------------------------------------------------------------


def test_parse_declared_content_length():
    assert c.parse_declared_content_length(None) is None
    assert c.parse_declared_content_length("0") == 0
    assert c.parse_declared_content_length("1024") == 1024
    assert c.parse_declared_content_length(1024) == 1024
    assert c.parse_declared_content_length("  1024  ") == 1024


@pytest.mark.parametrize("declared", ["-1", "-4096", "abc", "", "1.5", "0x10", "12,3", "1 024"])
def test_parse_declared_content_length_rejects_malformed(declared):
    with pytest.raises(c.VoiceSttError) as exc:
        c.parse_declared_content_length(declared)
    assert exc.value.code in ("invalid_content_length",)


def test_parse_declared_content_length_rejects_bool():
    # True == 1 must not slip through as a byte count.
    with pytest.raises(c.VoiceSttError):
        c.parse_declared_content_length(True)


async def _chunk_gen(chunks):
    async def read(limit):
        if not chunks:
            return None
        data = chunks.pop(0)
        return data[:limit]

    return read


async def test_read_bounded_body_concatenates_every_chunk():
    read = await _chunk_gen([b"ab", b"cd", b"ef"])
    assert await c.read_bounded_body(read, 6) == b"abcdef"


async def test_read_bounded_body_rejects_as_soon_as_the_cap_is_exceeded():
    read = await _chunk_gen([b"a" * 4, b"b" * 4])
    with pytest.raises(c.VoiceSttError) as exc:
        await c.read_bounded_body(read, 6)
    assert exc.value.code == "request_too_large"


async def test_read_bounded_body_accepts_a_body_exactly_at_the_cap():
    delivered = [b"z" * 6, None]

    async def read(_limit):
        return delivered.pop(0) if delivered else None

    assert await c.read_bounded_body(read, 6) == b"zzzzzz"


async def test_read_bounded_body_rejects_one_byte_over_the_cap():
    async def read(limit):
        return b"z" * (limit + 1) if limit else b"z" * 7

    with pytest.raises(c.VoiceSttError) as exc:
        await c.read_bounded_body(read, 6)
    assert exc.value.code == "request_too_large"


async def test_read_bounded_body_accepts_no_content_length_stream():
    """A chunked request with no declared length is still bounded by the cap."""
    chunks = [b"0123", b"4567"]
    async def read(limit):
        if not chunks:
            return None
        return chunks.pop(0)[:limit]
    assert await c.read_bounded_body(read, 8) == b"01234567"
    with pytest.raises(c.VoiceSttError):
        await c.read_bounded_body(await _chunk_gen([b"0123", b"4567"]), 7)


async def test_read_bounded_body_rejects_a_non_bytes_chunk():
    async def read(_limit):
        return 12345
    with pytest.raises(c.VoiceSttError) as exc:
        await c.read_bounded_body(read, 64)
    assert exc.value.code == "invalid_json"


async def test_read_bounded_body_accepts_str_and_memoryview_chunks():
    delivered = ["hello", None]

    async def read1(_limit):
        return delivered.pop(0) if delivered else None

    assert await c.read_bounded_body(read1, 64) == b"hello"

    delivered = [memoryview(b"world"), None]

    async def read2(_limit):
        return delivered.pop(0) if delivered else None

    assert await c.read_bounded_body(read2, 64) == b"world"


def test_read_bounded_body_uses_the_plus_one_limit_probe():
    """The contract must ask for one byte over budget, never the whole body."""
    import inspect

    source = inspect.getsource(c.read_bounded_body)
    assert "max_bytes - total + 1" in source


def test_normalize_http_method_handles_enum_and_string():
    from http import HTTPMethod

    assert c.normalize_http_method(HTTPMethod.POST) == "POST"
    assert c.normalize_http_method(HTTPMethod.GET) == "GET"
    assert c.normalize_http_method("post") == "POST"
    assert c.normalize_http_method(None) == "NONE"


def test_route_path_extracts_the_path_component():
    assert c.route_path("https://voice.internal/internal/v1/voice/transcribe") == "/internal/v1/voice/transcribe"
    assert c.route_path("https://voice.internal/internal/v1/voice/transcribe?x=1") == "/internal/v1/voice/transcribe"
    assert c.route_path("https://voice.internal/") == "/"
    assert c.route_path("") == ""
    assert c.route_path(None) == "None"
    assert c.route_path("not a url at all") == "not a url at all"
