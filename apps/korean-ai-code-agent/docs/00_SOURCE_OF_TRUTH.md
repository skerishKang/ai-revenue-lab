# Padiem Claw Source of Truth

## Identity

```text
BUSINESS_ID = B54
PRODUCT_NAME = Padiem Claw
PRODUCT_FAMILY = Padiem Agents
CANONICAL_CODE_PATH = apps/korean-ai-code-agent/**
NEW_BUSINESS_NUMBER = NO
```

`Padiem Agent`는 일반명/제품군 설명으로 사용한다. 사용자에게 노출되는 대표 실행형 제품명은 `Padiem Claw`다.

## Authority order

1. merged GitHub source and reviewed Markdown
2. accepted GitHub architecture/product issues
3. exact-head PR code + CI evidence
4. Drive Google Docs mirror
5. HTML overview/landing copy

Draft PR이나 working branch는 미래 계약 후보이지 main보다 높은 권위가 아니다.

## B65 correction

과거 Drive에 생성된 `B65_PADIEM_AGENT`와 charter는 초기 working artifact였으며 canonical business assignment가 아니다. B54 제품 결정을 발견한 뒤 B65 신설 방침은 철회되었다. 해당 자료는 삭제하지 않고 `SUPERSEDED` evidence로 보존한다.

## Change policy

- 제품 경계 변경: Issue → branch → reviewed PR.
- P01/B14/B62/Control Plane 권위 변경: 각 owner plane의 별도 Issue/PR.
- 문서와 코드가 충돌하면 코드/merged contract를 우선하고 문서를 reconciliation한다.
- secret, credential, provider key, raw private reasoning은 문서/HTML/evidence에 기록하지 않는다.
