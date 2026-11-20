"""In-memory workspace storage provider doubles."""
from __future__ import annotations


class MemoryMetadata:
    def __init__(self):
        self.rows = {}
        self.deleted = []

    async def insert(self, metadata):
        self.rows[metadata.document_id] = metadata

    async def get_active(self, document_id):
        return self.rows.get(document_id)

    async def get_active_owned(self, document_id, user_id):
        row = self.rows.get(document_id)
        return row if row is not None and row.user_id == user_id else None

    async def mark_deleted(self, document_id, deleted_at):
        self.rows.pop(document_id, None)
        self.deleted.append((document_id, deleted_at))


class R2Object:
    def __init__(self, body):
        self.body = body


class MemoryR2:
    def __init__(self):
        self.objects = {}
        self.put_calls = []
        self.delete_calls = []

    async def put(self, key, body, **kwargs):
        self.put_calls.append((key, bytes(body), kwargs))
        self.objects[key] = bytes(body)

    async def get(self, key):
        body = self.objects.get(key)
        return None if body is None else R2Object(body)

    async def delete(self, key):
        self.delete_calls.append(key)
        self.objects.pop(key, None)
