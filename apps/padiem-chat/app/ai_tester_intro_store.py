"""Short intro for AI honorary member accounts (#7690 stage 1).

Human users have no row here. The intro is written only by the operations tool
and read only by the administrator feedback inbox; it never enters a user
route, a response for a normal account, or a log line.
"""
from __future__ import annotations

import re

from .d1_rows import rows_from_result

INTRO_ID = re.compile(r"usr_[0-9a-f]{32}\Z")
FIELDS = ('age_band', 'job', 'device')
_MAX = 80


def clean_intro(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError('intro_invalid')
    text = ' '.join(value.split())
    if not text or len(text) > _MAX or any(ord(ch) < 32 for ch in text):
        raise ValueError('intro_invalid')
    return text


class AiTesterIntroStore:
    def __init__(self, db):
        if db is None or not callable(getattr(db, 'prepare', None)):
            raise ValueError('intro_store_unavailable')
        self._db = db

    async def _rows(self, sql, *values):
        result = await self._db.prepare(sql).bind(*values).run()
        return [dict(row.to_py() if callable(getattr(row, 'to_py', None)) else row)
                for row in rows_from_result(result)]

    async def get(self, user_id):
        if not isinstance(user_id, str) or INTRO_ID.fullmatch(user_id) is None:
            return None
        rows = await self._rows(
            'SELECT age_band, job, device FROM ai_tester_intro WHERE user_id=?', user_id)
        return {key: rows[0][key] for key in FIELDS} if rows else None

    async def get_many(self, user_ids):
        result = {}
        for user_id in dict.fromkeys(user_ids):
            intro = await self.get(user_id)
            if intro is not None:
                result[user_id] = intro
        return result

    async def save(self, user_id, *, age_band=None, job=None, device=None):
        if not isinstance(user_id, str) or INTRO_ID.fullmatch(user_id) is None:
            raise ValueError('intro_invalid')
        values = {'age_band': clean_intro(age_band), 'job': clean_intro(job),
                  'device': clean_intro(device)}
        if not any(value is not None for value in values.values()):
            raise ValueError('intro_empty')
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        await self._db.prepare(
            'INSERT INTO ai_tester_intro (user_id,age_band,job,device,created_at,updated_at) '
            'VALUES (?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET '
            'age_band=excluded.age_band, job=excluded.job, device=excluded.device, '
            'updated_at=excluded.updated_at'
        ).bind(user_id, values['age_band'], values['job'], values['device'], now, now).run()
        return values
