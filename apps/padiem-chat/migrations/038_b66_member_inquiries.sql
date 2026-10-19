-- B66 operator inquiries are explicitly submitted by signed-in members.
-- No chat transcripts are implicitly forwarded. Apply this migration before rollout.
CREATE TABLE IF NOT EXISTS b66_member_inquiries (
  inquiry_id TEXT PRIMARY KEY CHECK (length(inquiry_id)=39),
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  category TEXT NOT NULL CHECK (category IN ('general','usage','billing','bug','other')),
  subject TEXT NOT NULL CHECK (length(subject) BETWEEN 1 AND 120),
  body TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 3000),
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  delivered_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_b66_member_inquiries_user ON b66_member_inquiries(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_b66_member_inquiries_status ON b66_member_inquiries(status, created_at DESC);

CREATE TABLE IF NOT EXISTS b66_inquiry_alert_delivery (
  inquiry_id TEXT NOT NULL REFERENCES b66_member_inquiries(inquiry_id) ON DELETE CASCADE,
  channel TEXT NOT NULL CHECK (channel IN ('telegram','discord','email')),
  delivered_at TEXT NOT NULL,
  PRIMARY KEY (inquiry_id,channel)
);
