# Google AI Studio 무료 티어 실제 할당량 — 2026-10-09

**출처:** 사용자가 Google AI Studio의 [Rate limits 화면](https://aistudio.google.com/rate-limit)에서 제공한 표.

- 화면의 `0 / 15`처럼 **앞 숫자는 사용량**, 뒷 숫자는 **허용 한도**다. 아래 표는 허용 한도만 표시하며, 제공된 화면에서는 사용량이 모두 0이었다.
- **RPM=분당 요청**, **TPM=분당 입력 토큰**, **RPD=일일 요청**. 토큰 출력 최대치(`max_output_tokens`)와 전혀 다른 수치다.
- 한도 0은 **해당 화면에서 사용 가능 할당량 0**, 대시(—)는 **값 미표시**, 무제한은 원문 표시 그대로다.
- 이 수치는 **2026-10-09 화면 스냅샷**이다. 다른 프로젝트·유료 티어·향후 날짜의 한도를 의미하지 않는다.

## B14에 현재 등록된 Google 모델 4개

| B14 모델 ID | AI Studio 표시명 | RPM | 입력 TPM | RPD |
|---|---|---:|---:|---:|
| `google/gemini-3.1-flash-lite` | Gemini 3.1 Flash Lite | 15 | 250,000 | 500 |
| `google/gemini-3.5-flash-lite` | Gemini 3.5 Flash Lite | 15 | 250,000 | 500 |
| `google/gemma-4-26b-a4b-it` | Gemma 4 26B | 30 | 16,000 | 14,400 |
| `google/gemma-4-31b-it` | Gemma 4 31B | 30 | 16,000 | 14,400 |

Gemma 4의 AI Studio 화면명은 Gemma 4 26B와 Gemma 4 31B이다. B14에는 각각 `google/gemma-4-26b-a4b-it`와 `google/gemma-4-31b-it`로 등록되어 있다. **표시명 기반 매핑**이며 실제 제공자 upstream 매칭은 별도로 확인한다.

## Google AI Studio 무료 티어 모델 전체 한도

| AI Studio 모델 표시명 | 카테고리 | RPM | 입력 TPM | RPD |
|---|---|---:|---:|---:|
| Antigravity | 에이전트 | 60 | 100,000 | 100 |
| Deep Research Pro Preview | 에이전트 | 0 | 0 | 0 |
| Gemini 2 Flash | 텍스트 출력 모델 | 0 | 0 | 0 |
| Gemini 2 Flash Lite | 텍스트 출력 모델 | 0 | 0 | 0 |
| Computer Use Preview | 기타 모델 | 0 | 0 | 0 |
| Gemini 2.5 Flash | 텍스트 출력 모델 | 5 | 250,000 | 20 |
| Nano Banana (Gemini 2.5 Flash Preview Image) | 멀티모달 생성 모델 | 0 | 0 | 0 |
| Gemini 2.5 Flash Lite | 텍스트 출력 모델 | 10 | 250,000 | 20 |
| Gemini 2.5 Flash TTS | 멀티모달 생성 모델 | 3 | 10,000 | 10 |
| Gemini 2.5 Pro | 텍스트 출력 모델 | 0 | 0 | 0 |
| Gemini 2.5 Pro TTS | 멀티모달 생성 모델 | 0 | 0 | 0 |
| Gemini 3 Flash | 텍스트 출력 모델 | 5 | 250,000 | 20 |
| Nano Banana Pro (Gemini 3 Pro Image) | 멀티모달 생성 모델 | 0 | 0 | 0 |
| Gemini 3.1 Pro | 텍스트 출력 모델 | 0 | 0 | 0 |
| Nano Banana 2 (Gemini 3.1 Flash Image) | 멀티모달 생성 모델 | 0 | 0 | 0 |
| Gemini 3.1 Flash Lite | 텍스트 출력 모델 | 15 | 250,000 | 500 |
| Nano Banana 2 Lite (Gemini 3.1 Flash Lite Image) | 멀티모달 생성 모델 | 0 | 0 | 0 |
| Gemini 3.1 Flash TTS | 멀티모달 생성 모델 | 3 | 10,000 | 10 |
| Gemini 3.5 Flash | 텍스트 출력 모델 | 5 | 250,000 | 20 |
| Gemini 3.5 Flash Lite | 텍스트 출력 모델 | 15 | 250,000 | 500 |
| Gemini 3.5 Transcribe | Live API | 3 | 10,000 | 25 |
| Gemini 3.6 Flash | 텍스트 출력 모델 | 5 | 250,000 | 20 |
| Gemini 3.7 Flash | 텍스트 출력 모델 | 5 | 250,000 | 20 |
| Gemini 3.8 Flash | 텍스트 출력 모델 | 5 | 250,000 | 20 |
| Gemini 3.8 Flash Lite TTS | 멀티모달 생성 모델 | 3 | 10,000 | 10 |
| Gemini 3.8 Flash TTS | 멀티모달 생성 모델 | 3 | 10,000 | 10 |
| Gemini Embedding 1 | 기타 모델 | 100 | 30,000 | 1,000 |
| Gemini Embedding 2 | 기타 모델 | 100 | 30,000 | 1,000 |
| Gemini Nano Banana 2.1 | 미표시 | 0 | 0 | 0 |
| Gemini Omni 1.1 Flash | 멀티모달 생성 모델 | 0 | 0 | 0 |
| Gemini Omni Flash | 멀티모달 생성 모델 | 0 | 0 | 0 |
| Gemini Robotics ER 2 Preview | 기타 모델 | 5 | 250,000 | 20 |
| Gemma 4 26B | 기타 모델 | 30 | 16,000 | 14,400 |
| Gemma 4 31B | 기타 모델 | 30 | 16,000 | 14,400 |
| Lyria 3 Clip | 멀티모달 생성 모델 | 0 | 0 | 0 |
| Lyria 3 Pro | 멀티모달 생성 모델 | 0 | 0 | 0 |
| Veo 3 Fast Generate | 멀티모달 생성 모델 | 0 | — | 0 |
| Veo 3 Generate | 멀티모달 생성 모델 | 0 | — | 0 |
| Veo 3 Lite Generate | 멀티모달 생성 모델 | 0 | — | 0 |
| Gemini 2.5 Flash Native Audio Dialog | Live API | 무제한 | 1,000,000 | 무제한 |
| Gemini 3 Flash Live | Live API | 무제한 | 65,000 | 무제한 |
| Gemini 3.5 Live Translate | Live API | 무제한 | 20,000 | 무제한 |
| Gemini 3.5 Transcribe Live | Live API | 무제한 | 20,000 | 무제한 |
| Gemini 3.8 Live | Live API | 무제한 | 65,000 | 무제한 |
| Gemini 3.8 Live Extended Thinking | Live API | 무제한 | 65,000 | 무제한 |

## 도구별 무료 일일 한도 — 일반 추론 RPD와 분리

| 도구 | AI Studio 표시명 | 일일 허용 횟수 |
|---|---|---:|
| 맵 그라운딩 | Deep Research Pro Preview | 500 |
| 맵 그라운딩 | Gemini 2 Flash | 500 |
| 맵 그라운딩 | Computer Use Preview | 500 |
| 맵 그라운딩 | Gemini 2.5 Flash | 500 |
| 맵 그라운딩 | Gemini 2.5 Flash Lite | 500 |
| 맵 그라운딩 | Gemini 2.5 Pro | 0 |
| 맵 그라운딩 | Gemini 3 Flash | 0 |
| 맵 그라운딩 | Gemini 3.1 Pro | 0 |
| 맵 그라운딩 | Gemini 3.1 Flash Lite | 500 |
| 맵 그라운딩 | Gemini 3.1 Flash TTS | 500 |
| 맵 그라운딩 | Gemini 3.5 Flash | 0 |
| 맵 그라운딩 | Gemini 3.5 Flash Lite | 500 |
| 맵 그라운딩 | Gemini 3.5 Transcribe | 500 |
| 맵 그라운딩 | Gemini 3.6 Flash | 0 |
| 맵 그라운딩 | Gemini 3.7 Flash | 0 |
| 맵 그라운딩 | Gemini 3.8 Flash | 0 |
| 맵 그라운딩 | Gemini Robotics ER 2 Preview | 500 |
| 검색 그라운딩 | Gemini 2 | 1,500 |
| 검색 그라운딩 | Gemini 2.5 | 1,500 |
| 검색 그라운딩 | Gemini 3 | 0 |
| 검색 그라운딩 | Default | 1,500 |

**검색·맵 그라운딩 할당량은 별도 도구 한도이다.** 모델 텍스트 생성 RPD와 같은 항목으로 더하지 않는다.

이 수치는 B14 모델 최종 평가를 위한 **계정에서 확인한 기록**이며 모델 컨텍스트·출력 토큰 설정이나 운영 라우팅을 자동 변경하지 않는다.
