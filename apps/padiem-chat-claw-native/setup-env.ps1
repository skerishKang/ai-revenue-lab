# COM2 React Native development environment for the PADIEM Chat/Claw native app.
# Dot-source before any gradle/npm command:
#   . D:\PADIEM\projects\padiem-chat-claw-native\setup-env.ps1

# All build-time scratch space lives on D: so the C: system drive keeps headroom.
$env:TEMP = "D:\Temp"
$env:TMP = "D:\Temp"
$env:TMPDIR = "D:\Temp"

$env:JAVA_HOME = "D:\PADIEM\tools\jdk\jdk-17.0.20.1+1"
$env:ANDROID_HOME = "D:\DevToolData\android-sdk-from-C-20261020"
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:GRADLE_USER_HOME = "D:\AndroidDev\gradle-home"
$env:NPM_CONFIG_CACHE = "D:\npm-cache"
$env:PLAYWRIGHT_BROWSERS_PATH = "D:\DevToolData\playwright-browsers"
$env:PATH = "$env:JAVA_HOME\bin;$env:ANDROID_HOME\platform-tools;$env:ANDROID_HOME\cmdline-tools\latest\bin;$env:ANDROID_HOME\emulator;$env:PATH"

# Gradle never asks and never blocks a build on an interactive prompt.
$env:CI = "1"
$env:GRADLE_OPTS = "-Dorg.gradle.daemon=true -Dorg.gradle.jvmargs=-Xmx3072m -Dfile.encoding=UTF-8"
