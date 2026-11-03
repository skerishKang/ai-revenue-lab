-- #6695 후속(대표 요청 2026-11-04) — MCP 토큰이 한 연결로 여러 PC를 고를 수 있다.
--
-- 지금까지 padiem_mcp_tokens는 계정·PC·토큰만 바인딩했고(085·095), 모든 pc_* 도구는
-- 그 한 PC로만 갔다. 이제 동의 화면에서 "내 PC 전부" 또는 "고른 PC만"을 골라 토큰에
-- 새기고, 도구 호출이 device 인자로 대상 PC를 고른다.
--
-- device_scope: NULL은 이전에 발급된 단일 PC 토큰(기존 PAT·OAuth 토큰) — 토큰의
-- device_id만 허용하는 범위로 해석되어 기존 연결은 그대로 동작한다. 'all'은 소유자의
-- 연결 PC 전부, 'selected'는 device_scope_json에 새긴 PC 목록만 허용한다.
--
-- 같은 결정을 승인 코드 행에도 남긴다(코드→토큰 교환 때 그대로 이어 붙이기 위함).
-- 코드는 10분 수명이라 목록도 짧게 살지만, 토큰 행이 만기 전까지의 원본이다.
--
-- Additive only: 기존 행은 두 칸이 모두 NULL로 남고 아무 동작도 바뀌지 않는다.
ALTER TABLE padiem_mcp_tokens
  ADD COLUMN device_scope TEXT CHECK(device_scope IS NULL OR device_scope IN ('all','selected'));
ALTER TABLE padiem_mcp_tokens
  ADD COLUMN device_scope_json TEXT CHECK(device_scope_json IS NULL OR json_valid(device_scope_json));

ALTER TABLE padiem_mcp_oauth_codes
  ADD COLUMN device_scope TEXT CHECK(device_scope IS NULL OR device_scope IN ('all','selected'));
ALTER TABLE padiem_mcp_oauth_codes
  ADD COLUMN device_scope_json TEXT CHECK(device_scope_json IS NULL OR json_valid(device_scope_json));
