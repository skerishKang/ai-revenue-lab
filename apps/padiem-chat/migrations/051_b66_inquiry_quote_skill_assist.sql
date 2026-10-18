-- The assisted quote-form request (#3186) reuses member inquiries with one
-- additional category. SQLite cannot alter a CHECK constraint in place, so the
-- table is rebuilt with the same columns and a widened category set.
PRAGMA foreign_keys=OFF;
PRAGMA defer_foreign_keys=ON;

CREATE TABLE b66_member_inquiries_next (
  inquiry_id TEXT PRIMARY KEY CHECK (length(inquiry_id)=39),
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  category TEXT NOT NULL CHECK (category IN ('general','usage','billing','bug','other','quote_skill_assist')),
  subject TEXT NOT NULL CHECK (length(subject) BETWEEN 1 AND 120),
  body TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 3000),
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  delivered_at TEXT
);

INSERT INTO b66_member_inquiries_next
  (inquiry_id,user_id,category,subject,body,status,created_at,updated_at,delivered_at)
SELECT inquiry_id,user_id,category,subject,body,status,created_at,updated_at,delivered_at
FROM b66_member_inquiries;

DROP TABLE b66_member_inquiries;
ALTER TABLE b66_member_inquiries_next RENAME TO b66_member_inquiries;

CREATE INDEX IF NOT EXISTS idx_b66_member_inquiries_user ON b66_member_inquiries(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_b66_member_inquiries_status ON b66_member_inquiries(status, created_at DESC);

PRAGMA foreign_keys=ON;
