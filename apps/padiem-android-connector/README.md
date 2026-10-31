# Padiem Connector — Android 기초 앱

스마트폰에서 사용자가 허용한 폴더를 고르고, 그 폴더의 파일 목록과 UTF-8 TXT 내용을
앱 화면에서 확인하는 Android 기초 앱입니다. 이번 단계는 **스마트폰 내부 열람만** 지원합니다.

- 패키지명: `com.padiem.connector`
- 버전: `0.1.0` (versionCode 1)
- 최소 Android: 8.0(API 26)
- 대상 Android: 16(API 36)
- 언어: Kotlin, Android Views/XML
- 저장소 접근: Android Storage Access Framework(SAF)만 사용
- 서버 연결: **아직 연결되지 않음** (등록·Chat/Claw 연동 코드 없음)
- 네트워크 권한: 없음

## 이번 범위

- 시스템 폴더 선택 화면(`ACTION_OPEN_DOCUMENT_TREE`)으로 허용 폴더 선택
- 선택한 폴더의 바로 아래 파일 목록 표시(하위 폴더 제외, 최대 300개 표시)
- `.txt` 파일을 선택하면 UTF-8로 디코딩해 화면에 표시(최대 128 KB)
- 영구 URI 권한을 저장해 앱을 다시 열어도 같은 폴더 재사용
- 접근 권한 취소, 폴더 없음, 파일 삭제, 읽기 실패를 서로 다른 메시지로 표시
- 폴더 선택 해제 시 저장된 영구 권한도 해제

이번 범위가 아닌 것: 서버 등록, Chat/Claw 연동, 파일 업로드, 파일 쓰기/삭제,
전체 저장소 접근, 접근성 서비스, 루트 권한, 하위 폴더 탐색, Google Play 출시.

## 빌드

필요 도구:

- JDK 17
- Android SDK Platform 36, Build-Tools 35.0.0 이상
- Android Studio(최신 안정판) 또는 명령줄 Gradle wrapper

```bash
cd apps/padiem-android-connector
./gradlew :app:assembleDebug
```

디버그 APK: `app/build/outputs/apk/debug/app-debug.apk`

서명된 릴리스 테스트 APK를 만들려면 프로젝트 루트에 **커밋하지 않는**
`keystore.properties`를 두고 `assembleRelease`를 실행합니다.

```properties
storeFile=E:/path/to/test-keystore.jks
storePassword=...
keyAlias=...
keyPassword=...
```

```bash
./gradlew :app:assembleRelease
```

`keystore.properties`, `*.jks`, `local.properties`는 `.gitignore`에 포함되어 있습니다.
테스트 서명 키는 공개 저장소·이슈·로그에 올리지 않습니다. Play 출시용 키가 아닙니다.

`local.properties`에는 Android SDK 경로를 지정합니다.

```properties
sdk.dir=C\:/Users/<사용자>/AppData/Local/Android/Sdk
```

## 스마트폰 설치 방법 (쉬운 순서)

### 방법 A — USB와 adb

1. 스마트폰에서 **설정 > 휴대전화 정보 > 소프트웨어 정보**를 눌러 빌드 번호를 7번 탭해
   개발자 옵션을 켭니다.
2. **설정 > 개발자 옵션 > USB 디버깅**을 켭니다.
3. USB 케이블로 PC와 연결하고 폰 화면의 "USB 디버깅 허용"을 눌러 허용합니다.
4. PC에서 아래 명령을 실행합니다.

```bash
adb install -r PadiemConnector-0.1.0-test.apk
```

### 방법 B — APK 파일을 폰으로 옮기기

1. APK 파일을 USB, 메신저, 클라우드 등으로 스마트폰에 옮깁니다.
2. 폰의 **파일** 앱(또는 다운로드 알림)에서 APK를 탭합니다.
3. "출처를 알 수 없는 앱 설치" 안내가 나오면, 파일 앱에 대해 **허용**을 선택합니다.
   (Android 8 이상은 앱별 설치 허용 방식입니다.)
4. 설치를 누릅니다. 테스트용 APK이므로 Play Protect 경고가 나올 수 있습니다.
5. 이미 다른 서명 키로 설치된 같은 패키지가 있다면 먼저 삭제한 뒤 설치합니다.

## 사용 순서

1. 앱을 엽니다. 서버 연결 상태가 **"아직 연결되지 않음"** 으로 표시되는지 확인합니다.
2. **폴더 선택**을 누릅니다.
3. 시스템 폴더 선택 화면에서 허용할 폴더를 엽니다.
   Android 11 이상에서는 내부 저장소 루트와 `Download` 루트 자체는 선택할 수 없으므로,
   `Documents/PadiemTest`처럼 그 안의 폴더를 선택합니다.
4. 아래쪽 **이 폴더 사용**을 누르고 확인 대화상자에서 **허용**을 누릅니다.
5. 앱에 폴더 이름과 파일 목록이 표시됩니다.
6. `.txt` 파일을 탭하면 아래 **TXT 내용** 영역에 UTF-8 본문이 표시됩니다.
7. 앱을 완전히 닫았다가 다시 열어도 같은 폴더의 목록이 다시 표시됩니다.
8. **폴더 선택 해제**를 누르면 저장된 권한과 선택 상태가 지워집니다. **새로고침**은 목록을 다시 읽습니다.

### 오류 표시

- **읽기 권한 취소됨**: 시스템 설정에서 앱의 폴더 권한이 취소된 상태입니다. 폴더를 다시 선택합니다.
- **폴더를 찾을 수 없습니다**: 선택한 폴더가 삭제되었거나 이동했습니다.
- **파일이 삭제되었거나 접근할 수 없습니다**: 목록을 읽은 뒤 파일이 사라진 경우입니다. 새로고침합니다.
- **파일을 읽지 못했습니다**: 제공자 오류·I/O 오류입니다. 잠시 후 다시 시도합니다.

## 검증

- JVM 단위 테스트 18개 통과: UTF-8/BOM/잘린 멀티바이트 문자, 크기 표시, TXT 판별, 오류 분류
- Android Lint: 오류 0건(경고는 비차단 항목)
- 서명 APK: APK Signature Scheme v2/v3 검증
- 에뮬레이터(Android 16, API 36): 폴더 선택, 파일 목록, TXT 본문, 빈 파일·비 TXT·대용량 잘림 안내,
  파일 삭제 오류, 강제 종료 후 권한 재사용, 권한 취소 표시, 새로고침, 선택 해제를 확인했습니다.
- 권한 취소 상태는 디버그 빌드에만 포함되는 `DebugRevokeReceiver`(`android.permission.DUMP`
  보유자만 호출 가능)로 재현했습니다. 릴리스 APK에는 포함되지 않습니다.
- 실기기 검증: 연결된 테스트폰이 `unauthorized` 상태여서 미완료입니다.

## 다음 단계

서버 연동 단계에서는 기존 PADIEM 계정·기기 소유권·권한·작업 전달·결과 반환 계약을
재사용해야 합니다. 이 앱에는 공용 시크릿이나 별도 인증 체계를 넣지 않습니다.
