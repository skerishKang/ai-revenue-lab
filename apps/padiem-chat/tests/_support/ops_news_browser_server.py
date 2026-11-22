"""Local HTTP adapter for browser tests of the real operations news handlers."""
from __future__ import annotations

import asyncio
import http.server
import json
import sqlite3
import threading
from pathlib import Path
from urllib.parse import urlsplit

from app.d1_sqlite import SqliteD1
from app.feedback_store import D1FeedbackStore
from app.news_store import D1NewsStore
from app.ops_audit_store import OpsAuditStore
from app.ops_news_routes import admin_news_create, admin_news_list, admin_news_update
from _support.ops_audit_helpers import OTHER, request


def start_news_server(path: Path, now: str):
    directory = Path(__file__).resolve().parents[2] / 'static'
    news_calls = []

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(directory), **kwargs)

        def log_message(self, *_args):
            pass

        def respond(self, status, raw):
            self.send_response(status)
            self.send_header('content-type', 'application/json')
            self.send_header('content-length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def api(self, method):
            parts = urlsplit(self.path)
            if parts.path == '/api/admin/session':
                body = {'ok': True, 'authenticated': self.server.admin,
                        'role': 'ADMIN' if self.server.admin else None,
                        'capabilities': {'admin_hub': True, 'chat_admin': True}
                        if self.server.admin else {}}
                self.respond(200, json.dumps(body).encode())
                return
            if not parts.path.startswith('/api/admin/news'):
                self.respond(200, b'{"ok":true,"feedback":[],"audit":[],"members":[]}')
                return
            news_calls.append((method, parts.path))
            length = int(self.headers.get('content-length') or 0)
            data = json.loads(self.rfile.read(length)) if length else None
            conn = sqlite3.connect(str(path), isolation_level=None)
            conn.row_factory = sqlite3.Row
            try:
                adapter = SqliteD1(conn)
                req = request(D1FeedbackStore(adapter), method=method,
                              user=OTHER if self.server.admin else None,
                              path=parts.path, body=data)
                req.app.state.news_store = D1NewsStore(adapter, now=lambda: now)
                req.app.state.ops_audit_store = OpsAuditStore(adapter)
                handler = {'GET': admin_news_list, 'POST': admin_news_create,
                           'PATCH': admin_news_update}[method]
                if method == 'PATCH':
                    req.scope['path_params'] = {'number': int(parts.path.rsplit('/', 1)[1])}
                res = asyncio.run(handler(req))
                self.respond(res.status_code, res.body)
            finally:
                conn.close()

        def do_GET(self):
            if self.path.startswith('/api/'):
                self.api('GET')
            else:
                super().do_GET()

        def do_POST(self):
            self.api('POST')

        def do_PATCH(self):
            self.api('PATCH')

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.admin = False
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, news_calls
