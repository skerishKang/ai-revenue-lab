-- #8105: 운영센터 알림 대기함 — 새 의견·회차 점수가 들어오면 짧게 알린다.
-- B66 회원 문의 알림과 같은 모양: 채널별 영수증이 있어 재시도해도 같은 채널로
-- 두 번 가지 않는다. 채널 값이 없으면 조용히 쌓아만 둔다.
-- 본문·이메일·회원 식별자는 담지 않는다 — 종류·분류·대상 번호만 담는다.
CREATE TABLE IF NOT EXISTS ops_alert_outbox (
    alert_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('product_feedback', 'site_feedback', 'round_score')),
    target_id TEXT NOT NULL CHECK (length(target_id) BETWEEN 1 AND 128),
    label TEXT NOT NULL CHECK (length(label) BETWEEN 1 AND 40),
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    UNIQUE (kind, target_id)
);
CREATE INDEX IF NOT EXISTS idx_ops_alert_outbox_pending
    ON ops_alert_outbox (created_at ASC, alert_id ASC);

CREATE TABLE IF NOT EXISTS ops_alert_delivery (
    alert_id TEXT NOT NULL REFERENCES ops_alert_outbox(alert_id) ON DELETE CASCADE,
    channel TEXT NOT NULL CHECK (channel IN ('telegram', 'discord', 'email')),
    delivered_at TEXT,
    failed_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    PRIMARY KEY (alert_id, channel)
);
CREATE INDEX IF NOT EXISTS idx_ops_alert_delivery_channel
    ON ops_alert_delivery (channel, delivered_at DESC);