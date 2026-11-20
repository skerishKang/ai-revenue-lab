"""Shared public-copy validation and news publishing for the CLI and admin UI."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .feedback_store import FEEDBACK_ID
from .news_store import DETAIL_CHARS, KINDS, SOURCES, TITLE_CHARS, VERSION, NewsUnavailable


class NewsPublishError(RuntimeError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


MAX_FEEDBACK = 20
#: Literal '#12' or '# 12' — an issue number is internal and never public.
ISSUE_REF = re.compile(r'#\s*\d')
EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
PHONE = re.compile(r'(?:\+?82[-\s]?)?0\d{1,2}[-\s]?\d{3,4}[-\s]?\d{4}')
LATIN_WORD = re.compile(r'[A-Za-z]{3,}')
#: Words that may appear in public copy. A product, model or provider name is
#: not one of them, so an English proper noun stops here instead of leaking —
#: the list is short on purpose and grows only with CTO review.
ALLOWED_LATIN = frozenset({
    'chat', 'claw', 'pdf', 'markdown', 'excel', 'sns', 'api', 'url',
    # #7847 — the product's own name and the names of formats a customer
    # already reads in their own files. A model or provider name still stops
    # here, so these are words a customer sees on the screen, not vendors.
    'padiem', 'google', 'gmail', 'zip', 'ocr', 'csv', 'json', 'html', 'word',
    'powerpoint',
})


def check_public_copy(text, field):
    """Refuse public text that carries something only we may see."""
    if ISSUE_REF.search(text):
        raise NewsPublishError('NEWS_' + field + '_ISSUE_REF')
    if EMAIL.search(text):
        raise NewsPublishError('NEWS_' + field + '_EMAIL')
    if PHONE.search(text):
        raise NewsPublishError('NEWS_' + field + '_PHONE')
    unknown = {word.lower() for word in LATIN_WORD.findall(text)} - ALLOWED_LATIN
    if unknown:
        raise NewsPublishError('NEWS_' + field + '_FOREIGN_WORD')


def check_text(text, field, limit):
    if (not isinstance(text, str) or not text.strip() or len(text) > limit
            or any(ord(c) < 32 and c not in '\n\r\t' for c in text)
            or any(0xD800 <= ord(c) <= 0xDFFF for c in text)):
        raise NewsPublishError('NEWS_' + field + '_INVALID')
    check_public_copy(text, field)


def check_request(version, kind, title, detail, source, feedback, *, allow_legacy=False):
    if not isinstance(version, str) or (not (allow_legacy and version == '') and VERSION.match(version) is None):
        raise NewsPublishError('NEWS_VERSION_INVALID')
    if not isinstance(kind, str) or kind not in KINDS:
        raise NewsPublishError('NEWS_KIND_INVALID')
    if not isinstance(source, str) or source not in SOURCES:
        raise NewsPublishError('NEWS_SOURCE_INVALID')
    check_text(title, 'TITLE', TITLE_CHARS)
    check_text(detail, 'DETAIL', DETAIL_CHARS)
    if not isinstance(feedback, (list, tuple)):
        raise NewsPublishError('FEEDBACK_ID_INVALID')
    unique = []
    for feedback_id in feedback:
        if not isinstance(feedback_id, str) or FEEDBACK_ID.fullmatch(feedback_id) is None:
            raise NewsPublishError('FEEDBACK_ID_INVALID')
        if feedback_id not in unique:
            unique.append(feedback_id)
    if len(unique) > MAX_FEEDBACK:
        raise NewsPublishError('FEEDBACK_TOO_MANY')
    return tuple(unique)



@dataclass(frozen=True)
class PublishResult:
    record: object = None
    error: str | None = None
    feedback_id: str | None = None


async def write_news(news_store, feedback_store, *, version, kind, title, detail,
                     source, feedback=(), number=None, audit=None, actor=None):
    """Validate all input and linked feedback before writing; one audit per
    successful create/edit, including a partial link failure after the write.

    Existing links are retained. A submitted opinion already linked to another
    item is refused instead of silently changing its published reference.
    """
    feedback = check_request(version, kind, title, detail, source, feedback,
                             allow_legacy=number is not None)
    if news_store is None:
        raise NewsPublishError('NEWS_STORE_UNAVAILABLE')
    if number is not None and (type(number) is not int or number < 1):
        raise NewsPublishError('NEWS_NUMBER_INVALID')
    if number is not None and await news_store.get(number) is None:
        return PublishResult(error='NEWS_NOT_FOUND')
    if feedback and feedback_store is None:
        raise NewsPublishError('FEEDBACK_STORE_UNAVAILABLE')
    new_links = []
    for feedback_id in feedback:
        existing = await feedback_store.get_record(feedback_id)
        if existing is None:
            return PublishResult(error='FEEDBACK_NOT_FOUND', feedback_id=feedback_id)
        linked = getattr(existing, 'news_number', None)
        if linked is not None:
            if linked != number:
                return PublishResult(error='FEEDBACK_ALREADY_LINKED', feedback_id=feedback_id)
        else:
            new_links.append(feedback_id)
    if number is None:
        record = await news_store.create(kind, title, detail, source, version)
    else:
        record = await news_store.update(number, kind, title, detail, source, version)
        if record is None:
            return PublishResult(error='NEWS_NOT_FOUND')
    item_number = getattr(record, 'number', None)
    if type(item_number) is not int or item_number < 1:
        return PublishResult(error='NEWS_STORE_REFUSED')
    linked_count = 0
    error = None
    try:
        for feedback_id in new_links:
            if not await news_store.link_feedback(feedback_id, item_number):
                error = 'FEEDBACK_LINK_FAILED'
                break
            linked_count += 1
    except NewsUnavailable:
        error = 'FEEDBACK_LINK_FAILED'
    finally:
        if audit is not None and actor:
            await audit.append(actor_user_id=actor,
                               action='news_create' if number is None else 'news_update',
                               target_type='news', target_id=str(item_number),
                               detail={'source': source, 'linked_count': linked_count,
                                       'partial': error is not None})
    return PublishResult(record, error)
