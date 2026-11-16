#!/usr/bin/env python3
"""Publish one '새 소식' item under its deployment version (#7847 step 1).

The browser screen only reads news; writing an item used to live inside
``feedback_ops.py --news-create`` and had no way to say which deployment the
item belongs to and which feedback rows it answers. This tool is that one
publishing path: it calls the same store functions the Chat service uses
(``D1NewsStore.create`` and ``D1NewsStore.link_feedback``), never SQL.

Preview is the default and prints the whole public text plus its length check
so an operator reads exactly what a customer will read:

    sudo -u root /opt/padiem/chat-com2/venv/bin/python \\
        /opt/padiem/com2-deploy/ops/apps/padiem-chat/tools/chat_news_publish.py \\
        --version 2026.11.16 --kind improved --source ai_tester \\
        --title "..." --detail "..."

Write only with ``--apply`` (and only then are the root-only env file, the
service user and the deployed tree touched):

    ... chat_news_publish.py --version 2026.11.16 --kind fixed --source user \\
        --title "..." --detail "..." --feedback fb_<32hex> [fb_<32hex> ...] --apply

Refusals are one code per line and never repeat the rejected text: the public
list must not carry an issue number, a model or provider name, an e-mail
address or a phone number.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[1]
_TOOLS_DIR = Path(__file__).resolve().parent
for _path in (_TOOLS_DIR, _APP_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

# The COM2 conventions (root-only env file, drop to the service user, call the
# deployed tree's own store) have exactly one copy, in feedback_ops. Reusing it
# keeps the credentials path in one place instead of a second copy to drift.
from app.feedback_store import FEEDBACK_ID
from app.news_store import DETAIL_CHARS, KINDS, SOURCES, TITLE_CHARS, VERSION
from feedback_ops import (
    CHAT_ENV_PATH,
    ToolError,
    _assert_root,
    _become_service_user,
    _load_env_file,
    _load_state,
    _use_deployed_tree,
)

MAX_FEEDBACK = 20
#: Literal '#12' or '# 12' — an issue number is internal and never public.
ISSUE_REF = re.compile(r'#\s*\d')
EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
PHONE = re.compile(r'(?:\+?82[-\s]?)?0\d{1,2}[-\s]?\d{3,4}[-\s]?\d{4}')
LATIN_WORD = re.compile(r'[A-Za-z]{3,}')
#: Words that may appear in public copy. A product, model or provider name is
#: not one of them, so an English proper noun stops here instead of leaking —
#: the list is short on purpose and grows only with CTO review.
ALLOWED_LATIN = frozenset({'chat', 'claw', 'pdf', 'markdown', 'excel', 'sns', 'api', 'url'})


def check_public_copy(text, field):
    """Refuse public text that carries something only we may see."""
    if ISSUE_REF.search(text):
        raise ToolError('NEWS_' + field + '_ISSUE_REF')
    if EMAIL.search(text):
        raise ToolError('NEWS_' + field + '_EMAIL')
    if PHONE.search(text):
        raise ToolError('NEWS_' + field + '_PHONE')
    unknown = {word.lower() for word in LATIN_WORD.findall(text)} - ALLOWED_LATIN
    if unknown:
        raise ToolError('NEWS_' + field + '_FOREIGN_WORD')


def check_text(text, field, limit):
    if (not isinstance(text, str) or not text.strip() or len(text) > limit
            or any(ord(c) < 32 and c not in '\n\r\t' for c in text)
            or any(0xD800 <= ord(c) <= 0xDFFF for c in text)):
        raise ToolError('NEWS_' + field + '_INVALID')
    check_public_copy(text, field)


def check_request(version, kind, title, detail, source, feedback):
    if not isinstance(version, str) or VERSION.match(version) is None:
        raise ToolError('NEWS_VERSION_INVALID')
    if kind not in KINDS:
        raise ToolError('NEWS_KIND_INVALID')
    if source not in SOURCES:
        raise ToolError('NEWS_SOURCE_INVALID')
    check_text(title, 'TITLE', TITLE_CHARS)
    check_text(detail, 'DETAIL', DETAIL_CHARS)
    unique = []
    for feedback_id in feedback:
        if FEEDBACK_ID.fullmatch(feedback_id) is None:
            raise ToolError('FEEDBACK_ID_INVALID')
        if feedback_id not in unique:
            unique.append(feedback_id)
    if len(unique) > MAX_FEEDBACK:
        raise ToolError('FEEDBACK_TOO_MANY')
    return tuple(unique)


def _lines(version, kind, source, title, detail, feedback):
    return [f'version={version}', f'kind={kind}', f'source={source}',
            f'title_chars={len(title)}/{TITLE_CHARS}', f'detail_chars={len(detail)}/{DETAIL_CHARS}',
            f'feedback={len(feedback)}', f'title={title}', f'detail={detail}']


async def run_publish(news_store, feedback_store, *, version, kind, title, detail, source,
                      feedback=(), apply=False):
    """Create one item and point the named feedback rows at it.

    Preview writes nothing and needs no store. Apply calls the store's own
    `create` once, then one `link_feedback` per feedback id; a link that the
    store refuses is reported with the item number already printed, so the
    operator can finish it with the existing tool instead of guessing.
    """
    feedback = check_request(version, kind, title, detail, source, feedback)
    lines = _lines(version, kind, source, title, detail, feedback)
    if not apply:
        lines.append('ok=true')
        return {'lines': lines, 'error': None}
    if news_store is None:
        raise ToolError('NEWS_STORE_UNAVAILABLE')
    if feedback and feedback_store is not None:
        for feedback_id in feedback:
            if await feedback_store.get_record(feedback_id) is None:
                return {'lines': [f'feedback={feedback_id}', 'ok=false'],
                        'error': 'FEEDBACK_NOT_FOUND'}
    record = await news_store.create(kind, title, detail, source, version)
    number = getattr(record, 'number', None)
    if type(number) is not int or number < 1:
        return {'lines': ['news=pending', 'ok=false'], 'error': 'NEWS_STORE_REFUSED'}
    lines = [f'news={number}'] + lines
    for feedback_id in feedback:
        if not await news_store.link_feedback(feedback_id, number):
            return {'lines': lines, 'error': 'FEEDBACK_LINK_FAILED'}
    lines.append('ok=true')
    return {'lines': lines, 'error': None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--kind', required=True, choices=sorted(KINDS))
    parser.add_argument('--title', required=True)
    parser.add_argument('--detail', required=True)
    parser.add_argument('--source', required=True, choices=sorted(SOURCES))
    parser.add_argument('--feedback', nargs='+', action='append', default=[])
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    feedback = [item for group in args.feedback for item in group]
    try:
        news_store = feedback_store = None
        if args.apply:
            _assert_root()
            _load_env_file(CHAT_ENV_PATH)
            _use_deployed_tree()
            _become_service_user()
            state = _load_state()
            news_store = getattr(state, 'news_store', None)
            feedback_store = getattr(state, 'feedback_store', state)
            if news_store is None:
                raise ToolError('NEWS_STORE_UNAVAILABLE')
        result = asyncio.run(run_publish(
            news_store, feedback_store, version=args.version, kind=args.kind,
            title=args.title, detail=args.detail, source=args.source,
            feedback=feedback, apply=args.apply))
    except ToolError as exc:
        print('STOP ' + exc.code)
        return 1
    except Exception:
        print('STOP NEWS_PUBLISH_REFUSED')
        return 1
    for line in result['lines']:
        print(line)
    if result.get('error'):
        print('STOP ' + result['error'])
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
