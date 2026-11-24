-- 러브트리에서 넘어온 의견의 보낸 사람 표시 이름(닉네임)만 추가한다.
-- 이메일·소개는 받지 않는다. 기존 행은 NULL로 두고 운영센터는 'AI 고객'·'사람 고객'으로 보인다.
ALTER TABLE site_feedback ADD COLUMN external_account_name TEXT;
