// 1GB 통일 3단계 — 세 업로드 레인이 함께 쓰는 tus 1.0.0 화면 모듈.
//
// 의원3종 앭이 배포하는 자기 사본이다(다른 앭 자산을 불러오지 않는다). 귟c칙은
// Chat static 의 같은 이름 스크립트와 동일하며, 이 파일 하나로 자족한다.
//
// 프로토콜의 서버 정본은 app/tus_core.py 이고, 여기서는 **클라이언트 쪽 한 곳**만
// 만든다: 진행률(%), 끊기면 자동 이어 올리기, 1차 한국어 안내. 각 화면(프로젝트
// 파일·Chat 첨부·웹 XLSX)은 자기 엔드포인트·허용 형식·결과 검증만 갖는다 —
// 상한 숫자도, 재시도 규칙도, 문구 체계도 두 벌이 되지 않게.
//
// 클라이언트는 이 파일이 직접 구현한다. 외부 tus 클라이언트(tus-js-client 등)는
// 이어 올리기 지문을 브라우저 저장소에 남기고, 그 문자열이 브라우저 저장소 금지
// 감사(b62_browser_persistence_audit)를 실패시킨다. 여기서는 저장소 없이
// OPTIONS(한도) → POST(생성) → PATCH(조각) → HEAD(재개 위치) → GET(결과)만 쓴다.
//
// 화면 규칙(#2342): 이 모듈이 밖으로 던지는 오류는 전부 여기서 만든 1차 한국어
// 안내다. 서버 본문 메시지를 그대로 노출하지 않고 error.code 참조만 남긴다.
(function () {
  "use strict";

  var DEFAULT_CHUNK_BYTES = 16 * 1024 * 1024; // 90MB 서버 상한 안에서 재개 단위를 촘촘히.
  var CODE_PATTERN = /^[a-z][a-z0-9_]{0,63}$/;
  var TUS_VERSION = "1.0.0";
  var PATCH_CONTENT_TYPE = "application/offset+octet-stream";
  // 끊김(응답 없음)·서버 오류(5xx)·잠김(423)만 다시 시도한다. 4xx는 다시 보내도
  // 같은 답이므로 즉시 한국어 안내로 넘긴다.
  var RETRY_DELAYS_MS = [0, 1000, 3000, 5000, 10000];
  var limitsCache = Object.create(null);

  function humanBytes(total) {
    var value = total;
    var units = ["B", "KB", "MB", "GB"];
    for (var i = 0; i < units.length; i += 1) {
      if (value < 1024 || i === units.length - 1) {
        return (i >= 2 ? Math.round(value * 10) / 10 : Math.round(value)) + units[i];
      }
      value /= 1024;
    }
    return total + "B";
  }

  function safeError(message, code) {
    var error = new Error(message);
    error.uiMessageSafe = true;
    if (typeof code === "string" && CODE_PATTERN.test(code)) error.code = code;
    return error;
  }

  function percentOf(sent, total) {
    if (!Number.isFinite(total) || total <= 0) return 0;
    return Math.max(0, Math.min(100, Math.round((sent / total) * 100)));
  }

  function bodyCode(body) {
    var code = body && body.error && body.error.code;
    return typeof code === "string" && CODE_PATTERN.test(code) ? code : null;
  }

  function readJson(response) {
    return response.json().catch(function () { return null; });
  }

  function failureFrom(status, body, limits) {
    var error = safeError(messageFor(status, limits), bodyCode(body));
    error.failureStatus = status;
    return error;
  }

  // tus 규격: Upload-Metadata 값은 쉼표로 나눈 "키 공백 base64(UTF-8)" 목록이다.
  function base64Utf8(value) {
    var bytes = new TextEncoder().encode(String(value));
    var binary = "";
    for (var i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
    return btoa(binary);
  }

  function uploadMetadata(name, mediaType) {
    return "filename " + base64Utf8(name) + ",filetype " + base64Utf8(mediaType);
  }

  // 서버가 준 Location은 같은 출처의 경로일 수도, 절대 URL일 수도 있다.
  function absoluteLocation(location) {
    try {
      return new URL(location, window.location.href).toString();
    } catch (ignore) {
      return location;
    }
  }

  function messageFor(status, limits) {
    return status === 413
        ? "파일이 너무 커요 — 최대 " + humanBytes((limits && limits.maxUploadBytes) || 0) + "까지 올릴 수 있어요."
      : status === 401 ? "로그인이 필요해요. 로그인 후 다시 시도해 주세요."
      : (status === 403 || status === 404) ? "올릴 권한을 확인할 수 없어요. 로그인 상태를 확인한 뒤 다시 시도해 주세요."
      : status === 409 ? "올리던 위치가 맞지 않아요. 처음부터 다시 올려 주세요."
      : (status === 415 || status === 422) ? "이 형식은 올릴 수 없어요."
      : "업로드가 끊겼어요. 네트워크를 확인하고 다시 시도해 주세요.";
  }

  // 전체·조각 상한은 서버가 답하는 값만 따른다 — 화면이 숫자를 따로 들지 않는다.
  function discover(endpoint) {
    if (limitsCache[endpoint]) return Promise.resolve(limitsCache[endpoint]);
    return fetch(endpoint, {
      method: "OPTIONS",
      headers: { "Tus-Resumable": TUS_VERSION },
      credentials: "same-origin",
      cache: "no-store",
    }).then(function (response) {
      if (!response.ok) throw safeError("업로드 한도를 확인하지 못했어요. 다시 시도해 주세요.");
      var maxSize = Number(response.headers.get("Tus-Max-Size"));
      var chunkMax = Number(response.headers.get("X-Padiem-Tus-Chunk-Max"));
      var limits = {
        maxUploadBytes: Number.isFinite(maxSize) && maxSize > 0 ? maxSize : 0,
        chunkMaxBytes: Number.isFinite(chunkMax) && chunkMax > 0 ? chunkMax : 0,
      };
      limitsCache[endpoint] = limits;
      return limits;
    }, function () {
      throw safeError("업로드 한도를 확인하지 못했어요. 다시 시도해 주세요.");
    });
  }

  // 생성: Location이 곧 이어 올리기 자원이다. 없으면 위치를 알 수 없으므로 실패다.
  function createUpload(endpoint, file, mediaType, limits) {
    return fetch(endpoint, {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        "Tus-Resumable": TUS_VERSION,
        "Upload-Length": String(file.size),
        "Upload-Metadata": uploadMetadata(file.name, mediaType),
      },
    }).then(function (response) {
      return readJson(response).then(function (body) {
        if (!response.ok) throw failureFrom(response.status, body, limits);
        var location = response.headers.get("Location");
        if (!location) throw safeError("업로드를 시작하지 못했어요. 다시 시도해 주세요.");
        return absoluteLocation(location);
      });
    }, function () {
      throw safeError("업로드를 시작하지 못했어요. 다시 시도해 주세요.");
    });
  }

  // options: {file, endpoint, mediaType, onProgress(sent,total), onState(state), signal}
  //   state.phase: discovering | uploading | resuming | finalizing
  //   state.percent: 0~100
  // 돌려주는 값은 마지막 한 번의 GET 결과 본문이다(각 화면이 자기 모양으로 검증).
  function upload(options) {
    var file = options.file;
    var endpoint = options.endpoint;
    var mediaType = options.mediaType;
    var onProgress = options.onProgress || function () {};
    var onState = options.onState || function () {};
    var signal = options.signal;
    if (!file || !endpoint || !mediaType) {
      return Promise.reject(safeError("업로드 정보가 올바르지 않아요."));
    }
    if (signal && signal.aborted) {
      return Promise.reject(safeError("업로드를 취소했어요."));
    }
    onState({ phase: "discovering", percent: 0 });
    return discover(endpoint).then(function (limits) {
      if (limits.maxUploadBytes && file.size > limits.maxUploadBytes) {
        throw safeError(
          "파일이 너무 커요 — 최대 " + humanBytes(limits.maxUploadBytes) + "까지 올릴 수 있어요.");
      }
      return new Promise(function (resolve, reject) {
        var settled = false;
        var resumed = false;
        var offset = 0;
        var url = null;
        var retries = 0;
        var chunkSize = Math.min(DEFAULT_CHUNK_BYTES, limits.chunkMaxBytes || DEFAULT_CHUNK_BYTES);

        function aborted() {
          return Boolean(signal && signal.aborted);
        }

        function report(phase, sent, total) {
          var percent = phase === "finalizing" ? 100 : percentOf(sent, total);
          onProgress(sent, total);
          onState({ phase: phase, percent: percent, sent: sent, total: total });
        }

        function fail(error) {
          if (settled) return;
          settled = true;
          reject(error);
        }

        function succeed(data) {
          if (settled) return;
          settled = true;
          resolve(data);
        }

        function cancel() {
          fail(safeError("업로드를 취소했어요."));
        }

        if (signal && typeof signal.addEventListener === "function") {
          signal.addEventListener("abort", cancel, { once: true });
        }

        // 마지막 PATCH는 204로 끝난다(tus 규격). 저장 결과(201/4xx)는 한 번만
        // 꺼내 쓴다 — GET이 결과를 돌려주고 서버가 임시 조각을 치운다.
        function finish() {
          report("finalizing", file.size, file.size);
          fetch(url, {
            credentials: "same-origin", cache: "no-store",
            headers: { "Accept": "application/json" },
          }).then(function (response) {
            return readJson(response).then(function (data) {
              if (!response.ok || !data) throw failureFrom(response.status, data, limits);
              succeed(data);
            });
          }, function () {
            throw safeError("업로드 결과를 확인하지 못했어요. 다시 시도해 주세요.");
          }).catch(function (error) {
            fail(error && error.uiMessageSafe ? error
              : safeError("업로드 결과를 확인하지 못했어요. 다시 시도해 주세요."));
          });
        }

        // 서버가 확정한 위치를 다시 읽는다. 자원이 사라졌으면(404) 새로 시작한다.
        function reconcile() {
          return fetch(url, {
            method: "HEAD",
            credentials: "same-origin",
            cache: "no-store",
            headers: { "Tus-Resumable": TUS_VERSION },
          }).then(function (response) {
            if (response.status === 404) return null;
            var next = Number(response.headers.get("Upload-Offset"));
            if (!response.ok || !Number.isFinite(next) || next < 0 || next > file.size) {
              throw safeError("올리던 위치를 확인하지 못했어요. 다시 시도해 주세요.");
            }
            return next;
          }, function () {
            // HEAD 실패는 "서버 위치를 못 읽었다"일 뿐이다. 아는 위치에서 이어 간다.
            return offset;
          });
        }

        function send() {
          if (settled) return;
          if (aborted()) { cancel(); return; }
          if (offset >= file.size) { finish(); return; }
          var start = offset;
          var end = Math.min(file.size, start + chunkSize);
          fetch(url, {
            method: "PATCH",
            credentials: "same-origin",
            cache: "no-store",
            signal: signal,
            headers: {
              "Tus-Resumable": TUS_VERSION,
              "Upload-Offset": String(start),
              "Content-Type": PATCH_CONTENT_TYPE,
            },
            body: file.slice(start, end),
          }).then(function (response) {
            return readJson(response).then(function (body) {
              if (!response.ok) throw failureFrom(response.status, body, limits);
              var next = Number(response.headers.get("Upload-Offset"));
              if (!Number.isFinite(next) || next <= start || next > file.size) {
                throw safeError("올리던 위치가 맞지 않아요. 처음부터 다시 올려 주세요.");
              }
              offset = next;
              retries = 0;
              report(resumed ? "resuming" : "uploading", offset, file.size);
              send();
            });
          }, function () {
            // 네트워크 끊김: 위치를 서버에 다시 물은 뒤 이어 올린다.
            throw failureFrom(0, null, limits);
          }).catch(function (error) {
            if (settled) return;
            if (aborted()) { cancel(); return; }
            var status = error && error.failureStatus;
            var retryable = status === 0 || status === 423
              || (typeof status === "number" && status >= 500);
            var message = error && error.uiMessageSafe ? error : safeError(messageFor(0, limits));
            if (!retryable || retries >= RETRY_DELAYS_MS.length) { fail(message); return; }
            var delay = RETRY_DELAYS_MS[retries];
            retries += 1;
            resumed = true;
            report("resuming", offset, file.size);
            setTimeout(function () {
              if (settled) return;
              if (aborted()) { cancel(); return; }
              reconcile().then(function (next) {
                if (settled) return;
                if (next === null) {
                  offset = 0;
                  return createUpload(endpoint, file, mediaType, limits).then(function (fresh) {
                    url = fresh;
                    send();
                  }, function (restartError) {
                    fail(restartError);
                  });
                }
                offset = Math.max(offset, next);
                send();
              }, function (headError) {
                fail(headError);
              });
            }, delay);
          });
        }

        createUpload(endpoint, file, mediaType, limits).then(function (fresh) {
          url = fresh;
          report("uploading", 0, file.size);
          send();
        }, function (error) {
          fail(error);
        });
      });
    });
  }

  window.PadiemTusUpload = Object.freeze({
    upload: upload,
    discover: discover,
    humanBytes: humanBytes,
  });
})();
