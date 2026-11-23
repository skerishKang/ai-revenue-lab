-- #7690 역방향: 운영센터 답글·상태를 러브트리로 보내는 outbox. 새 표만 만든다.
-- 받는 계약(CTO 댓글): eventKey 멱등, 서명된 POST /api/ops-feedback/ingest,
-- 2xx 완료 / 4xx 실패 / 5xx만 재시도(1분·5분·30분·2시간·12시간).
-- 정방향으로 받아서 바뀐 상태는 넣지 않는다(되돌이 금지): 적재는
-- 운영센터 화면(답글·상태 변경) 경로에서만 한다.
CREATE TABLE IF NOT EXISTS lovetree_ops_outbox (
    event_key TEXT PRIMARY KEY,
    feedback_id TEXT NOT NULL CHECK (length(feedback_id) BETWEEN 1 AND 64),
    external_feedback_id TEXT NOT NULL CHECK (length(external_feedback_id) BETWEEN 1 AND 32),
    kind TEXT NOT NULL CHECK (kind IN ('reply', 'status')),
    reply_id TEXT,
    reply_body TEXT CHECK (reply_body IS NULL OR length(reply_body) BETWEEN 1 AND 2000),
    reply_created_at TEXT,
    status TEXT CHECK (status IN ('received', 'reviewing', 'fixed', 'later')),
    created_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_attempt_at TEXT,
    sent_at TEXT,
    failed_at TEXT,
    last_status_code INTEGER,
    last_error TEXT,
    CHECK (
        (kind = 'reply' AND reply_id IS NOT NULL AND reply_body IS NOT NULL
            AND reply_created_at IS NOT NULL AND status IS NULL)
        OR (kind = 'status' AND status IS NOT NULL AND reply_id IS NULL
            AND reply_body IS NULL AND reply_created_at IS NULL)
    )
);
CREATE INDEX IF NOT EXISTS idx_lovetree_ops_outbox_pending
    ON lovetree_ops_outbox (created_at ASC, event_key ASC)
    WHERE sent_at IS NULL AND failed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_lovetree_ops_outbox_feedback
    ON lovetree_ops_outbox (feedback_id, created_at DESC, event_key DESC);
