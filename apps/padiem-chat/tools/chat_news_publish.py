#!/usr/bin/env python3
"""Publish one '새 소식' item under its deployment version (#7847 step 1).

The publishing tool and the administrator screen share ``app.news_publish``:
public-copy validation, feedback checks and the same news store functions.
The signed-in customer screen still reads news only. Neither publishing
entry point runs SQL directly.

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

An already published item's source can be corrected without touching its
title, detail, date or number. The item is named by its published number:

    ... chat_news_publish.py --fix-source 9 --source none
    ... chat_news_publish.py --fix-source 9 --source none --apply

Preview (the default) reads the item and prints source_before/source_after;
only --apply calls the store's own update_source.

Refusals are one code per line and never repeat the rejected text: the public
list must not carry an issue number, a model or provider name, an e-mail
address or a phone number.
"""
from __future__ import annotations

import argparse
import asyncio
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
from app.news_store import DETAIL_CHARS, KINDS, SOURCES, TITLE_CHARS
from app.news_publish import NewsPublishError as ToolError, check_request, write_news
from feedback_ops import (
    CHAT_ENV_PATH,
    ToolError as OpsToolError,
    _assert_root,
    _become_service_user,
    _load_env_file,
    _load_state,
    _use_deployed_tree,
)

def _lines(version, kind, source, title, detail, feedback):
    return [f'version={version}', f'kind={kind}', f'source={source}',
            f'title_chars={len(title)}/{TITLE_CHARS}', f'detail_chars={len(detail)}/{DETAIL_CHARS}',
            f'feedback={len(feedback)}', f'title={title}', f'detail={detail}']


async def run_publish(news_store, feedback_store, *, version, kind, title, detail, source,
                      feedback=(), apply=False, audit=None):
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
    result = await write_news(news_store, feedback_store, version=version, kind=kind,
                              title=title, detail=detail, source=source, feedback=feedback,
                              audit=audit, actor='ops-tool')
    if result.record is None:
        label = f'feedback={result.feedback_id}' if result.feedback_id else 'news=pending'
        return {'lines': [label, 'ok=false'], 'error': result.error}
    lines = [f'news={result.record.number}'] + lines
    if result.error:
        return {'lines': lines, 'error': result.error}
    lines.append('ok=true')
    return {'lines': lines, 'error': None}


async def run_fix_source(news_store, *, number, source, apply=False, audit=None):
    """Correct only the source of one published item; preview writes nothing."""
    if type(number) is not int or number < 1:
        raise ToolError('NEWS_NUMBER_INVALID')
    if source not in SOURCES:
        raise ToolError('NEWS_SOURCE_INVALID')
    if news_store is None:
        raise ToolError('NEWS_STORE_UNAVAILABLE')
    record = await news_store.get(number)
    if record is None:
        return {'lines': [f'news={number}', 'ok=false'], 'error': 'NEWS_NOT_FOUND'}
    lines = [f'news={number}', f'version={record.version}', f'title={record.title}',
             f'source_before={record.source}', f'source_after={source}']
    if apply:
        updated = await news_store.update_source(number, source)
        if updated is None:
            return {'lines': lines, 'error': 'NEWS_STORE_REFUSED'}
        if audit is not None:
            await audit.append(actor_user_id='ops-tool', action='news_update',
                               target_type='news', target_id=str(number),
                               detail={'source': source})
    lines.append('ok=true')
    return {'lines': lines, 'error': None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version')
    parser.add_argument('--fix-source', type=int, metavar='NUMBER')
    parser.add_argument('--kind', choices=sorted(KINDS))
    parser.add_argument('--title')
    parser.add_argument('--detail')
    parser.add_argument('--source', required=True, choices=sorted(SOURCES))
    parser.add_argument('--feedback', nargs='+', action='append', default=[])
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    feedback = [item for group in args.feedback for item in group]
    try:
        news_store = feedback_store = audit = None
        # Correcting a published source needs the deployed store even in preview,
        # because the item and its current source are read before anything is
        # shown. Publish preview still needs no store at all.
        if args.fix_source is not None or args.apply:
            _assert_root()
            _load_env_file(CHAT_ENV_PATH)
            _use_deployed_tree()
            _become_service_user()
            state = _load_state()
            news_store = getattr(state, 'news_store', None)
            audit = getattr(state, 'ops_audit_store', None)
            feedback_store = getattr(state, 'feedback_store', state)
            if news_store is None:
                raise ToolError('NEWS_STORE_UNAVAILABLE')
        if args.fix_source is not None:
            result = asyncio.run(run_fix_source(
                news_store, number=args.fix_source, source=args.source, apply=args.apply, audit=audit))
        else:
            result = asyncio.run(run_publish(
                news_store, feedback_store, version=args.version or '', kind=args.kind or '',
                title=args.title or '', detail=args.detail or '', source=args.source,
                feedback=feedback, apply=args.apply, audit=audit))
    except (ToolError, OpsToolError) as exc:
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
