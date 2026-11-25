# #8749 회의 캡처 화면 픽셀 측정 (2026-11-25)

- 대상 커밋: `f89521382779cd688c7659f920e64841cc01b46d` (`refactor/7811-meeting-capture-261125`)의 `apps/padiem-chat/static`과 `tools/chat_pixel_compare.py`·`tools/chat_pixel_scope.py`
- 측정 위치: COM2 임시 폴더(측정 후 삭제). 해당 트리만 옮겨 측정했고 전체 저장소는 옮기지 않음.
- 화면: `meeting-capture` 1개, 5테마 × 2폭(1440x950, 390x844) = 10조합

## 결과

| 항목 | 결과 | 파일 |
|---|---|---|
| (a) before/after 픽셀 | 최종 판정 0 (10/10). 단, `cinematic 390x844` 첫 쌍에서 35790px 차이가 나 재촬영 후 0이 됨 | `before_after_report.json` |
| (a) 제어쌍 | 0 (10/10), 첫 촬영 통과 | `control_report.json` |
| (a) 계산값 `#meetingNavButton` `color` | light `rgb(25, 25, 29)`, dark `rgb(237, 244, 250)`, padiem-glass `rgb(23, 32, 42)`, cinematic `rgb(247, 248, 250)`, padiem-home `rgb(26, 34, 48)` | 콘솔 출력 값 (계산값 도구는 한쪽 트리만 출력하므로 before/after 동일성은 픽셀 단계로 확인) |
| (b) 변조 검사 `--tamper-token=--meeting-capture-panel-edge --tamper-surface meeting-capture` | pixel **2938** (> 0, 노이즈 기준 8 초과, 검출 성공) | `tamper_report.json` |
| (c) 캡처 | 4장 저장 (10장 중 핵심 선택) | `captures/` |

## 확인된 제약

- 확인된 제약: `cinematic 390x844` 첫 쌍에서 35790px 차이가 발생했다. 도구 규칙에 따라 재촬영 후 0으로 통과했으나, 같은 커밋에서 간헐적 차이가 있다는 뜻이므로 애니메이션 안정화 여부는 별도 확인이 필요하다.
- 확인된 제약: 변조 옵션은 `--tamper-token --meeting-capture-panel-edge`처럼 공백으로 쓰면 argparse가 값을 받지 못한다(`--`로 시작하는 값). 같은 의미로 `--tamper-token=--meeting-capture-panel-edge`를 사용했다.
- 측정 중 COM2에는 측정 폴더(`C:\measure-7811`)만 만들었고, 측정 후 삭제했다. systemd, DB, 설정 파일은 변경하지 않았다.
