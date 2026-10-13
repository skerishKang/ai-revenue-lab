"""Server-side STT transport contract (Groq Whisper + Gemini Live token).

Ported from ``netlify/functions/transcribe.mts`` (Groq) and the
``/api/live-token`` contract in ``hooks/useInterviewLive.ts`` (Gemini Live),
minus the Netlify runtime. Every rule here is pure and testable without the
Cloudflare Workers runtime.
"""

from __future__ import annotations

import base64

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


def test_live_token_contract_returns_only_an_ephemeral_token():
    body = c.build_live_token_request_body()
    assert body["model"] == c.GEMINI_LIVE_STT_MODEL
    assert body["uses"] == 1
    assert isinstance(body["expireTime"], str)
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
    assert c.GROQ_API_KEY_BINDING_VERIFIED is False
    assert c.PADIEM_SECRETS_STORE_ID == "f0b09ca04a7b43248154c773704a5616"


def test_every_error_code_has_a_status():
    assert set(c.STATUS_BY_CODE) == set(c.VOICE_STT_CODES)
    assert all(400 <= status < 600 for status in c.STATUS_BY_CODE.values())


def test_voice_stt_error_rejects_unregistered_code():
    with pytest.raises(ValueError):
        c.VoiceSttError("definitely_not_registered")


def test_normalize_http_method_handles_enum_and_string():
    from http import HTTPMethod

    assert c.normalize_http_method(HTTPMethod.POST) == "POST"
    assert c.normalize_http_method(HTTPMethod.GET) == "GET"
    assert c.normalize_http_method("post") == "POST"
    assert c.normalize_http_method(None) == "NONE"
