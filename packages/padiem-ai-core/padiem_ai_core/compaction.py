"""Pure compaction and owner-scoped source archive.

Adapted from OpenCode session compaction (MIT) and OpenClaw's transcript
preservation/identifier policy (MIT):
https://github.com/openclaw/openclaw/blob/main/docs/concepts/compaction.md
See THIRD_PARTY_NOTICES.md. The caller supplies the authenticated owner,
archive location and summarizer; no model or Engine is invoked here.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

HEADINGS = ("완료한 것", "진행 중", "남은 일", "중요한 파일·경로")
SUMMARY_PROMPT = (
    "대화에서 완료한 것, 진행 중, 남은 일, 중요한 파일·경로를 정리하세요. "
    "각 항목에 그 근거가 되는 입력 메시지 id를 source_ids로 기록하세요. "
    "source_ids는 전달받은 메시지 id만 사용하세요."
)
DEFAULT_KEEP_RECENT = 8


def _owner(owner: str) -> str:
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError("owner must be a non-empty authenticated owner")
    return owner


class CompactionStore:
    """SQLite archive; the host is responsible for authenticating owner.

    A caller-selected database file survives process restarts. Use ':memory:'
    only for tests. The database is not a substitute for host authentication.
    """

    def __init__(self, path: str | Path):
        self._db = sqlite3.connect(str(path))
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS compaction_sources "
            "(owner TEXT NOT NULL, id TEXT NOT NULL, message TEXT NOT NULL, "
            "PRIMARY KEY(owner,id))"
        )
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    def save(self, messages: Sequence[Mapping[str, Any]], *, owner: str) -> None:
        owner = _owner(owner)
        rows = [(owner, m["id"], json.dumps(m, ensure_ascii=False, sort_keys=True))
                for m in messages]
        with self._db:
            for row in rows:
                current = self._db.execute(
                    "SELECT message FROM compaction_sources WHERE owner=? AND id=?",
                    row[:2],
                ).fetchone()
                if current is not None and current[0] != row[2]:
                    raise ValueError("source id already has different content")
                if current is None:
                    self._db.execute("INSERT INTO compaction_sources VALUES (?,?,?)", row)

    def recall(self, source_ids: Sequence[str], *, owner: str) -> list[dict[str, Any]]:
        owner = _owner(owner)
        if isinstance(source_ids, (str, bytes)) or not all(
            isinstance(x, str) and x for x in source_ids
        ):
            raise ValueError("source_ids must be a sequence of non-empty ids")
        result = []
        for source_id in source_ids:
            row = self._db.execute(
                "SELECT message FROM compaction_sources WHERE owner=? AND id=?",
                (owner, source_id),
            ).fetchone()
            # Do not reveal whether another owner has the requested ID.
            if row is None:
                raise PermissionError("source unavailable for owner")
            result.append(json.loads(row[0]))
        return result


def needs_compaction(messages: Sequence[Mapping[str, Any]], token_budget: int) -> bool:
    if isinstance(token_budget, bool) or not isinstance(token_budget, int) or token_budget <= 0:
        raise ValueError("token_budget must be a positive integer")
    text = json.dumps(list(messages), ensure_ascii=False, separators=(",", ":"))
    return max(len(text), (len(text.encode("utf-8")) + 3) // 4) > token_budget


def compact(
    messages: Sequence[Mapping[str, Any]],
    summarize_fn: Callable[[list[Mapping[str, Any]], str], Mapping[str, Any]],
    keep_recent: int = DEFAULT_KEEP_RECENT,
    *,
    owner: str,
    store: CompactionStore,
) -> dict[str, Any]:
    """Return summary items with original source IDs and archive removed turns.

    summarize_fn returns {'items': [{'section': heading, 'text': text,
    'source_ids': [input_message_id, ...]}, ...]}. Previous summaries can be
    included as assistant messages with their previous 'summary_items' list.
    Their IDs are recursively replaced with original archived IDs.
    """
    owner = _owner(owner)
    if not isinstance(store, CompactionStore):
        raise TypeError("store must be a CompactionStore")
    if isinstance(keep_recent, bool) or not isinstance(keep_recent, int) or keep_recent < 0:
        raise ValueError("keep_recent must be a non-negative integer")
    if not callable(summarize_fn):
        raise TypeError("summarize_fn must be callable")
    source = list(messages)
    if any(not isinstance(message, Mapping) for message in source):
        raise ValueError("messages must contain mappings")
    tail_start = max(0, len(source) - keep_recent)
    kept = [m for i, m in enumerate(source) if i >= tail_start or m.get("role") == "user"]
    older = [m for i, m in enumerate(source) if i < tail_start and m.get("role") != "user"]
    ids = [m.get("id") for m in older]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("each removed message must have a unique non-empty id")
    by_id = {m["id"]: m for m in older}
    items = [] if not older else summarize_fn(older, SUMMARY_PROMPT).get("items")
    if not isinstance(items, list):
        raise ValueError("summary items must be a list")
    normalized = []
    for item in items:
        if not isinstance(item, Mapping) or item.get("section") not in HEADINGS:
            raise ValueError("invalid summary section")
        text, refs = item.get("text"), item.get("source_ids")
        if not isinstance(text, str) or not text.strip() or not isinstance(refs, list) or not refs:
            raise ValueError("summary item requires text and source_ids")
        original_ids = []
        for ref in refs:
            if not isinstance(ref, str) or ref not in by_id:
                raise ValueError("summary source must be an input message")
            prior = by_id[ref].get("summary_items")
            expanded = [sid for part in prior for sid in part.get("source_ids", [])] if prior else [ref]
            if prior:
                store.recall(expanded, owner=owner)
            for sid in expanded:
                if sid not in original_ids:
                    original_ids.append(sid)
        normalized.append({"section": item["section"], "text": text, "source_ids": original_ids})
    if older and set(item["section"] for item in normalized) != set(HEADINGS):
        raise ValueError("summary requires all four sections")
    store.save(older, owner=owner)
    summary_text = "\n".join(
        "## " + heading + "\n" + "\n".join(
            "- " + item["text"] for item in normalized if item["section"] == heading
        ) for heading in HEADINGS
    )
    return {"summary": {"text": summary_text, "items": normalized},
            "kept": kept, "dropped_ids": ids}
