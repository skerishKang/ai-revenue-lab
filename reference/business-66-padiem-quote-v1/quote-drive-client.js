/* B66 — 고객 본인 Google Drive(BYOS) 저장·불러오기 클라이언트 (#3871 Slice B/C).
   이 모듈만 Google OAuth/Drive API 와 통신한다.

   절대 규칙
   - 최소 권한: 기본 범위는 drive.file(앱이 만든 파일/사용자가 선택한 파일) 하나다.
     전체 드라이브 목록 권한(drive.readonly 등)을 요청하지 않는다.
   - 접근 권한의 근거는 연결된 Google 세션 + Drive 가 돌려준 **소유 정보**다.
     소유 정보가 없거나 확인되지 않으면 허용하지 않는다(fail-closed).
     파일 안에 적힌 사용자 ID/이메일은 권한 근거로 쓰지 않는다(계약 단계에서 거부).
   - 액세스 토큰은 이 모듈의 메모리 클로저에만 둔다. 어떤 브라우저 저장소나 쿠키에도 기록하지 않는다.
   - 기존 B67/Claw Drive 커넥터를 고객 개인 Drive 권위로 재사용하지 않는다.
   - 모델 호출은 0이다. 통신 대상은 Google OAuth/Drive 엔드포인트뿐이다.

   네트워크·전역 객체는 주입 가능하다(테스트는 전부 주입된 스텁으로 수행). */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./quote-drive-contract.js"));
  } else {
    root.B66QuoteDriveClient = factory(root.B66QuoteDriveContract);
  }
})(typeof self !== "undefined" ? self : this, function (Contract) {
  "use strict";

  if (!Contract) throw new Error("B66QuoteDriveContract is required");

  var GIS_SRC = "https://accounts.google.com/gsi/client";
  var GAPI_SRC = "https://apis.google.com/js/api.js";
  var DRIVE_FILES_ENDPOINT = "https://www.googleapis.com/drive/v3/files";
  var DRIVE_UPLOAD_ENDPOINT = "https://www.googleapis.com/upload/drive/v3/files";
  var DRIVE_REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke";
  var SCOPE_DRIVE_FILE = "https://www.googleapis.com/auth/drive.file";
  var DEFAULT_SCOPES = [SCOPE_DRIVE_FILE];
  var LIST_FIELDS = "nextPageToken, files(id,name,mimeType,size,trashed,modifiedTime,owners,capabilities)";
  var FILE_FIELDS = "id,name,mimeType,size,trashed,modifiedTime,owners,capabilities";
  var MAX_LIST_PAGE_SIZE = 100;
  var MAX_LIST_PAGES = 10;
  var MAX_NAME_RECHECKS = 2;
  var EXPIRY_SKEW_MS = 30 * 1000;

  function utf8Bytes(text) {
    if (typeof TextEncoder === "function") return new TextEncoder().encode(String(text));
    if (typeof Buffer === "function") return new Uint8Array(Buffer.from(String(text), "utf8"));
    throw new Error("encoding_unavailable");
  }

  function normalizeBytes(bytes) {
    if (bytes == null) return null;
    if (bytes instanceof Uint8Array) return bytes;
    if (typeof ArrayBuffer !== "undefined" && bytes instanceof ArrayBuffer) return new Uint8Array(bytes);
    if (Array.isArray(bytes)) return new Uint8Array(bytes);
    return null;
  }

  function concatBytes(parts) {
    var total = 0;
    parts.forEach(function (part) { total += part.length; });
    var out = new Uint8Array(total);
    var at = 0;
    parts.forEach(function (part) {
      out.set(part, at);
      at += part.length;
    });
    return out;
  }

  function multipartBody(metadata, bytes, mimeType, boundary) {
    var head = "--" + boundary + "\r\n" +
      "Content-Type: application/json; charset=UTF-8\r\n\r\n" +
      JSON.stringify(metadata) + "\r\n" +
      "--" + boundary + "\r\n" +
      "Content-Type: " + mimeType + "\r\n\r\n";
    return concatBytes([utf8Bytes(head), bytes, utf8Bytes("\r\n--" + boundary + "--")]);
  }

  function defaultLoadScript(src) {
    return new Promise(function (resolve, reject) {
      if (typeof document === "undefined" || !document.createElement) {
        reject(new Error("script_loader_unavailable"));
        return;
      }
      var existing = document.querySelector('script[src="' + src + '"]');
      if (existing) { resolve(existing); return; }
      var element = document.createElement("script");
      element.src = src;
      element.async = true;
      element.onload = function () { resolve(element); };
      element.onerror = function () { reject(new Error("script_load_failed")); };
      document.head.appendChild(element);
    });
  }

  function resolveGlobal(name, injected) {
    if (injected) return injected;
    if (typeof window !== "undefined" && window[name]) return window[name];
    if (typeof globalThis !== "undefined" && globalThis[name]) return globalThis[name];
    return null;
  }

  function encodeQuery(params) {
    var pairs = [];
    Object.keys(params).forEach(function (key) {
      var value = params[key];
      if (value === undefined || value === null) return;
      pairs.push(encodeURIComponent(key) + "=" + encodeURIComponent(String(value)));
    });
    return pairs.join("&");
  }

  function escapeDriveQueryValue(value) {
    return String(value).replace(/\\/g, "\\\\").replace(/'/g, "\\'");
  }

  /* 소유권 판정: 소유 정보가 없거나 확인되지 않으면 허용하지 않는다. */
  function ownershipOf(file) {
    if (!file || typeof file !== "object" || typeof file.id !== "string" || !file.id) return "invalid";
    if (file.trashed === true) return "trashed";
    if (!Array.isArray(file.owners) || file.owners.length === 0) return "unverified";
    var mine = file.owners.some(function (owner) { return owner && owner.me === true; });
    if (!mine) return "foreign";
    if (file.capabilities && file.capabilities.canDownload === false) return "not_downloadable";
    return "owned";
  }

  var OWNERSHIP_CODES = {
    invalid: "invalid_response",
    trashed: "drive_file_trashed",
    unverified: "drive_file_ownership_unverified",
    foreign: "drive_file_not_owned_by_connected_account",
    not_downloadable: "drive_file_not_downloadable"
  };

  function create(options) {
    var config = options || {};
    var clientId = typeof config.clientId === "string" ? config.clientId.trim() : "";
    var appId = typeof config.appId === "string" ? config.appId.trim() : "";
    var developerKey = typeof config.developerKey === "string" ? config.developerKey.trim() : "";
    var scopes = Array.isArray(config.scopes) && config.scopes.length ? config.scopes.slice() : DEFAULT_SCOPES.slice();

    var deps = {
      fetchImpl: typeof config.fetch === "function"
        ? config.fetch
        : (typeof fetch === "function" ? function (url, init) { return fetch(url, init); } : null),
      loadScript: typeof config.loadScript === "function" ? config.loadScript : defaultLoadScript,
      now: typeof config.now === "function" ? config.now : function () { return Date.now(); },
      gisLoader: config.gisLoader || null,
      gapiLoader: config.gapiLoader || null
    };

    /* 토큰은 이 클로저 안에만 존재한다. 어떤 저장소에도 기록하지 않는다.
       epoch 는 계정 전환·로그아웃 시 증가해, 이전 세션의 in-flight 응답이
       새 owner 의 편집기나 Drive 상태를 갱신하지 못하게 막는다. */
    var session = {
      connected: false,
      accessToken: "",
      scopes: [],
      expiresAt: 0,
      connectedAt: null,
      lastErrorCode: null,
      epoch: 0
    };

    function googleObject() {
      return resolveGlobal("google", config.google);
    }

    function gapiObject() {
      return resolveGlobal("gapi", config.gapi);
    }

    function isConfigured() {
      return Boolean(clientId);
    }

    function pickerReady() {
      return Boolean(clientId && appId && developerKey);
    }

    function notConfigured() {
      return { ok: false, code: "drive_not_configured", message: "Google Drive 연결 설정(클라이언트 ID)이 준비되지 않았습니다." };
    }

    function publicSession() {
      return {
        connected: session.connected === true,
        scopes: session.scopes.slice(),
        expiresAt: session.expiresAt,
        expired: session.connected === true && session.expiresAt <= deps.now() + EXPIRY_SKEW_MS,
        connectedAt: session.connectedAt,
        lastErrorCode: session.lastErrorCode,
        epoch: session.epoch
      };
    }

    function clearSession(reasonCode) {
      session.connected = false;
      session.accessToken = "";
      session.scopes = [];
      session.expiresAt = 0;
      session.connectedAt = null;
      session.lastErrorCode = typeof reasonCode === "string" ? reasonCode : null;
      session.epoch += 1;
    }

    function stale(epoch) {
      return session.epoch !== epoch;
    }

    function requireToken() {
      if (!isConfigured()) return { ok: false, code: "drive_not_configured" };
      if (session.connected !== true || !session.accessToken) return { ok: false, code: "drive_not_connected" };
      if (session.expiresAt <= deps.now() + EXPIRY_SKEW_MS) {
        clearSession("drive_token_expired");
        return { ok: false, code: "drive_token_expired" };
      }
      return { ok: true, token: session.accessToken, epoch: session.epoch };
    }

    async function ensureGis() {
      var google = googleObject();
      if (google && google.accounts && google.accounts.oauth2) return google;
      var loader = deps.gisLoader || (typeof deps.loadScript === "function"
        ? function () { return deps.loadScript(GIS_SRC); }
        : null);
      if (!loader) throw new Error("gis_unavailable");
      await loader();
      google = googleObject();
      if (!google || !google.accounts || !google.accounts.oauth2) throw new Error("gis_unavailable");
      return google;
    }

    /* ── 연결: 고객이 버튼을 눌러 명시적으로 시작한다 ── */
    function connect(options) {
      var opts = options || {};
      if (!isConfigured()) return Promise.resolve(notConfigured());
      var prompt = typeof opts.prompt === "string" && opts.prompt ? opts.prompt : "";

      return ensureGis().then(function (google) {
        return new Promise(function (resolve) {
          var settled = false;
          var client;
          try {
            client = google.accounts.oauth2.initTokenClient({
              client_id: clientId,
              scope: scopes.join(" "),
              callback: function (response) {
                if (settled) return;
                settled = true;
                if (!response || response.error || !response.access_token) {
                  clearSession("drive_auth_failed");
                  var denied = response && (response.error === "access_denied" ||
                    response.error === "popup_closed" || response.error === "user_cancelled");
                  resolve({
                    ok: false,
                    code: denied ? "drive_auth_denied" : "drive_auth_failed",
                    message: denied
                      ? "Google 계정 연결이 취소되었습니다."
                      : "Google 계정 연결에 실패했습니다."
                  });
                  return;
                }
                var lifetime = Number(response.expires_in);
                var expiresAt = deps.now() + (Number.isFinite(lifetime) && lifetime > 0 ? lifetime * 1000 : 3600 * 1000);
                /* 새 세션은 이전 세션의 in-flight 작업을 무효화한다. */
                session.epoch += 1;
                session.connected = true;
                session.accessToken = String(response.access_token);
                session.scopes = String(response.scope || scopes.join(" ")).split(/\s+/).filter(Boolean);
                session.expiresAt = expiresAt;
                session.connectedAt = new Date(deps.now()).toISOString();
                session.lastErrorCode = null;
                resolve({ ok: true, scopes: session.scopes.slice(), expiresAt: expiresAt, session: publicSession() });
              }
            });
          } catch (err) {
            resolve({ ok: false, code: "gis_unavailable", message: "Google 로그인 스크립트를 불러오지 못했습니다." });
            return;
          }
          try {
            client.requestAccessToken(prompt ? { prompt: prompt } : {});
          } catch (err) {
            if (!settled) {
              settled = true;
              resolve({ ok: false, code: "drive_auth_failed", message: "Google 계정 연결을 시작하지 못했습니다." });
            }
          }
        });
      }).catch(function () {
        return { ok: false, code: "gis_unavailable", message: "Google 로그인 스크립트를 불러오지 못했습니다." };
      });
    }

    /* ── 연결 해제: 토큰 폐기 + 메모리 세션 완전 삭제(계정 전환 격리) ──
       B66 로그아웃/계정 전환에서도 같은 경로를 쓴다. */
    async function disconnect(options) {
      var opts = options || {};
      var token = session.accessToken;
      var wasConnected = session.connected === true;
      clearSession(typeof opts.reason === "string" ? opts.reason : null);
      if (!token || !deps.fetchImpl) return { ok: true, code: "signed_out", revoked: false, wasConnected: wasConnected };
      try {
        await deps.fetchImpl(DRIVE_REVOKE_ENDPOINT + "?token=" + encodeURIComponent(token), { method: "POST" });
        return { ok: true, code: "signed_out", revoked: true, wasConnected: wasConnected };
      } catch (err) {
        /* 폐기 실패해도 로컬 세션은 이미 지워졌다. 다음 호출은 drive_not_connected 다. */
        return { ok: true, code: "signed_out", revoked: false, wasConnected: wasConnected };
      }
    }

    function driveFetch(url, init, token) {
      var request = Object.assign({}, init || {});
      request.headers = Object.assign({}, request.headers || {}, {
        Authorization: "Bearer " + token
      });
      return deps.fetchImpl(url, request);
    }

    async function readError(response, fallbackCode) {
      var data = null;
      try {
        data = await response.json();
      } catch (err) {
        data = null;
      }
      var message = data && data.error && typeof data.error.message === "string" ? data.error.message : null;
      return { code: fallbackCode, status: response.status, message: message };
    }

    function sessionChanged() {
      return { ok: false, code: "drive_session_changed", message: "Google 계정 연결이 변경되어 작업을 중단했습니다." };
    }

    /* ── 단일 파일 소유·권한 검증 ── */
    async function verifyOwnedFile(fileId, guard) {
      var id = typeof fileId === "string" ? fileId.trim() : "";
      if (!id) return { ok: false, code: "invalid_file_id" };
      var url = DRIVE_FILES_ENDPOINT + "/" + encodeURIComponent(id) + "?" + encodeQuery({
        fields: FILE_FIELDS,
        supportsAllDrives: false
      });
      var response;
      try {
        response = await driveFetch(url, { method: "GET" }, guard.token);
      } catch (err) {
        return { ok: false, code: "network_error" };
      }
      if (response.status === 401) {
        clearSession("drive_token_expired");
        return { ok: false, code: "drive_token_expired" };
      }
      if (response.status === 404 || response.status === 403) {
        return {
          ok: false,
          code: response.status === 404 ? "drive_file_not_found" : "drive_file_access_denied",
          message: "선택한 파일을 이 Google 계정으로 열 수 없습니다."
        };
      }
      if (!response.ok) {
        var failure = await readError(response, "drive_metadata_failed");
        return { ok: false, code: failure.code, status: failure.status, message: failure.message };
      }
      var meta = null;
      try {
        meta = await response.json();
      } catch (err) {
        return { ok: false, code: "invalid_response" };
      }
      var ownership = ownershipOf(meta);
      if (ownership !== "owned") {
        return {
          ok: false,
          code: OWNERSHIP_CODES[ownership] || "drive_file_ownership_unverified",
          ownership: ownership,
          message: ownership === "unverified"
            ? "이 파일의 소유 정보를 확인할 수 없어 열지 않았습니다."
            : "이 Google 계정이 소유한 파일만 사용할 수 있습니다."
        };
      }
      return { ok: true, meta: meta };
    }

    /* ── 목록: 앱이 만들었거나 사용자가 선택한 파일 범위에서만, 페이지 전체를 조회한다 ── */
    async function listQuoteFiles(options) {
      var guard = requireToken();
      if (!guard.ok) return Object.assign({ ok: false, files: [], truncated: false }, guard);
      var opts = options || {};
      var pageSize = Math.min(Math.max(Number(opts.pageSize) || 20, 1), MAX_LIST_PAGE_SIZE);
      var maxPages = Math.min(Math.max(Number(opts.maxPages) || MAX_LIST_PAGES, 1), MAX_LIST_PAGES);
      var query = "trashed = false and (mimeType = 'application/json' or mimeType = 'application/pdf')";

      var collected = [];
      var pageToken = null;
      var pages = 0;

      while (pages < maxPages) {
        var url = DRIVE_FILES_ENDPOINT + "?" + encodeQuery({
          q: query,
          fields: LIST_FIELDS,
          pageSize: pageSize,
          orderBy: "modifiedTime desc",
          pageToken: pageToken
        });
        var response;
        try {
          response = await driveFetch(url, { method: "GET" }, guard.token);
        } catch (err) {
          return { ok: false, code: "network_error", files: [], truncated: false };
        }
        if (stale(guard.epoch)) return Object.assign(sessionChanged(), { files: [], truncated: false });
        if (response.status === 401) {
          clearSession("drive_token_expired");
          return { ok: false, code: "drive_token_expired", files: [], truncated: false };
        }
        if (!response.ok) {
          var failure = await readError(response, "drive_list_failed");
          return { ok: false, code: failure.code, status: failure.status, message: failure.message, files: [], truncated: false };
        }
        var data = null;
        try {
          data = await response.json();
        } catch (err) {
          return { ok: false, code: "invalid_response", files: [], truncated: false };
        }
        pages += 1;
        var batch = Array.isArray(data && data.files) ? data.files : [];
        batch.forEach(function (file) { collected.push(file); });
        pageToken = data && typeof data.nextPageToken === "string" && data.nextPageToken ? data.nextPageToken : null;
        if (!pageToken) break;
      }
      var truncated = Boolean(pageToken);

      var visible = [];
      var withheld = 0;
      collected.forEach(function (file) {
        if (ownershipOf(file) !== "owned") { withheld += 1; return; }
        visible.push({
          id: file.id,
          name: typeof file.name === "string" ? file.name : "",
          mimeType: typeof file.mimeType === "string" ? file.mimeType : "",
          size: Number(file.size) || 0,
          modifiedTime: typeof file.modifiedTime === "string" ? file.modifiedTime : null
        });
      });
      return { ok: true, files: visible, pages: pages, truncated: truncated, withheld: withheld };
    }

    /* ── 이름 점검 ──
       조회 실패는 fail-open 하지 않는다. 이름 충돌 검사가 불가능하면 저장을 거부한다. */
    async function existingNames(options) {
      var listed = await listQuoteFiles(options);
      if (!listed.ok) return { ok: false, code: listed.code, truncated: false, names: [] };
      return {
        ok: true,
        names: listed.files.map(function (file) { return file.name; }),
        truncated: listed.truncated === true
      };
    }

    async function nameTaken(name, guard) {
      var query = "trashed = false and name = '" + escapeDriveQueryValue(name) + "'";
      var url = DRIVE_FILES_ENDPOINT + "?" + encodeQuery({
        q: query,
        fields: "files(id,name)",
        pageSize: 5
      });
      var response;
      try {
        response = await driveFetch(url, { method: "GET" }, guard.token);
      } catch (err) {
        return { ok: false, code: "network_error" };
      }
      if (stale(guard.epoch)) return sessionChanged();
      if (response.status === 401) {
        clearSession("drive_token_expired");
        return { ok: false, code: "drive_token_expired" };
      }
      if (!response.ok) {
        var failure = await readError(response, "drive_list_failed");
        return { ok: false, code: failure.code, status: failure.status, message: failure.message };
      }
      var data = null;
      try {
        data = await response.json();
      } catch (err) {
        return { ok: false, code: "invalid_response" };
      }
      var files = Array.isArray(data && data.files) ? data.files : [];
      return { ok: true, taken: files.some(function (file) { return file && file.name === name; }) };
    }

    /* ── Picker: 사용자가 직접 파일을 고른다 ── */
    function openPicker(options) {
      var opts = options || {};
      var guard = requireToken();
      if (!guard.ok) return Promise.resolve(Object.assign({ ok: false, picked: [] }, guard));
      if (!pickerReady()) {
        return Promise.resolve({
          ok: false,
          code: "picker_unavailable",
          picked: [],
          message: "파일 선택기 설정이 준비되지 않았습니다."
        });
      }
      var loader = deps.gapiLoader || (typeof deps.loadScript === "function"
        ? function () { return deps.loadScript(GAPI_SRC); }
        : null);
      if (!loader) return Promise.resolve({ ok: false, code: "picker_unavailable", picked: [] });

      return loader().then(function () {
        return new Promise(function (resolve) {
          var gapi = gapiObject();
          var google = googleObject();
          if (!gapi || typeof gapi.load !== "function" || !google || !google.picker) {
            resolve({ ok: false, code: "picker_unavailable", picked: [] });
            return;
          }
          gapi.load("picker", {
            callback: function () {
              var Picker = google.picker;
              if (!Picker || !Picker.PickerBuilder) {
                resolve({ ok: false, code: "picker_unavailable", picked: [] });
                return;
              }
              var viewId = Picker.ViewId && Picker.ViewId.DOCS ? Picker.ViewId.DOCS : "all";
              var view = new Picker.DocsView(viewId)
                .setIncludeFolders(true)
                .setMimeTypes(Contract.JSON_MIME);
              var builder = new Picker.PickerBuilder()
                .setAppId(appId)
                .setDeveloperKey(developerKey)
                .setOAuthToken(guard.token)
                .addView(view)
                .setTitle("불러올 견적 JSON 파일을 선택해 주세요")
                .setCallback(function (data) {
                  if (!data || !data.action) return;
                  if (data.action === Picker.Action.CANCEL) {
                    resolve({ ok: false, code: "picker_cancelled", picked: [] });
                    return;
                  }
                  if (data.action !== Picker.Action.PICKED) return;
                  var docs = Array.isArray(data.docs) ? data.docs : [];
                  resolve({
                    ok: docs.length > 0,
                    code: docs.length > 0 ? "picked" : "picker_cancelled",
                    picked: docs.map(function (doc) {
                      return { id: doc.id, name: doc.name, mimeType: doc.mimeType };
                    })
                  });
                });
              try {
                builder.build().setVisible(true);
              } catch (err) {
                resolve({ ok: false, code: "picker_unavailable", picked: [] });
              }
            }
          });
        });
      }).catch(function () {
        return { ok: false, code: "picker_unavailable", picked: [] };
      });
    }

    /* ── 파일 읽기: 소유 검증 → 크기 → 계약 검증 → QuoteCore 재계산 → 템플릿 권위 ── */
    async function openQuoteFile(fileId, options) {
      var opts = options || {};
      var guard = requireToken();
      if (!guard.ok) return Object.assign({ ok: false }, guard);

      var verified = await verifyOwnedFile(fileId, guard);
      if (stale(guard.epoch)) return sessionChanged();
      if (!verified.ok) return verified;
      var meta = verified.meta;

      var size = Number(meta.size);
      if (Number.isFinite(size) && size > Contract.MAX_JSON_BYTES) {
        return { ok: false, code: "json_too_large", message: "견적 JSON 파일이 지원 크기를 초과했습니다." };
      }

      var mediaUrl = DRIVE_FILES_ENDPOINT + "/" + encodeURIComponent(meta.id) + "?alt=media";
      var mediaResponse;
      try {
        mediaResponse = await driveFetch(mediaUrl, { method: "GET" }, guard.token);
      } catch (err) {
        return { ok: false, code: "network_error" };
      }
      if (stale(guard.epoch)) return sessionChanged();
      if (mediaResponse.status === 401) {
        clearSession("drive_token_expired");
        return { ok: false, code: "drive_token_expired" };
      }
      if (!mediaResponse.ok) {
        var mediaFailure = await readError(mediaResponse, "drive_download_failed");
        return { ok: false, code: mediaFailure.code, status: mediaFailure.status, message: mediaFailure.message };
      }
      var text = null;
      try {
        text = await mediaResponse.text();
      } catch (err) {
        return { ok: false, code: "drive_download_failed" };
      }
      if (stale(guard.epoch)) return sessionChanged();

      var parsed = Contract.readPackage(text, {
        byteLength: Number.isFinite(size) ? size : undefined
      });
      if (!parsed.ok) {
        return {
          ok: false,
          code: parsed.code,
          lost: parsed.lost,
          message: "선택한 파일을 견적 데이터로 읽을 수 없습니다. (" + parsed.code + ")"
        };
      }
      var imported = Contract.importPackage(parsed.package, {
        templates: opts.templates,
        requireApprovedTemplate: opts.requireApprovedTemplate
      });
      if (!imported.ok) {
        return {
          ok: false,
          code: imported.code,
          template: imported.template,
          warnings: imported.warnings,
          message: imported.message || "이 견적을 편집기로 불러올 수 없습니다. (" + imported.code + ")"
        };
      }

      return {
        ok: true,
        file: {
          id: meta.id,
          name: typeof meta.name === "string" ? meta.name : "",
          size: Number.isFinite(size) ? size : null,
          modifiedTime: typeof meta.modifiedTime === "string" ? meta.modifiedTime : null
        },
        packageId: parsed.package.packageId,
        contentFingerprint: parsed.package.contentFingerprint,
        draft: imported.draft,
        totals: imported.totals,
        template: imported.template,
        warnings: imported.warnings,
        totalsIgnored: parsed.totalsIgnored === true,
        totalsAuthority: "quote-core"
      };
    }

    /* ── 업로드: 항상 새 파일 생성. 기존 파일 id 를 덮어쓰지 않는다 ── */
    async function uploadFile(options) {
      var guard = options && options.guard ? options.guard : requireToken();
      if (!guard.ok) return Object.assign({ ok: false }, guard);
      var bytes = normalizeBytes(options && options.bytes);
      if (!bytes) return { ok: false, code: "upload_bytes_missing" };
      var name = typeof options.name === "string" ? options.name.trim() : "";
      var mimeType = typeof options.mimeType === "string" ? options.mimeType : "";
      if (!name || !mimeType) return { ok: false, code: "upload_metadata_missing" };
      if (Array.isArray(options.takenNames) && options.takenNames.indexOf(name) !== -1) {
        return { ok: false, code: "duplicate_name_conflict", message: "같은 이름의 파일이 있어 덮어쓰지 않았습니다." };
      }

      var boundary = "b66-drive-boundary-0123456789";
      var body = multipartBody({ name: name, mimeType: mimeType }, bytes, mimeType, boundary);
      var response;
      try {
        response = await driveFetch(
          DRIVE_UPLOAD_ENDPOINT + "?uploadType=multipart&fields=id,name,mimeType,size",
          {
            method: "POST",
            body: body,
            headers: { "Content-Type": "multipart/related; boundary=" + boundary }
          },
          guard.token
        );
      } catch (err) {
        return { ok: false, code: "network_error", message: "Google Drive 업로드 중 연결이 끊겼습니다." };
      }
      if (stale(guard.epoch)) return sessionChanged();
      if (response.status === 401) {
        clearSession("drive_token_expired");
        return { ok: false, code: "drive_token_expired" };
      }
      if (!response.ok) {
        var failure = await readError(response, response.status === 403 ? "drive_quota_or_permission_denied" : "upload_failed");
        return { ok: false, code: failure.code, status: failure.status, message: failure.message };
      }
      var data = null;
      try {
        data = await response.json();
      } catch (err) {
        return { ok: false, code: "invalid_response" };
      }
      if (!data || typeof data.id !== "string") return { ok: false, code: "invalid_response" };
      return { ok: true, id: data.id, name: typeof data.name === "string" ? data.name : name, mimeType: mimeType };
    }

    /* ── 저장 준비: 이름 점검을 fail-closed 로 수행하고 이름을 확정한다 ── */
    async function planNames(guard, draft, baseName) {
      var listing = await existingNames();
      if (stale(guard.epoch)) return sessionChanged();
      if (!listing.ok) {
        return { ok: false, code: "naming_check_unavailable", message: "기존 파일 이름을 확인하지 못해 저장을 시작하지 않았습니다." };
      }
      if (listing.truncated) {
        return { ok: false, code: "naming_check_incomplete", message: "기존 파일 목록을 모두 확인하지 못해 저장을 시작하지 않았습니다." };
      }
      var taken = listing.names.slice();
      var planned = Contract.planUniqueFileNames({ draft: draft, baseName: baseName, existingNames: taken });
      if (!planned.ok) return planned;

      /* 업로드 직전에 계획한 이름을 다시 확인한다(그 사이 생성된 파일 대비). */
      for (var attempt = 0; attempt < MAX_NAME_RECHECKS; attempt += 1) {
        var jsonCheck = await nameTaken(planned.json, guard);
        if (!jsonCheck.ok) {
          return { ok: false, code: "naming_check_unavailable", message: "파일 이름을 확인하지 못해 저장을 시작하지 않았습니다." };
        }
        var pdfCheck = await nameTaken(planned.pdf, guard);
        if (!pdfCheck.ok) {
          return { ok: false, code: "naming_check_unavailable", message: "파일 이름을 확인하지 못해 저장을 시작하지 않았습니다." };
        }
        if (!jsonCheck.taken && !pdfCheck.taken) return planned;
        taken = taken.concat([planned.json, planned.pdf]);
        var replanned = Contract.planUniqueFileNames({ draft: draft, baseName: baseName, existingNames: taken });
        if (!replanned.ok) return replanned;
        planned = replanned;
      }
      return { ok: false, code: "duplicate_name_conflict", message: "같은 이름의 파일이 있어 저장하지 않았습니다." };
    }

    /* ── 한 쌍 저장 ── */
    async function savePair(options) {
      var opts = options || {};
      var guard = requireToken();
      if (!guard.ok) return Object.assign({ ok: false, status: "failed", partial: false, reported: true }, guard);

      var built = Contract.buildPackage({
        draft: opts.draft,
        template: opts.template,
        savedAt: opts.savedAt,
        packageId: opts.packageId
      });
      if (!built.ok) {
        return Contract.buildUploadOutcome({
          json: { ok: false, code: built.code },
          pdf: { ok: false, code: built.code }
        });
      }

      var pdfCheck = Contract.validatePdfBytes(opts.pdfBytes);
      if (!pdfCheck.ok) {
        /* 무엇도 올리지 않는다. 조용한 부분 저장을 만들지 않는다. */
        return Contract.buildUploadOutcome({
          packageId: built.package.packageId,
          json: { ok: false, code: pdfCheck.code },
          pdf: { ok: false, code: pdfCheck.code }
        });
      }

      var planned = await planNames(guard, built.package.quote, opts.baseName);
      if (stale(guard.epoch)) return Object.assign(sessionChanged(), { status: "failed", partial: false });
      if (!planned.ok) {
        return Contract.buildUploadOutcome({
          packageId: built.package.packageId,
          json: { ok: false, code: planned.code, message: planned.message },
          pdf: { ok: false, code: planned.code, message: planned.message }
        });
      }

      var pair = Contract.buildPairBinding({
        packageId: built.package.packageId,
        createdAt: built.package.createdAt,
        baseName: planned.baseName,
        renamed: planned.renamed,
        jsonName: planned.json,
        pdfName: planned.pdf,
        draftFingerprint: built.package.contentFingerprint,
        pdfFingerprint: Contract.pdfFingerprint(opts.pdfBytes)
      });

      var jsonResult = await uploadFile({
        guard: guard,
        name: planned.json,
        mimeType: Contract.JSON_MIME,
        bytes: utf8Bytes(Contract.serializePackage(built.package))
      });
      if (stale(guard.epoch)) return Object.assign(sessionChanged(), { status: "failed", partial: false });
      var pdfResult = await uploadFile({
        guard: guard,
        name: planned.pdf,
        mimeType: Contract.PDF_MIME,
        bytes: normalizeBytes(opts.pdfBytes)
      });
      if (stale(guard.epoch)) return Object.assign(sessionChanged(), { status: "failed", partial: false });

      var outcome = Contract.buildUploadOutcome({
        packageId: built.package.packageId,
        pair: pair,
        json: jsonResult,
        pdf: pdfResult
      });
      outcome.baseName = planned.baseName;
      outcome.renamed = planned.renamed;
      return outcome;
    }

    /* ── 부분 실패 복구: 원래 쌍을 그대로 유지한 채 없는 쪽만 올린다 ──
       - 이름을 재계획하지 않는다(고정된 원래 이름을 쓴다).
       - 견적 내용이 바뀌었으면 이어서 저장하지 않고 새 쌍을 요구한다.
       - 유지된 파일이 아직 존재하고 소유되어 있는지 확인한 뒤에만 완료를 주장한다. */
    async function retryMissing(options) {
      var opts = options || {};
      var guard = requireToken();
      if (!guard.ok) return { ok: false, code: guard.code };

      var check = Contract.pairRetryGuard(opts.outcome, {
        draft: opts.draft,
        template: opts.template,
        pdfBytes: opts.pdfBytes
      });
      if (!check.ok) return check;
      var pair = check.pair;
      var target = check.target;

      var keptId = target === "pdf"
        ? (opts.outcome.json && opts.outcome.json.id)
        : (opts.outcome.pdf && opts.outcome.pdf.id);
      if (!keptId) {
        return { ok: false, code: "kept_file_unavailable", message: "이미 저장된 파일을 확인할 수 없어 이어서 저장하지 않았습니다." };
      }
      var verified = await verifyOwnedFile(keptId, guard);
      if (stale(guard.epoch)) return sessionChanged();
      if (!verified.ok) {
        return {
          ok: false,
          code: "kept_file_unavailable",
          detail: verified.code,
          message: "이미 저장된 파일이 삭제되었거나 소유 확인에 실패해 이어서 저장하지 않았습니다."
        };
      }

      var plannedName = target === "json" ? pair.jsonName : pair.pdfName;
      if (!plannedName) return { ok: false, code: "pending_pair_missing" };
      var takenCheck = await nameTaken(plannedName, guard);
      if (stale(guard.epoch)) return sessionChanged();
      if (!takenCheck.ok) {
        return { ok: false, code: "naming_check_unavailable", message: "파일 이름을 확인하지 못해 이어서 저장하지 않았습니다." };
      }
      if (takenCheck.taken) {
        /* 이름을 재계획하면 원래 쌍과 다른 이름이 되어 잘못 묶일 수 있다. 새 저장을 요구한다. */
        return {
          ok: false,
          code: "duplicate_name_conflict",
          message: "같은 이름의 파일이 이미 있어 이어서 저장하지 않았습니다. 새 견적서로 저장해 주세요."
        };
      }

      var missingResult;
      if (target === "json") {
        var built = Contract.buildPackage({
          draft: opts.draft,
          template: opts.template,
          savedAt: pair.createdAt,
          packageId: pair.packageId
        });
        if (!built.ok) return { ok: false, code: built.code };
        missingResult = await uploadFile({
          guard: guard,
          name: plannedName,
          mimeType: Contract.JSON_MIME,
          bytes: utf8Bytes(Contract.serializePackage(built.package))
        });
      } else {
        missingResult = await uploadFile({
          guard: guard,
          name: plannedName,
          mimeType: Contract.PDF_MIME,
          bytes: normalizeBytes(opts.pdfBytes)
        });
      }
      if (stale(guard.epoch)) return sessionChanged();

      var keptFile = { ok: true, id: keptId, name: target === "pdf" ? pair.jsonName : pair.pdfName };
      var outcome = Contract.buildUploadOutcome({
        packageId: pair.packageId,
        pair: pair,
        json: target === "json" ? missingResult : keptFile,
        pdf: target === "pdf" ? missingResult : keptFile
      });
      outcome.baseName = pair.baseName;
      outcome.renamed = pair.renamed;
      return outcome;
    }

    return Object.freeze({
      SCOPE_DRIVE_FILE: SCOPE_DRIVE_FILE,
      GIS_SRC: GIS_SRC,
      GAPI_SRC: GAPI_SRC,
      DRIVE_FILES_ENDPOINT: DRIVE_FILES_ENDPOINT,
      DRIVE_UPLOAD_ENDPOINT: DRIVE_UPLOAD_ENDPOINT,
      MAX_LIST_PAGES: MAX_LIST_PAGES,
      ownershipOf: ownershipOf,
      isConfigured: isConfigured,
      pickerReady: pickerReady,
      session: publicSession,
      connect: connect,
      disconnect: disconnect,
      listQuoteFiles: listQuoteFiles,
      verifyOwnedFile: verifyOwnedFile,
      openPicker: openPicker,
      openQuoteFile: openQuoteFile,
      uploadFile: uploadFile,
      savePair: savePair,
      retryMissing: retryMissing
    });
  }

  return Object.freeze({
    SCOPE_DRIVE_FILE: SCOPE_DRIVE_FILE,
    DEFAULT_SCOPES: DEFAULT_SCOPES.slice(),
    DRIVE_FILES_ENDPOINT: DRIVE_FILES_ENDPOINT,
    DRIVE_UPLOAD_ENDPOINT: DRIVE_UPLOAD_ENDPOINT,
    MAX_LIST_PAGES: MAX_LIST_PAGES,
    ownershipOf: ownershipOf,
    create: create
  });
});
