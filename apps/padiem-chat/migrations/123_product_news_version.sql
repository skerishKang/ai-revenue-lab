-- #7847: '새 소식'을 배포(버전)별로 묶어 보여주기 위한 version 열.
-- 형식은 'YYYY.MM.DD' 한 가지이며, 빈 값('')은 '그 밖의 소식'으로 묶인다.
-- 기존 행은 모두 빈 값으로 남는다(기본값만 얻는다).
ALTER TABLE product_news ADD COLUMN version TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS product_news_version ON product_news(version, number);
