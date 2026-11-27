"""Shared local SQLite feedback store fixtures."""

from pathlib import Path
import sqlite3

from app.d1_sqlite import SqliteD1
from app.feedback_store import D1FeedbackStore
from _support.migrated_db_template import apply_copied_migrations as apply_migrations

OWNER = 'usr_' + 'a' * 32
OTHER = 'usr_' + 'b' * 32
BODY = 'fixture-private-feedback-body'


def database(path=':memory:', *, full=False):
    db = sqlite3.connect(str(path), isolation_level=None, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=OFF')
    if full:
        apply_migrations(db)
        db.execute('PRAGMA foreign_keys=OFF')
    else:
        db.execute("CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, display_name TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '')")
        for name in ('115_feedback.sql', '117_feedback_replies_ai_tester.sql', '119_chat_news.sql',
                     '123_product_news_version.sql', '126_ai_tester_intro.sql'):
            migration = Path(__file__).resolve().parents[2] / 'migrations' / name
            db.executescript(migration.read_text(encoding='utf-8'))
    for uid in (OWNER, OTHER):
        if full:
            db.execute("INSERT INTO users (id,auth_provider,provider_subject,email,display_name,picture_url,created_at,updated_at) "
                       "VALUES (?,'google',?,'fixture@example.test','','','','')", (uid, uid))
        else:
            db.execute('INSERT OR IGNORE INTO users (id) VALUES (?)', (uid,))
    return db, D1FeedbackStore(SqliteD1(db))
