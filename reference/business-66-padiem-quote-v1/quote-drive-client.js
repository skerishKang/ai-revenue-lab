/* B66 — 고객 본인 Google Drive(BYOS) 저장·불러오기 클라이언트 (#3871 Slice B/C).
   이 모듈만 Google OAuth/Drive API 와 통신한다.

   절대 규칙
   - 최소 권한: 기본 범위는 drive.file(앱이 만든 파일/사용자가 선택한 파일) 하나다.
     전체 드라이브 목록 권한(drive.readonly 등)을 요청하지 않는다.
   - 접근 권한의 근거는 항상 연결된 Google 세션 + Drive 가 돌려준 파일 소유 정보다.
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
  var MAX_LIST_PAGE_SIZE = 100;
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

    /* 토큰은 이 클로저 안에만 존재한다. 어떤 저장소에도 기록하지 않는다. */
    var session = {
      connected: false,
      accessToken: "",
      scopes: [],
      expiresAt: 0,
      connectedAt: null,
      lastErrorCode: null
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
        lastErrorCode: session.lastErrorCode
      };
    }

    function requireToken() {
      if (!isConfigured()) return { ok: false, code: "drive_not_configured" };
      if (session.connected !== true || !session.accessToken) return { ok: false, code: "drive_not_connected" };
      if (session.expiresAt <= deps.now() + EXPIRY_SKEW_MS) {
        clearSession("drive_token_expired");
        return { ok: false, code: "drive_token_expired" };
      }
      return { ok: true, token: session.accessToken };
    }

    function clearSession(reasonCode) {
      session.connected = false;
      session.accessToken = "";
      session.scopes = [];
      session.expiresAt = 0;
      session.connectedAt = null;
      session.lastErrorCode = typeof reasonCode === "string" ? reasonCode : null;
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
          var request = prompt ? { prompt: prompt } : {};
          try {
            client.requestAccessToken(request);
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

    /* ── 연결 해제: 토큰 폐기 + 메모리 세션 완전 삭제(계정 전환 격리) ── */
    async function disconnect() {
      var token = session.accessToken;
      var wasConnected = session.connected === true;
      clearSession(null);
      if (!token || !deps.fetchImpl) return { ok: true, code: "signed_out", revoked: false };
      try {
        await deps.fetchImpl(DRIVE_REVOKE_ENDPOINT + "?token=" + encodeURIComponent(token), { method: "POST" });
        return { ok: true, code: "signed_out", revoked: true };
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

    /* ── 목록: 앱이 만들었거나 사용자가 선택한 파일 범위에서만 조회한다 ── */
    async function listQuoteFiles(options) {
      var guard = requireToken();
      if (!guard.ok) return Object.assign({ ok: false, files: [] }, guard);
      var opts = options || {};
      var pageSize = Math.min(Math.max(Number(opts.pageSize) || 20, 1), MAX_LIST_PAGE_SIZE);
      var query = "trashed = false and (mimeType = 'application/json' or mimeType = 'application/pdf')";
      var url = DRIVE_FILES_ENDPOINT + "?" + encodeQuery({
        q: query,
        fields: LIST_FIELDS,
        pageSize: pageSize,
        orderBy: "modifiedTime desc"
      });
      var response;
      try {
        response = await driveFetch(url, { method: "GET" }, guard.token);
      } catch (err) {
        return { ok: false, code: "network_error", files: [] };
      }
      if (response.status === 401) {
        clearSession("drive_token_expired");
        return { ok: false, code: "drive_token_expired", files: [] };
      }
      if (!response.ok) {
        var failure = await readError(response, "drive_list_failed");
        return { ok: false, code: failure.code, status: failure.status, message: failure.message, files: [] };
      }
      var data = null;
      try {
        data = await response.json();
      } catch (err) {
        return { ok: false, code: "invalid_response", files: [] };
      }
      var files = Array.isArray(data && data.files) ? data.files : [];
      /* 다른 계정이 공유하지 않은 파일은 Drive 가 애초에 돌려주지 않는다.
         그래도 owners.me 로 한 번 더 확인해 소유하지 않은 파일은 걸러낸다. */
      var visible = files.filter(function (file) {
        if (!file || typeof file.id !== "string" || !file.id) return false;
        if (file.trashed === true) return false;
        if (Array.isArray(file.owners) && file.owners.length) {
          return file.owners.some(function (owner) { return owner && owner.me === true; });
        }
        return true;
      }).map(function (file) {
        return {
          id: file.id,
          name: typeof file.name === "string" ? file.name : "",
          mimeType: typeof file.mimeType === "string" ? file.mimeType : "",
          size: Number(file.size) || 0,
          modifiedTime: typeof file.modifiedTime === "string" ? file.modifiedTime : null
        };
      });
      return { ok: true, files: visible };
    }

    async function existingNames() {
      var listed = await listQuoteFiles({ pageSize: MAX_LIST_PAGE_SIZE });
      if (!listed.ok) return listed;
      return { ok: true, names: listed.files.map(function (file) { return file.name; }) };
    }

    /* ── Picker: 사용자가 직접 파일을 고른다. 없으면 목록 기반 선택으로 대체한다 ── */
    function openPicker(options) {
      var opts = options || {};
      var guard = requireToken();
      if (!guard.ok) return Promise.resolve(Object.assign({ ok: false, picked: [] }, guard));
      if (!appId || !developerKey) {
        return Promise.resolve({ ok: false, code: "picker_unavailable", picked: [] });
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

    /* ── 파일 읽기: 소유 검증 → 크기 → 계약 검증 → QuoteCore 재계산 ── */
    async function openQuoteFile(fileId, options) {
      var opts = options || {};
      var guard = requireToken();
      if (!guard.ok) return Object.assign({ ok: false }, guard);
      var id = typeof fileId === "string" ? fileId.trim() : "";
      if (!id) return { ok: false, code: "invalid_file_id" };

      var metaUrl = DRIVE_FILES_ENDPOINT + "/" + encodeURIComponent(id) + "?" + encodeQuery({
        fields: "id,name,mimeType,size,trashed,modifiedTime,owners,capabilities",
        supportsAllDrives: false
      });
      var metaResponse;
      try {
        metaResponse = await driveFetch(metaUrl, { method: "GET" }, guard.token);
      } catch (err) {
        return { ok: false, code: "network_error" };
      }
      if (metaResponse.status === 401) {
        clearSession("drive_token_expired");
        return { ok: false, code: "drive_token_expired" };
      }
      if (metaResponse.status === 404 || metaResponse.status === 403) {
        /* 다른 Google 계정의 파일이거나 권한이 없다. 내용을 추측하지 않고 거부한다. */
        return {
          ok: false,
          code: metaResponse.status === 404 ? "drive_file_not_found" : "drive_file_access_denied",
          message: "선택한 파일을 이 Google 계정으로 열 수 없습니다."
        };
      }
      if (!metaResponse.ok) {
        var metaFailure = await readError(metaResponse, "drive_metadata_failed");
        return { ok: false, code: metaFailure.code, status: metaFailure.status, message: metaFailure.message };
      }
      var meta = null;
      try {
        meta = await metaResponse.json();
      } catch (err) {
        return { ok: false, code: "invalid_response" };
      }
      if (!meta || typeof meta.id !== "string") return { ok: false, code: "invalid_response" };
      if (meta.trashed === true) return { ok: false, code: "drive_file_trashed" };

      /* 소유 검증: 연결된 계정이 소유하지 않은 파일은 열지 않는다. */
      if (Array.isArray(meta.owners) && meta.owners.length &&
          !meta.owners.some(function (owner) { return owner && owner.me === true; })) {
        return {
          ok: false,
          code: "drive_file_not_owned_by_connected_account",
          message: "이 Google 계정이 소유한 파일만 불러올 수 있습니다."
        };
      }
      var size = Number(meta.size);
      if (Number.isFinite(size) && size > Contract.MAX_JSON_BYTES) {
        return { ok: false, code: "json_too_large", message: "견적 JSON 파일이 지원 크기를 초과했습니다." };
      }

      var mediaUrl = DRIVE_FILES_ENDPOINT + "/" + encodeURIComponent(id) + "?alt=media";
      var mediaResponse;
      try {
        mediaResponse = await driveFetch(mediaUrl, { method: "GET" }, guard.token);
      } catch (err) {
        return { ok: false, code: "network_error" };
      }
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

      var parsed = Contract.readPackage(text, {
        byteLength: Number.isFinite(size) ? size : undefined
      });
      if (!parsed.ok) {
        return { ok: false, code: parsed.code, message: "선택한 파일을 견적 데이터로 읽을 수 없습니다. (" + parsed.code + ")" };
      }
      var imported = Contract.importPackage(parsed.package, { templates: opts.templates });
      if (!imported.ok) return { ok: false, code: imported.code };

      return {
        ok: true,
        file: {
          id: meta.id,
          name: typeof meta.name === "string" ? meta.name : "",
          size: Number.isFinite(size) ? size : null,
          modifiedTime: typeof meta.modifiedTime === "string" ? meta.modifiedTime : null
        },
        packageId: parsed.package.packageId,
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
      var guard = requireToken();
      if (!guard.ok) return Object.assign({ ok: false }, guard);
      var bytes = normalizeBytes(options && options.bytes);
      if (!bytes) return { ok: false, code: "upload_bytes_missing" };
      var name = typeof options.name === "string" ? options.name.trim() : "";
      var mimeType = typeof options.mimeType === "string" ? options.mimeType : "";
      if (!name || !mimeType) return { ok: false, code: "upload_metadata_missing" };
      if (Array.isArray(options.takenNames) && options.takenNames.indexOf(name) !== -1) {
        /* 덮어쓰기 방지: 계획한 이름이 이미 있으면 만들지 않는다. */
        return { ok: false, code: "duplicate_name_conflict", message: "같은 이름의 파일이 있어 덮어쓰지 않았습니다." };
      }

      var boundary = "b66-drive-boundary-0123456789";
      var metadata = { name: name, mimeType: mimeType };
      var body = multipartBody(metadata, bytes, mimeType, boundary);
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

    /* ── 한 쌍 저장: PDF 바이트를 먼저 검증해 불필요한 외톨이 파일을 줄인다 ── */
    async function savePair(options) {
      var opts = options || {};
      var guard = requireToken();
      if (!guard.ok) return Object.assign({ ok: false, status: "failed", partial: false }, guard);

      var built = Contract.buildPackage({
        draft: opts.draft,
        template: opts.template,
        savedAt: opts.savedAt,
        packageId: opts.packageId
      });
      if (!built.ok) {
        return Contract.buildUploadOutcome({
          packageId: null,
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

      var names = await existingNames();
      var taken = names.ok ? names.names : [];
      var planned = Contract.planUniqueFileNames({
        draft: built.package.quote,
        baseName: opts.baseName,
        existingNames: taken
      });
      if (!planned.ok) {
        return Contract.buildUploadOutcome({
          packageId: built.package.packageId,
          json: { ok: false, code: planned.code },
          pdf: { ok: false, code: planned.code }
        });
      }

      var jsonText = Contract.serializePackage(built.package);
      var jsonBytes = utf8Bytes(jsonText);

      var jsonResult = await uploadFile({
        name: planned.json,
        mimeType: Contract.JSON_MIME,
        bytes: jsonBytes,
        takenNames: taken
      });
      var pdfResult = await uploadFile({
        name: planned.pdf,
        mimeType: Contract.PDF_MIME,
        bytes: normalizeBytes(opts.pdfBytes),
        takenNames: taken.concat(jsonResult.ok ? [planned.json] : [])
      });

      var outcome = Contract.buildUploadOutcome({
        packageId: built.package.packageId,
        json: jsonResult,
        pdf: pdfResult
      });
      outcome.baseName = planned.baseName;
      outcome.renamed = planned.renamed;
      return outcome;
    }

    /* ── 부분 실패 복구: 없는 쪽만 다시 올린다(같은 packageId 재사용) ── */
    async function retryMissing(options) {
      var opts = options || {};
      var outcome = opts.outcome;
      if (!outcome || outcome.partial !== true || !outcome.missing) {
        return { ok: false, code: "nothing_to_retry" };
      }
      var built = Contract.buildPackage({
        draft: opts.draft,
        template: opts.template,
        savedAt: opts.savedAt,
        packageId: outcome.packageId || opts.packageId
      });
      if (!built.ok) return { ok: false, code: built.code };

      var names = await existingNames();
      var taken = names.ok ? names.names : [];
      var planned = Contract.planUniqueFileNames({
        draft: built.package.quote,
        baseName: opts.baseName,
        existingNames: taken
      });
      if (!planned.ok) return { ok: false, code: planned.code };

      if (outcome.missing === "json") {
        var jsonResult = await uploadFile({
          name: planned.json,
          mimeType: Contract.JSON_MIME,
          bytes: utf8Bytes(Contract.serializePackage(built.package)),
          takenNames: taken
        });
        return Contract.buildUploadOutcome({
          packageId: built.package.packageId,
          json: jsonResult,
          pdf: { ok: true, id: outcome.pdf && outcome.pdf.id, name: outcome.pdf && outcome.pdf.name }
        });
      }
      var pdfCheck = Contract.validatePdfBytes(opts.pdfBytes);
      if (!pdfCheck.ok) {
        return Contract.buildUploadOutcome({
          packageId: built.package.packageId,
          json: { ok: true, id: outcome.json && outcome.json.id, name: outcome.json && outcome.json.name },
          pdf: { ok: false, code: pdfCheck.code }
        });
      }
      var pdfResult = await uploadFile({
        name: planned.pdf,
        mimeType: Contract.PDF_MIME,
        bytes: normalizeBytes(opts.pdfBytes),
        takenNames: taken
      });
      return Contract.buildUploadOutcome({
        packageId: built.package.packageId,
        json: { ok: true, id: outcome.json && outcome.json.id, name: outcome.json && outcome.json.name },
        pdf: pdfResult
      });
    }

    return Object.freeze({
      SCOPE_DRIVE_FILE: SCOPE_DRIVE_FILE,
      GIS_SRC: GIS_SRC,
      GAPI_SRC: GAPI_SRC,
      DRIVE_FILES_ENDPOINT: DRIVE_FILES_ENDPOINT,
      DRIVE_UPLOAD_ENDPOINT: DRIVE_UPLOAD_ENDPOINT,
      isConfigured: isConfigured,
      session: publicSession,
      connect: connect,
      disconnect: disconnect,
      listQuoteFiles: listQuoteFiles,
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
    create: create
  });
});
