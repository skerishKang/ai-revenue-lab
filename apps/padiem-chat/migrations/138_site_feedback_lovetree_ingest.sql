-- #7690: Lovetree 서버-서버 의견 수신용 외부 식별 열만 추가한다.
-- 기존 행·공개 접수(miraen-home)에는 손대지 않고, 새 열은 모두 NULL 허용이다.
ALTER TABLE site_feedback ADD COLUMN external_feedback_id TEXT;
ALTER TABLE site_feedback ADD COLUMN external_title TEXT;
ALTER TABLE site_feedback ADD COLUMN external_category TEXT;
ALTER TABLE site_feedback ADD COLUMN external_account_subject_id TEXT;
ALTER TABLE site_feedback ADD COLUMN external_is_ai_customer INTEGER CHECK (external_is_ai_customer IN (0, 1));
ALTER TABLE site_feedback ADD COLUMN external_append TEXT;
ALTER TABLE site_feedback ADD COLUMN external_append_created_at TEXT;
ALTER TABLE site_feedback ADD COLUMN external_created_at TEXT;
ALTER TABLE site_feedback ADD COLUMN external_status TEXT;
ALTER TABLE site_feedback ADD COLUMN external_status_created_at TEXT;
CREATE UNIQUE INDEX site_feedback_external_unique
    ON site_feedback(site, external_feedback_id)
    WHERE external_feedback_id IS NOT NULL;
