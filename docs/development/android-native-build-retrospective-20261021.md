# Android Native 개발 문제점 및 9시간 실측 회고 (2026-10-21)

관련: [#5435](https://github.com/skerishKang/ai-revenue-lab/issues/5435), [PR #5436](https://github.com/skerishKang/ai-revenue-lab/pull/5436). 아래 개발 구간 시간은 LOCAL이 세션 DB와 산출물 mtime으로 측정·보고한 자료이며, 원시 로그를 이 문서 작성 시 독립 대조하지 않았다. (보완 섹션은 원본 로그와 세션 DB로 구대조했다.)

## 실제 소요 및 산출물

- 세션: 2026-10-20 22:29:34 ~ 2026-10-21 07:30:32 KST. **9시간 0분 58초**.
- React Native Chat·Claw 앱: `src/` 24개 파일, 4,302 LOC; PR 78개 파일 +19,242줄. Login/Chat/History/Settings/ClawStatusBar·공통 컴포넌트·내비게이션 구현.
- Android Release APK arm64-v8a 24,180,853 bytes(23.06 MB), SHA256 `B3B05B9349816F60177CE0B87DA05E876B8F36FC6F8AC9538A996EB3289657D6` (LOCAL 보고). TypeScript 오류 0건. PR 병합 SHA `734bfa91c69529389c2210ef484854737ab4647a`.
- 음성 Kotlin 모듈·바이너리 첨부 전송·실기기 E2E는 미완료. adb 기기 0대.

| 단계 | KST | LOCAL 보고 소요 | 내용 |
|---|---|---:|---|
| 환경 구축 | 22:29~22:46 | 17분 | JDK17, SDK36, NDK r27b, CMake 등 약 2.4GB |
| 서버 계약 추출 | 22:30~23:24 | 54분 | 기존 인증 handoff·Chat SSE·Claw·등급·음성 API |
| 툴체인 장애 | 23:24~02:50 | **3시간26분** | RN 0.88→0.86.3, SDK37, C: 디스크 고갈, Gradle OOM 2회, dependency |
| 앱 화면 구현 | 02:50~06:56 | 4시간06분 | 화면·컴포넌트·i18n·타입 오류 |
| 최종 APK 빌드 | 06:57~07:09 | 12분 | Release 빌드 |
| 검증·PR·병합 | 07:09~07:30 | 21분 | 해시, aapt2, CI, #5435/#5436 |

환경 구축과 계약 추출은 **시간대가 중첩**된다. 위 구간은 반올림돼 세션 전체와 완벽히 합산되지 않는다.

## 병목과 개선 대책

1. **최대 병목: 툴체인 3시간26분.** RN 버전·SDK 호환성을 초기화 전에 확인하고, 이미 작동하는 프로젝트의 고정 버전·lockfile을 재사용한다. RN 0.88→0.86.3 재시작 손실 LOCAL 추정 약 25분.
2. **C: 디스크 고갈:** SDK/NDK 최초 설치 위치가 원인. 향후 D: SDK/NDK·Gradle 캐시 경로를 먼저 확인하여 그대로 재사용한다. 반복 진단 손실 약 40분(LOCAL 추정).
3. **Gradle 실패:** 14분16초 + 5분05초 = 19분21초. 최초 OOM 원인을 로그로 확인하고 필요한 설정만 수정; 실패한 Release를 무작정 반복하지 않는다.
4. **병목 오진:** `-j1` 과잉 적용. 실제 구간은 C++ 약 3.5분, Metro 7분, D8 약 8.4분, 초기 코드 생성/컴파일 약 11.5분. 검증된 단계만 최적화한다.
5. **다운로드·빌드 대기:** Gradle 4회 총 62분06초, SDK/JDK/NDK 다운로드 약 25분, Maven artifacts 약 10분. LOCAL 총 대기 추정 약 1시간37분(18%), 비대기 약 7시간24분(82%). **비대기 시간은 순수 코딩 시간이 아니며 장애 진단을 포함한다.** 회피 가능 시간을 중복 합산하지 않는다.
6. **측정 착오 예방:** PR 생성→병합 2분21초는 개발 소요시간이 아니다. 최초 지시, 첫 코드 수정, 각 실패·복구, 빌드, PR 시간을 분리 기록한다.

## #5435 후속 개발 운영 원칙

- 기존 Android SDK, NDK, Gradle, React Native 버전, D: 설치 경로, 워밍된 캐시를 재사용. 정당한 실패 없이 SDK 재설치/프로젝트 재생성 금지.
- Kotlin `PadiemVoice`/AudioRecord 16kHz PCM16/TextToSpeech/`RECORD_AUDIO` 구현 → 기존 JS 음성 계약 연결 → 집중 검사 → Release 빌드.
- 파일 첨부는 서버 원본 계약(`POST /api/chat`, 4-byte BE header length + JSON header + 원본 바이트)을 실제 소스에서 재확인해 구현. Chat 스트리밍 첨부 422 문제를 우회하되 새로운 서버 경로는 만들지 않는다.
- 실기기 부재는 `LIVE_VERIFIED=NO`로 기록하고 구현 중단 사유로 삼지 않는다. x86_64/에뮬레이터 추가는 실제 검증 필요 시에만.
- 불필요한 전수 테스트와 반복 빌드를 줄이고 기능 구현·PR 산출물을 우선한다.

## 추가로 LOCAL에게 요청할 증거

세션 DB 타임스탬프의 기준 시간대, 산출물 mtime 목록, 네 번의 Gradle 실행 명령/성공·실패 로그, OOM·SDK37·C: 공간 부족 최초 증거, D: SDK/Gradle 캐시 실제 경로, 대기시간 중복 여부. 확인 자료가 없으면 미확인으로 표기하고 추정치를 관측치로 변경하지 않는다.

**결론:** 최초 Android 앱 구축 자체는 성과가 있지만 9시간 중 3시간26분의 툴체인 장애가 주요 개선 대상이다. 향후 반복 작업은 기능당 실제 소요시간과 장애 재발 여부로 평가한다.

---

## 보완: 원본 로그 교차 확인 결과 (2026-10-21 추가)

앞 문서는 LOCAL이 세션 DB와 산출물 mtime으로 측정한 **보고값**이었다. 이후 **원본 로그·세션 DB 파트·산출물과 독립 대조**해 아래를 확정했다. 앞 문단의 일부 서술은 이 보완에서 정정한다.

대조한 원본 자료:

| 자료 | 식별 | 용도 |
|---|---|---|
| 세션 DB | `session.time_created` / `time_updated` (id `ses_ea67f3881ffeebRHzfeOsqO3B2`) | 시작·종료 시각 |
| 세션 DB `part` | 도구 호출 원문·출력 | 실패 오류문, 명령문 |
| 1차 Gradle 로그 | `D:\Temp\opencode\gradle-baseline.log` (11,007B, 2026-10-20 23:34:01) | 1차 실패 |
| Gradle 설정 검사 로그 | `D:\Temp\opencode\gradle-check.log` (2,545B, 2026-10-21 02:49:19) | 설정 평가 성공 |
| 성공 빌드 로그 | `D:\Temp\opencode\gradle-build.log` (24,442B, 2026-10-21 07:09:09) | 성공 2회 |
| APK | `android/app/build/outputs/apk/release/app-release.apk` | 해시·패키지 |
| `.cxx` 오브젝트 67개 | `android/app/.cxx/**` mtime | C++ 컴파일 구간 |
| JS 번들 | `build/generated/assets/react/release/index.android.bundle` | 번들 구간 |

### 1. Gradle 실행 횟수 정정 — 4회가 아니라 5회

앞 문단의 "Gradle 4회"는 부정확하다. 실행은 **5회**였고, 그중 2회는 성공·2회는 실패·1회는 설정 검사 성공이다. 추가로 **로그가 덮어써져 소요시간을 확인할 수 없는 실패 실행이 최소 1회 더** 있었다.

| # | 시각 | 명령 | 소요 | 결과 | 확정된 실패 원인 |
|---|---|---|---|---|---|
| 1 | 10-20 23:26 | `:app:assembleDebug --stacktrace -PreactNativeArchitectures=arm64-v8a,x86_64` | 미확인(데몬 사망) | FAIL | C: 0바이트 → `%TEMP%` 21.78GB → `DaemonDisappearedException` |
| 2 | 10-21 02:4x | `:app:assembleDebug --stacktrace` (2 ABI) | **14분 16초** | FAIL | `':react-native-nitro-modules' could not be found` (설정 평가 단계) |
| 3 | 10-21 03:1x | `:app:assembleDebug --stacktrace` (2 ABI) | **5분 05초** | FAIL | clang++ `LLVM ERROR: out of memory` |
| 4 | 10-21 03:0x~05:30 | `:app:assembleRelease --stacktrace -PreactNativeArchitectures=arm64-v8a`, `CMAKE_BUILD_PARALLEL_LEVEL=1` | **30분 46초** | SUCCESS | — |
| 5 | 10-21 06:57 | 동일(캐시 보존) | **11분 59초** | SUCCESS | — |
| 별도 | 10-21 02:43~03:11 | `gradlew help` (설정 검사) | 12초~4분04초 | SUCCESS | — |
| 미확인 | 02:4x~03:0x | debug 재시도 1회 이상 | **미확인** | FAIL | 로그 덮어써짐 |

**앞 문단 정정**: "Gradle 실패: 14분16초 + 5분05초"에서 **14분16초는 OOM이 아니라 nitro peer 설정 평가 실패**이고, OOM은 5분05초때다. 앞 문단 §병목 3항은 두 원인을 분리해 기술한다.

### 2. SDK 37 부재 — 원본 출력

RN 0.88.0 템플릿 `android/build.gradle`:

```
buildToolsVersion = "37.0.0"
compileSdkVersion = 37
targetSdkVersion = 36
ndkVersion = "27.1.12297006"
```

`sdkmanager --list` 원본 출력(2026-10-20 23:01:03):

```
build-tools;36.0.0   | 36.0.0  | Android SDK Build-Tools 36
platforms;android-36 | 2       | Android SDK Platform 36
platforms;android-35 | 2       | Android SDK Platform 35
platforms;android-36-ext18 / -ext19
```

`platforms;android-37` **미출현**이므로 `compileSdkVersion = 37`은 만족시킬 수 없다. 비교 확인한 0.86.3 / 0.83.10 / 0.81.6 템플릿은 모두 `compileSdk 36 / buildTools 36.0.0 / ndk 27.1.12297006`이었다.

### 3. C: 용량 고갈 — 최초 증거와 사용처 분리

2026-10-20 23:25:55, 모든 도구 호출이 동일하게 실패했다.

```
ENOSPC: no space left on device, write
```

23:27:56 드라이브 실측:

```
Name  FreeGB  UsedGB
C       0.00  118.27
D    1340.05  522.96
```

23:28:13 사용처 실측:

```
      2.63 GB  C:\Users\user\AppData\Local\Android
     21.78 GB  C:\Users\user\AppData\Local\Temp
      0.17 GB  C:\Users\user\.gradle
      0.80 GB  C:\Users\user\AppData\Local\Google
      1.66 GB  C:\Users\user\AppData\Local\Programs
```

1차 Gradle 실행 로그(`gradle-baseline.log` 62~73행)는 **OOM이 아니라 디스크 고갈에 의한 데몬 사망**임을 보여준다.

```
* What went wrong:
Gradle build daemon disappeared unexpectedly (it may have been killed or may have crashed)
* Exception is:
org.gradle.launcher.daemon.client.DaemonDisappearedException: ...
```

같은 로그 59행의 데몬 기동 파라미터: `javaHome=D:\PADIEM\tools\jdk\jdk-17.0.20.1+1, javaVersion=17, daemonOpts=-Xmx3072m` — **1차 실패 시점의 `-Xmx3072m`은 RAM 대비 과대**였다.

**앞 문단 정정**: 1차 실패 원인은 "Gradle 중간 산출물"만이 아니라 **SDK/NDK 2.63GB가 C: 기본 SDK 루트에 설치된 것** + 그 첫 Gradle 실행이 `%TEMP%`에 남긴 산출물 21.78GB의 합이다. `%TEMP%`이 지배적이지만, SDK가 처음부터 C:에 들어간 것이 원인의 시작점이다.

### 4. clang OOM — 원본 오류와 RAM 실측

```
Execution failed for task ':app:buildCMakeDebug[arm64-v8a]'.
  FAILED: rnasyncstorage_autolinked_build/.../EventEmitters.cpp.o
  LLVM ERROR: out of memory
  Allocation failed
  Exception Code: 0xC000001D
```

동일 시점 RAM 실측: `TotalRAM_GB: 15.91` / `FreeRAM_GB: 1.53`. 점유는 `vmmem`(WSL) 2.38GB · 에이전트 프로세스 3개 2.59GB · Gradle 데몬 1.28GB · Memory Compression 1.00GB.

**해결책은 병렬도 축소가 아니라 variant 변경이었다.** RN **debug** AAR은 디버그 심볼을 포함해 의존 모듈도 `-g`로 컴파일되고, clang이 libc++ 헤더를 파싱하며 디버그 정보를 생성하는 순간 1개 프로세스가 여유 RAM(1.53GB)을 초과한다. `assembleRelease` AAR에는 `-g`가 없어 TU당 메모리 요구가 크게 낮아진다. `-j1`은 그 뒤에 추가된 과잉 처치이며 **1.5분만 절약**했다.

### 5. 서드파티 네이티브 모듈 2종의 Gradle 9 비호환 — 원본 오류

`react-native-audio-recorder-player@4.5.0` (설정 평가 단계):

```
* What went wrong:
A problem occurred evaluating project ':react-native-audio-recorder-player'.
> Project with path ':react-native-nitro-modules' could not be found in project ':react-native-audio-recorder-player'.
```

`react-native-tts@4.1.1` (최신판):

```
Caused by: org.gradle.internal.metaobject.AbstractDynamicObject$CustomMessageMissingMethodException:
Could not find method jcenter() for arguments [] on repository container of type
org.gradle.api.internal.artifacts.dsl.DefaultRepositoryHandler
```

Gradle 9에서 `jcenter()`가 제거된 것이 원인이다. **Gradle 9.x를 쓰는 환경에서는 서드파티 네이티브 모듈을 도입하기 전에 저장소 API 호환과 C++ peer 존재를 확인**해야 한다. 이번에는 서버가 STT·TTS 공급사를 소유하므로 앱에 키가 필요 없고, 자체 Kotlin 모듈 1개로 mic+TTS를 함께 구현하는 편이 리스크·의존성 모두 낮다.

### 6. 실제 병목 — 산출물 mtime 역추적 (성공 빌드 30분 46초)

| 구간 | 소요 | 근거 |
|---|---|---|
| Gradle 설정 + AAR transform + 코드생성 + Java/Kotlin 컴파일 | 11.5분 | 빌드 시작 ~ C++ 첫 오브젝트 |
| **C++ 컴파일 (ninja, `-j1`)** | **3.5분** | 63개 `.o` mtime 05:10:34 → 05:14:02 |
| native lib 병합 | 0.7분 | 05:14:02 → 05:14:46 |
| **Metro 번들 + Hermes 바이트코드** | **6.9분** | 05:14:46 → 05:21:39 |
| **D8 dex + 패키징 + 서명** | **8.4분** | 05:21:39 → 05:30:00 |

성공 구간 내 네이티브 모듈 산출물 **1,526개** 분포:

| 모듈 | 파일 수 | 비중 |
|---|---:|---:|
| **react-native-screens** | **1,125** | 74% |
| react-native-gesture-handler | 241 | 16% |
| react-native-safe-area-context | 68 | 4% |
| @react-native-documents/picker | 52 | 3% |
| @react-native-async-storage/async-storage | 40 | 3% |

**C++ 컴파일은 병목이 아니었다(3.5분).** 실제 병목 3곳(코드생성·Kotlin 11.5분 / Metro 6.9분 / D8 dex 8.4분)은 모두 `react-native-screens` 1개가 지배한다. 앞 문단 §병목 4항이 지적한 `-j1` 과잉 적용이 맞다.

### 7. 현재 정상 동작하는 개발 환경 (재사용 대상)

| 구성물 | 버전 |
|---|---|
| JDK | Eclipse Temurin **17.0.20.1+1** |
| Android SDK | platform **36**, build-tools **36.0.0** |
| NDK | **27.1.12297006** |
| CMake | **3.22.1** |
| Gradle | **9.3.1** (wrapper) |
| React Native | **0.86.3** (React 19.2.3) |
| New Architecture / Hermes / ABI | `newArchEnabled=true` / `hermesEnabled=true` / `arm64-v8a` (빌드 시) |

`android/gradle.properties` 확정값 (OOM 재발 방지 포함):

```properties
org.gradle.jvmargs=-Xmx1600m -XX:MaxMetaspaceSize=512m -Dfile.encoding=UTF-8
org.gradle.workers.max=2
org.gradle.parallel=false
org.gradle.daemon=true
kotlin.daemon.jvmargs=-Xmx1024m
reactNativeArchitectures=arm64-v8a,x86_64
newArchEnabled=true
hermesEnabled=true
edgeToEdgeEnabled=false
```

`Xmx3072m` → `Xmx1600m` 하강이 데몬 OOM-kill 회피에 효과적이었다.

**재사용할 캐시** (경로는 로컬 개발머신 기준이며 상세는 비공개 운영 문서에 둔다):

| 대상 | 크기 | 비고 |
|---|---:|---|
| Gradle caches + wrapper dists | 5,471 MB + 145 MB | SDK·NDK·Kotlin·Maven 전부 포함 |
| Android SDK (platform 36 / build-tools 36 / NDK r27b / CMake) | 2,829 MB | 재설치 금지 |
| JDK 17 | 303 MB | 재설치 금지 |
| npm cache | 20,275 MB | |
| 프로젝트 `android/app/build` | 563 MB | **`gradle clean` 금지** |
| 프로젝트 `android/app/.cxx` | 58 MB (67 objects) | **`gradle clean` 금지** |

캐시 보존 상태의 증분 빌드는 **11분 59초**, 초기 상태는 **30분 46초**였다.

### 8. 재발 방지 실행 순서

1. **SDK/NDK/JDK를 처음부터 D: 경로에 설치**하고 `TEMP`/`TMP`/`TMPDIR`·`ANDROID_HOME`·`GRADLE_USER_HOME`·`NPM_CONFIG_CACHE`를 모두 D:로 지정한 뒤 첫 Gradle을 실행한다. C: 기본 SDK 루트(`%LOCALAPPDATA%\Android\Sdk`)를 쓰지 않는다.
2. **RN 버전을 초기화 전에 결정**한다. `sdkmanager --list`로 `platforms;android-XX` 출현을 확인하고, 이미 설치된 SDK가 충족하는 안정 브랜치를 고른다.
3. **설정 검사를 먼저** 한다(`gradlew help`, 12초). 이 단계에서 `jcenter()`·nitro peer 같은 설정 평가 오류가 드러난다.
4. **debug를 시도하지 않는다.** `assembleRelease` + 단일 ABI로 빌드한다. OOM이 나면 병렬도 축소 전에 variant를 바꾼다.
5. **`gradle clean`을 하지 않는다.** 증분 빌드를 유지한다.
6. **실패한 빌드 로그를 덮어쓰기 전에 별도 파일로 보존한다.** 이번에 2회분의 로그가 덮어써져 소요시간 일부가 미확인 처리되었다.
7. **병목은 측정한다.** 산출물 mtime로 구간을 나누고, 추정으로 병목을 단정하지 않는다.
8. **기기 부재는 `LIVE_VERIFIED=NO`로 기록**하고 구현을 계속한다. 기기 부재로 빌드를 반복하지 않는다.

### 9. 미확인 항목 (명시)

- 1차 Gradle 실행의 정확한 소요시간 — 로그에 `BUILD ... in ...` 행이 없고 데몬 로그로 끝났다.
- 02:4x~03:0x 사이 추가 debug 실패 실행의 횟수·소요시간·원인 — 로그 덮어쓰기로 소실.
- clang이 1개 TU에서 필요로 하는 정확한 메모리 — 측정하지 않았으며, 관측된 실패 경로로부터의 판단이다.
- 단계 경계값(환경 구축 17분, 계약 추출 54분, 화면 구현 4시간06분 등)은 산출물 mtime에서 근사한 값이다.
- SDK/JDK/NDK 다운로드 25분, Maven artifact 10분, 재진단 손실 40분, RN 재시도 손실 25분은 **추정**이며 앞 문단 §병목 5항의 대기/비대기 18%/82%도 이 추정에 의존한다.
