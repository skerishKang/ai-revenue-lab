-- #8149: 채널별 포기 시각 — 시도 상한·만료에 도달한 채널을 표시한다.
-- 새 컬럼만 추가한다. 기존 영수증·시도 횟수는 그대로 읽는다.
ALTER TABLE ops_alert_delivery ADD COLUMN abandoned_at TEXT;
