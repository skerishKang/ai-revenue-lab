// #7216 R5 1단계 — Node 하네스 호환 preload (테스트 전용).
//
// app.js는 설정·사이드바 구역을 chat-settings-module.js / chat-sidebar-module.js
// 에서 가져온다. 실제 브라우저(index.html)는 두 파일을 app.js보다 먼저 로드하지만,
// 기존 Node 하네스 다수는 app.js 한 파일만 vm에 넣는다. 이 preload는 하네스가
// static/app.js를 읽을 때 같은 디렉터리의 두 모듈을 앞에 붙여, 제품 코드를
// 복제하거나 하네스 21개를 각각 고치지 않고도 동일한 로드 순서를 재현한다.
// 제품 번들·배포 파일에는 포함되지 않는다.
const fs = require("fs");
const path = require("path");

const originalReadFileSync = fs.readFileSync;
const MODULES = ["chat-settings-module.js", "chat-sidebar-module.js", "chat-history-module.js", "chat-auth-module.js"];

fs.readFileSync = function readFileSyncWithR5Modules(target, ...rest) {
  const text = originalReadFileSync.call(this, target, ...rest);
  const normalized = typeof target === "string" ? target.split("\\").join("/") : "";
  if (!normalized.endsWith("static/app.js")) {
    return text;
  }
  if (typeof text !== "string") return text;
  const dir = path.dirname(target);
  const sources = MODULES.map((name) => {
    try {
      return originalReadFileSync.call(fs, path.join(dir, name), "utf8");
    } catch (_) {
      return "";
    }
  }).filter(Boolean);
  return sources.length ? sources.join("\n") + "\n" + text : text;
};
