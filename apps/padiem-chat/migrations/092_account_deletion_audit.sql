-- 계정 탈퇴 감사 기록 (#6659 3번 1단계).
--
-- 탈퇴 사실을 최소로 남긴다: 시각과 사용자 id의 SHA-256 해시뿐이다. 이메일,
-- 표시 이름, provider_subject 등 재식별 가능한 값은 절대 저장하지 않는다.
-- Additive only, idempotent.
CREATE TABLE IF NOT EXISTS account_deletion_audit (
    id TEXT PRIMARY KEY,
    user_id_hash TEXT NOT NULL,
    deleted_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_account_deletion_audit_deleted_at
    ON account_deletion_audit (deleted_at);
