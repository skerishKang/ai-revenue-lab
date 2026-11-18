"""One read path for the split locale groups (#7995).

Tests that used to read ``static/locale.js`` now read the merged view of every
group file. ``source()`` rebuilds the old single-file shape (one ``ko: {`` and
one ``en: {`` block, one key per line) so existing block-parsing contracts keep
working without being weakened.
"""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
GROUP_NAMES = (
    "locale-common.js", "locale-chat.js", "locale-claw.js",
    "locale-pc-connect.js", "locale-settings.js", "locale-utility.js",
    "locale-feedback-news.js",
)
GROUP_PATHS = tuple(STATIC / name for name in GROUP_NAMES)
PAIR = re.compile(r'"((?:[^"\\]|\\.)*)"\s*:\s*"((?:[^"\\]|\\.)*)"')


def group_text(path: Path, lang: str) -> str:
    source = path.read_text(encoding="utf-8")
    end = "\n    }," if lang == "ko" else "\n    }"
    block = source.split("%s: {" % lang, 1)[1].split(end, 1)[0]
    return block


def keys(lang: str) -> dict[str, str]:
    merged: dict[str, str] = {}
    for path in GROUP_PATHS:
        merged.update(PAIR.findall(group_text(path, lang)))
    return merged


def source() -> str:
    """The bootstrap with every group's keys inlined: the old single-file view."""
    boot = (STATIC / "locale.js").read_text(encoding="utf-8")
    ko = "\n".join(line for path in GROUP_PATHS
                   for line in group_text(path, "ko").splitlines() if line.strip())
    en = "\n".join(line for path in GROUP_PATHS
                   for line in group_text(path, "en").splitlines() if line.strip())
    start = boot.index("  const labels = { ko: {}, en: {} };")
    end = boot.index("  const promptCopy", start)
    labels = ("  const labels = {\n    ko: {\n%s\n    },\n    en: {\n%s\n    }\n  };\n\n"
              % (ko, en))
    return boot[:start] + labels + boot[end:]


SOURCE_PATH = Path(__file__).resolve().parent / "fixtures" / "locale_merged.js"


class _Source:
    """Drop-in for a Path: reads return the merged source, str() is its path."""

    def read_text(self, *args, **kwargs) -> str:
        return SOURCE_PATH.read_text(encoding="utf-8")

    def __str__(self) -> str:
        return str(SOURCE_PATH)


SOURCE = _Source()
