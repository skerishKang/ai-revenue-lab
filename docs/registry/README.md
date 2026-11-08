# 비공개 모델 등록부 (padiem.models.private.v1)

#6828 2단계 ②. 실제 프로바이더·주소·모델·등급별 폴백 순서는 **공개 저장소에 두지 않습니다.**
이 디렉터리에는 형식(`models.schema.json`)과 자리표시자 예시(`models.example.json`)만 있습니다.

## 위치와 권한

| 항목 | 값 |
|---|---|
| 운영 파일 (컴2) | `/etc/padiem/registry/models-private.json`, 소유 `padiem:padiem`, 권한 `0640` |
| 경로 env | `PADIEM_MODELS_REGISTRY` (미설정 시 위 기본 경로) |
| 비상 덮어쓰기 | `PADIEM_MODELS_REGISTRY_OVERRIDE` — 지정 시 그 파일을 우선 |
| 백업 | 비공개 거버넌스 폴더 `registry/YYYYMMDD/models-private.json`(+sha256). 공개 저장소·공개 버킷 금지 |

로더(`packages/padiem-control-plane/padiem_control_plane/models_registry.py`)는 **다른 사용자가 읽을 수 있는 파일을 파싱 전에 거부**합니다(`registry_permissions_too_open`).

## 형식 (v1)

```json
{
  "version": "padiem.models.private.v1",
  "providers": {"<provider_id>": {"base_origin": "https://…", "allowed_hosts": ["…"], "credential_binding": "PADIEM_B14_CREDENTIAL_NN"}},
  "models": [{"id": "<provider_id>/<upstream>", "provider_id": "<provider_id>", "upstream_model": "…", "capabilities": ["chat"], "enabled": true}],
  "tiers": {"free": {"primary": "…", "fallback": ["…"]}, "plus": {}, "pro": {}, "max": {}}
}
```

- `credential_binding`은 **이름만** 받습니다. 값(키)은 지금처럼 env에만 둡니다.
- `tiers`가 `product_tier_routes.py`의 등급→경로 선언과 `tier_fallback.py`의 순서를 흡수합니다. 코드는 "등급 이름 → 경로"만 알고 식별자는 파일에서 받습니다.
- `free`/`plus`/`pro`/`max`는 필수, `admin`은 선택입니다.
- 검증: 참조 무결성(모델의 `provider_id` 존재, `tiers`가 가리키는 id 존재), `https` 강제, 자격증명 이름 형식, capability 어휘.

## 없을 때 (fail-closed)

- 파일 없음·권한 오류·스키마 위반: **빈 등록부(모델 0개)** 로 응답하고, 이미 성공한 로드가 있으면 그 스냅샷을 유지한 채 새 작업을 받지 않습니다.
- 로그에는 **파일 이름과 이유 코드만** 남깁니다(경로 전체·주소·식별자·값 없음).
- 공개 저장소의 값으로 되돌아가는 경로는 없습니다.

이유 코드: `registry_file_missing`, `registry_file_unreadable`, `registry_permissions_too_open`, `registry_document_invalid`, `registry_version_unsupported`, `registry_providers`, `registry_provider_origin`, `registry_provider_hosts`, `registry_provider_credential_binding`, `registry_models`, `registry_model_provider_mismatch`, `registry_model_capabilities`, `registry_tiers`, `registry_tier_names`, `registry_tier_unknown_model`, `registry_tier_primary_in_fallback`.

## 배포 순서 (롤백 지점 유지)

1. 이 로더·스키마·fixture를 머지한다. **동작 변화 없음**(아직 소비자가 읽지 않음).
2. 컴2에 실제 파일 배치 + `0640` 확인, `PADIEM_MODELS_REGISTRY` 지정.
3. B14 재배포 → readiness `models > 0` 확인 → 카나리 1회 호출.
4. 공개 저장소에서 값 제거(`b14_models.json`, `tier_fallback.py`, `product_tier_routes.py`). 문제가 생기면 3 이전 바이너리로 되돌리면 값이 아직 저장소에 있어 즉시 복구됩니다.

## 남은 연결 지점

v1 문서는 `b14_models.json`이 담던 표시 이름·컨텍스트·가격·출처까지 함께 담아야 합니다(그 파일을 대체하므로). B14의 `install_models()`는 기존 문서 형식(`schema_version:1`, `providers`/`models`/`groups`)을 받으므로, 배선 단계에서 v1 → 설치 문서 변환을 한 곳(`model_registry_file.install_from_private`)에 두고 `tiers`는 `tier_fallback` 대체로 읽습니다.
