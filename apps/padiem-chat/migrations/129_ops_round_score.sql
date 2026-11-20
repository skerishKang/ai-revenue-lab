-- #8035 ③ (#7718 흡수): AI 고객·실제 고객 회차의 '다시 올 점수'·'예쁜가' 점수.
-- 지금까지 거버넌스 운영일지에 손으로 적던 값을 앱 안에서 입력·수정·집계한다.
-- 한 행 = 한 고객 이름의 한 회차(날짜·출처 포함). 지우기는 행을 없애지 않고
-- hidden_at만 채운다 — 감사 기록(ops_audit_log, 128)과 함께 이력이 남는다.
-- 점수는 1~5 정수만, 메모는 짧은 글만. 계정 식별자·이메일은 담지 않는다.
CREATE TABLE IF NOT EXISTS ops_round_score (
    id TEXT PRIMARY KEY,
    persona_name TEXT NOT NULL CHECK(length(persona_name) BETWEEN 1 AND 120),
    round_no INTEGER NOT NULL CHECK(round_no BETWEEN 1 AND 9999),
    round_on TEXT NOT NULL CHECK(length(round_on) = 10),
    source TEXT NOT NULL CHECK(source IN ('ai', 'human')),
    return_score INTEGER NOT NULL CHECK(return_score BETWEEN 1 AND 5),
    pretty_score INTEGER NOT NULL CHECK(pretty_score BETWEEN 1 AND 5),
    memo TEXT NOT NULL DEFAULT '' CHECK(length(memo) <= 400),
    hidden_at TEXT,
    created_by TEXT NOT NULL CHECK(length(created_by) BETWEEN 1 AND 256),
    updated_by TEXT NOT NULL CHECK(length(updated_by) BETWEEN 1 AND 256),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(persona_name, round_no, round_on, source)
);
CREATE INDEX IF NOT EXISTS idx_ops_round_score_day ON ops_round_score (round_on DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_ops_round_score_persona ON ops_round_score (persona_name, round_on DESC);