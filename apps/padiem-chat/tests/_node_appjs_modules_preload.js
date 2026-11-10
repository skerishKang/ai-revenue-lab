// #7216 R5 — Node 하네스 호환 preload (테스트 전용). R5 0단계(0-1)에서 통일.
//
// app.js는 설정·사이드바 이후 여러 구역을 chat-*-module.js 들에서 가져온다.
// 실제 브라우저(index.html)는 app.js보다 먼저 그 모듈들을 로드하지만, 기존
// Node 하네스 다수는 app.js 한 파일만 vm에 넣는다. 이 preload는 하네스가
// static/app.js를 읽을 때 index.html에서 app.js 앞에 적힌 chat-*-module.js를
// 로드 순서대로 앞에 붙여, 제품 코드를 복제하거나 하네스마다 로더 줄을 두지
// 않고도 동일한 로드 순서를 재현한다. 새 모듈은 index.html script 줄만 추가하면
// 여기에 자동으로 따라온다. 제품 번들·배포 파일에는 포함되지 않는다.
const fs = require("fs");
const path = require("path");

const originalReadFileSync = fs.readFileSync;
const moduleCache = new Map(); // static 디렉터리 -> app.js 앞 모듈 경로 목록

function modulesBeforeApp(staticDir) {
  if (moduleCache.has(staticDir)) return moduleCache.get(staticDir);
  let names = [];
  try {
    const index = originalReadFileSync.call(fs, path.join(staticDir, "index.html"), "utf8");
    const scripts = [...index.matchAll(/<script\s+src="\.\/([^"]+\.js)"/g)].map((m) => ({
      name: m[1],
      pos: m.index,
    }));
    const appPos = scripts.find((s) => s.name === "app.js");
    if (appPos) {
      names = scripts
        .filter((s) => s.pos < appPos.pos && /^chat-[\w-]+-module\.js$/.test(s.name))
        .map((s) => s.name);
    }
  } catch (_) {
    names = [];
  }
  const paths = names.map((name) => path.join(staticDir, name));
  moduleCache.set(staticDir, paths);
  return paths;
}

fs.readFileSync = function readFileSyncWithR5Modules(target, ...rest) {
  const text = originalReadFileSync.call(this, target, ...rest);
  const normalized = typeof target === "string" ? target.split("\\").join("/") : "";
  if (!normalized.endsWith("static/app.js")) {
    return text;
  }
  if (typeof text !== "string") return text;
  const dir = path.dirname(target);
  const sources = [];
  for (const modulePath of modulesBeforeApp(dir)) {
    try {
      sources.push(originalReadFileSync.call(fs, modulePath, "utf8"));
    } catch (_) {
      // 모듈 파일이 없으면 건너뛴다. app.js는 그대로 반환된다.
    }
  }
  return sources.length ? sources.join("\n") + "\n" + text : text;
};
