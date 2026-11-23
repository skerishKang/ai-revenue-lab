from pathlib import Path


_REFERENCE_ASSISTANT_RULE = b".assistant-content { color: var(--styles-assistant-content-text); font-size: 16px; }"
_APP_ASSISTANT_RULE = b".assistant-content { color: var(--styles-assistant-content-text); font-family: inherit; font-size: 16px; }"


def assert_phase1_styles_match(static_styles: Path, reference_styles: Path) -> None:
    """Keep the accepted stylesheet byte-pinned except answer font inheritance."""
    actual = static_styles.read_bytes()
    reference = reference_styles.read_bytes()
    assert actual == reference or (
        reference.count(_REFERENCE_ASSISTANT_RULE) == 1
        and actual == reference.replace(_REFERENCE_ASSISTANT_RULE, _APP_ASSISTANT_RULE, 1)
    )
