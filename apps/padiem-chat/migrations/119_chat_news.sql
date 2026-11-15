-- 119: Chat '새 소식'(버전 노트) — #7718 2단계.
-- 공개 항목이고 쉬운 말만 저장한다. 사용자 이름은 어디에도 저장하지 않는다.
-- 고친 것의 출처는 'AI 테스터가 찾아 준 것'/'사용자 의견으로 고친 것'으로만 구분한다(없음 허용).
CREATE TABLE IF NOT EXISTS product_news (
    number INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK(kind IN ('improved','fixed')),
    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 120),
    detail TEXT NOT NULL CHECK(length(detail) BETWEEN 1 AND 1000),
    source TEXT NOT NULL CHECK(source IN ('ai_tester','user','none')),
    published_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS product_news_recent ON product_news(published_at DESC, number DESC);
-- 의견(product_feedback)과 새 소식 항목을 잇는 칸. 항목 하나를 여러 의견이 가리킬 수 있다.
ALTER TABLE product_feedback ADD COLUMN news_number INTEGER REFERENCES product_news(number);
-- 로그인 사용자가 마지막으로 새 소식을 본 시각. 이후에 공개된 항목이 '안 본 새 항목'이다.
ALTER TABLE users ADD COLUMN news_read_at TEXT;
