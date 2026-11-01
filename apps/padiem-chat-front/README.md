# padiem-chat-front 운영 설정

운영값 변경 후에는 `wrangler.toml`의 `[vars]`와 운영 변수 계약 시험을 함께 갱신한다. `wrangler.toml`에 선언된 `[vars]` 값은 `--keep-vars`로 보호되지 않으며 같은 이름의 운영값을 덮어쓴다.

`node --test test/worker.test.mjs`는 2026-11-01 확인한 비밀 제외 운영 변수 기준값과 설정 파일을 대조한다. 현재 운영값을 직접 대조할 때는 비밀을 제외한 변수만 JSON 객체로 `PADIEM_FRONT_LIVE_VARS_JSON`에 전달한다. 기준값 시험만 통과한 것은 이후 운영값의 변경 여부를 실시간으로 확인했다는 뜻이 아니다.
