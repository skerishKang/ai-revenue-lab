/* B66 — 고객 본인 Google Drive(BYOS) 견적 저장·불러오기 계약 (#3871 Slice A).
   이 모듈은 저장 데이터 계약만 소유한다. 네트워크·OAuth·Picker 는 quote-drive-client.js,
   화면 연결은 quote-drive-ui.js 가 소유한다.

   절대 규칙
   - 저장된 합계는 어떤 경우에도 계산 권위가 아니다. 불러오면 항상 QuoteCore 가 다시 계산한다.
   - 파일 안의 사용자 ID/이메일/계정 값은 접근 권한의 근거로 쓰지 않는다(명시 거부).
   - 승인되지 않았거나 비활성인 템플릿/Skill 을 임의의 다른 것으로 대체하지 않는다.
   - 모델 호출은 0이다. Google Sheets 변환도 없다.
   DOM 없음. 브라우저/Node 양쪽에서 실행된다. */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./quote-core.js"));
  } else {
    root.B66QuoteDriveContract = factory(root.QuoteCore);
  }
})(typeof self !== "undefined" ? self : this, function (Core) {
  "use strict";

  if (!Core) throw new Error("QuoteCore is required");

  var CONTRACT_ID = "b66.quote-drive.v1";
  var PACKAGE_KIND = "b66.quote-package";
  var CURRENT_SCHEMA_VERSION = 1;
  var SUPPORTED_SCHEMA_VERSIONS = [1];
  var RENDERER_CONTRACT = "quote-template-renderer.v1";

  var JSON_MIME = "application/json";
  var PDF_MIME = "application/pdf";
  var MAX_JSON_BYTES = 512 * 1024;
  var MAX_PDF_BYTES = 32 * 1024 * 1024;
  var MIN_PDF_BYTES = 64;
  var MAX_FILE_NAME_CHARS = 120;
  var MAX_DUPLICATE_SUFFIX = 999;
  var PDF_MAGIC = "%PDF-";
  var PDF_MAGIC_BYTES = [37, 80, 68, 70, 45]; /* % P D F - */
  var MAX_MANIFEST_TEXT_CHARS = 120;

  /* 파일 안의 신원 주장은 권한 근거가 될 수 없으므로 계약 수준에서 금지한다. */
  var FORBIDDEN_IDENTITY_KEYS = [
    "owner", "ownerEmail", "ownerId", "user", "userId", "userEmail",
    "account", "accountId", "accountEmail", "googleAccount", "permission",
    "permissions", "grantedTo", "authorizedAccount"
  ];

  var ALLOWED_TOP_LEVEL_KEYS = [
    "kind", "contract", "schemaVersion", "packageId", "createdAt",
    "quote", "template", "assets", "manifest", "totalsAuthority", "totals", "app"
  ];

  var UNSAFE_JSON_KEYS = ["__proto__", "constructor", "prototype"];

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function byteLength(text) {
    if (typeof Buffer === "function" && typeof Buffer.byteLength === "function") {
      return Buffer.byteLength(String(text), "utf8");
    }
    if (typeof TextEncoder === "function") return new TextEncoder().encode(String(text)).length;
    return String(text).length;
  }

  function boundedText(value, maxLength) {
    if (typeof value !== "string") return null;
    var text = value.trim();
    if (!text) return null;
    return text.slice(0, maxLength);
  }

  function isSupportedSchemaVersion(version) {
    return SUPPORTED_SCHEMA_VERSIONS.indexOf(version) !== -1;
  }

  /* ── 파일명 규칙 ──
     Drive 파일명에서 쓸 수 없는 문자를 제거하고 길이를 제한한다. */
  function sanitizeFileNamePart(raw, fallback) {
    var text = String(raw == null ? "" : raw)
      .replace(/[\u0000-\u001f\u007f]/g, " ")
      .replace(/[\\/:*?"<>|]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    if (!text) text = String(fallback || "");
    return text.slice(0, MAX_FILE_NAME_CHARS);
  }

  function buildBaseName(draft) {
    var quoteNo = sanitizeFileNamePart(draft && draft.meta && draft.meta.quoteNo, "견적");
    var who = boundedText(draft && draft.recipient && draft.recipient.company, MAX_MANIFEST_TEXT_CHARS) ||
      boundedText(draft && draft.recipient && draft.recipient.person, MAX_MANIFEST_TEXT_CHARS) ||
      "견적";
    return sanitizeFileNamePart("견적서_" + quoteNo + "_" + who, "견적서");
  }

  function withExtension(stem, extension) {
    var base = String(stem || "").slice(0, MAX_FILE_NAME_CHARS - extension.length);
    if (!base) base = "견적서";
    return base + extension;
  }

  /* 중복 파일명은 기존 파일을 덮어쓰지 않고 접미사를 붙여 새 파일로 만든다. */
  function planUniqueFileNames(options) {
    var opts = options || {};
    var stem = typeof opts.baseName === "string" && opts.baseName.trim()
      ? opts.baseName.trim()
      : buildBaseName(opts.draft);
    stem = sanitizeFileNamePart(stem, "견적서");
    var taken = Array.isArray(opts.existingNames) ? opts.existingNames : [];

    var json = uniqueName(withExtension(stem, ".json"), taken);
    if (!json) return { ok: false, code: "duplicate_name_limit" };
    var pdf = uniqueName(withExtension(stem, ".pdf"), taken.concat([json.name]));
    if (!pdf) return { ok: false, code: "duplicate_name_limit" };

    return {
      ok: true,
      baseName: stem,
      json: json.name,
      pdf: pdf.name,
      renamed: json.renamed === true || pdf.renamed === true
    };
  }

  function uniqueName(candidate, taken) {
    if (taken.indexOf(candidate) === -1) return { name: candidate, renamed: false };
    var extension = candidate.slice(candidate.lastIndexOf("."));
    var stem = extension ? candidate.slice(0, candidate.lastIndexOf(".")) : candidate;
    for (var suffix = 2; suffix <= MAX_DUPLICATE_SUFFIX; suffix += 1) {
      var next = withExtension(stem + "-" + suffix, extension);
      if (taken.indexOf(next) === -1) return { name: next, renamed: true };
    }
    return null;
  }

  /* ── PDF 바이트 검증 ──
     인증된 렌더러가 만든 PDF 만 저장 대상으로 받는다. 형식만 확인하고 내용을 해석하지 않는다. */
  function validatePdfBytes(bytes) {
    if (bytes == null) return { ok: false, code: "pdf_missing" };
    var length = bytes.byteLength !== undefined ? bytes.byteLength : bytes.length;
    if (!Number.isFinite(length) || length <= 0) return { ok: false, code: "pdf_missing" };
    if (length < MIN_PDF_BYTES) return { ok: false, code: "pdf_too_small" };
    if (length > MAX_PDF_BYTES) return { ok: false, code: "pdf_too_large" };
    for (var i = 0; i < PDF_MAGIC_BYTES.length; i += 1) {
      if (bytes[i] !== PDF_MAGIC_BYTES[i]) return { ok: false, code: "pdf_format_invalid" };
    }
    return { ok: true, byteLength: length };
  }

  /* ── 저장 패키지 생성 ──
     D1 서버 스냅샷(#3405)이 버리는 detailGroups/calculationPolicy 를 포함해
     QuoteDraft 전체 편집 데이터를 보존한다. */
  function normalizeTemplateReference(raw) {
    if (raw === undefined || raw === null) return null;
    if (!isPlainObject(raw)) return null;
    var savedSkillId = boundedText(raw.savedSkillId, 64);
    var fingerprint = boundedText(raw.fingerprint, 128);
    if (!savedSkillId) return null;
    var ref = { savedSkillId: savedSkillId };
    if (fingerprint) ref.fingerprint = fingerprint;
    var rendererContract = boundedText(raw.rendererContract, 64);
    if (rendererContract) ref.rendererContract = rendererContract;
    var label = boundedText(raw.label, MAX_MANIFEST_TEXT_CHARS);
    if (label) ref.label = label;
    return ref;
  }

  function buildPackage(options) {
    var opts = options || {};
    var draft = Core.normalizeDraft(opts.draft);
    if (!draft) return { ok: false, code: "invalid_draft" };
    var guard = assertLosslessDraft(opts.draft);
    if (!guard.lossless) return { ok: false, code: "draft_lossy_round_trip", lost: guard.lost };

    var packageId = boundedText(opts.packageId, 64) || createPackageId(opts);
    var savedAt = boundedText(opts.savedAt, 40) || null;
    var totalItems = draft.items.length;
    var baseName = buildBaseName(draft);

    var template = normalizeTemplateReference(opts.template);
    var assets = {
      json: { role: "quote-json", mimeType: JSON_MIME, packageId: packageId },
      pdf: { role: "quote-pdf", mimeType: PDF_MIME, packageId: packageId }
    };

    var pkg = {
      kind: PACKAGE_KIND,
      contract: CONTRACT_ID,
      schemaVersion: CURRENT_SCHEMA_VERSION,
      packageId: packageId,
      createdAt: savedAt,
      quote: draft,
      template: template,
      assets: assets,
      manifest: {
        quoteNo: boundedText(draft.meta.quoteNo, 80),
        issueDate: boundedText(draft.meta.issueDate, 40),
        recipientCompany: boundedText(draft.recipient.company, MAX_MANIFEST_TEXT_CHARS),
        recipientPerson: boundedText(draft.recipient.person, MAX_MANIFEST_TEXT_CHARS),
        itemCount: totalItems,
        detailGroupCount: Array.isArray(draft.detailGroups) ? draft.detailGroups.length : 0,
        baseName: baseName,
        savedAt: savedAt
      },
      totalsAuthority: "quote-core",
      totals: null,
      app: { product: "b66", rendererContract: RENDERER_CONTRACT, modelCalls: 0 }
    };
    return { ok: true, package: pkg, baseName: baseName };
  }

  function createPackageId(opts) {
    var now = opts && opts.now ? opts.now : null;
    var stamp = String(now instanceof Date ? now.getTime() : Date.now());
    var random = "";
    if (typeof opts === "object" && opts && typeof opts.random === "function") {
      random = String(opts.random());
    } else if (typeof Math !== "undefined" && typeof Math.random === "function") {
      random = Math.random().toString(36).slice(2, 10);
    }
    return ("pkg-" + stamp + "-" + random).replace(/[^0-9a-zA-Z-]/g, "").slice(0, 64);
  }

  /* 저장 전 무손실 검증: QuoteCore 정규화가 편집 데이터를 버리면 저장하지 않는다. */
  function assertLosslessDraft(rawDraft) {
    var normalized = Core.normalizeDraft(rawDraft);
    if (!normalized) return { lossless: false, lost: ["draft"], draft: null };
    var source = isPlainObject(rawDraft) ? rawDraft : {};
    var lost = [];
    if (Array.isArray(source.detailGroups) && source.detailGroups.length &&
        !Array.isArray(normalized.detailGroups)) lost.push("detailGroups");
    if (source.calculationPolicy && !normalized.calculationPolicy) lost.push("calculationPolicy");
    if (source.meta && source.meta.projectName && !normalized.meta.projectName) {
      lost.push("meta.projectName");
    }
    if (Array.isArray(source.items) && source.items.length !== normalized.items.length) {
      lost.push("items.length");
    }
    if (Array.isArray(source.items) && Array.isArray(normalized.items)) {
      source.items.forEach(function (item, index) {
        var target = normalized.items[index];
        if (!target) return;
        if (item && item.spec && !target.spec) lost.push("items[].spec");
        if (item && item.unit && !target.unit) lost.push("items[].unit");
        if (item && item.note && !target.note) lost.push("items[].note");
      });
    }
    return { lossless: lost.length === 0, lost: lost, draft: normalized };
  }

  function serializePackage(pkg) {
    if (!isPlainObject(pkg)) return null;
    return JSON.stringify(pkg, null, 2);
  }

  /* ── 읽기 검증 ──
     크기 → JSON 파싱(프로토타입 오염 키 거부) → 스키마 → 신원 주장 거부 → QuoteDraft 정규화 */
  function parseJsonSafely(text) {
    return JSON.parse(text, function (key, value) {
      if (UNSAFE_JSON_KEYS.indexOf(key) !== -1) {
        var error = new Error("unsafe_json_key");
        error.code = "unsafe_json_key";
        throw error;
      }
      return value;
    });
  }

  function readPackage(text, options) {
    var opts = options || {};
    if (typeof text !== "string") return { ok: false, code: "invalid_json_text" };
    var size = Number.isFinite(Number(opts.byteLength)) ? Number(opts.byteLength) : byteLength(text);
    if (size > MAX_JSON_BYTES) return { ok: false, code: "json_too_large" };
    if (!text.trim()) return { ok: false, code: "invalid_json_text" };

    var raw;
    try {
      raw = parseJsonSafely(text);
    } catch (err) {
      return { ok: false, code: (err && err.code) === "unsafe_json_key" ? "unsafe_json_key" : "invalid_json" };
    }
    return normalizePackage(raw, { byteLength: size });
  }

  function normalizePackage(raw, options) {
    var opts = options || {};
    if (!isPlainObject(raw)) return { ok: false, code: "invalid_package" };
    if (raw.kind !== PACKAGE_KIND) return { ok: false, code: "package_kind_unsupported" };
    if (raw.contract !== CONTRACT_ID) return { ok: false, code: "contract_unsupported" };

    var version = raw.schemaVersion;
    if (!Number.isInteger(version)) return { ok: false, code: "schema_version_missing" };
    if (!isSupportedSchemaVersion(version)) {
      if (version > CURRENT_SCHEMA_VERSION) return { ok: false, code: "schema_version_newer_than_supported" };
      return { ok: false, code: "schema_version_unsupported" };
    }

    if (raw.totalsAuthority !== undefined && raw.totalsAuthority !== "quote-core") {
      return { ok: false, code: "totals_authority_unsupported" };
    }

    var keys = Object.keys(raw);
    for (var i = 0; i < keys.length; i += 1) {
      var key = keys[i];
      if (ALLOWED_TOP_LEVEL_KEYS.indexOf(key) === -1) return { ok: false, code: "unsupported_package_field" };
      if (FORBIDDEN_IDENTITY_KEYS.indexOf(key) !== -1) {
        return { ok: false, code: "identity_authority_field_rejected" };
      }
    }

    var draft = Core.normalizeDraft(raw.quote);
    if (!draft) return { ok: false, code: "invalid_quote_draft" };

    var template = normalizeTemplateReference(raw.template);
    if (raw.template !== undefined && raw.template !== null && !template) {
      return { ok: false, code: "invalid_template_reference" };
    }

    var packageId = boundedText(raw.packageId, 64);
    var manifest = isPlainObject(raw.manifest) ? clone(raw.manifest) : {};

    var pkg = {
      kind: PACKAGE_KIND,
      contract: CONTRACT_ID,
      schemaVersion: CURRENT_SCHEMA_VERSION,
      packageId: packageId || null,
      createdAt: boundedText(raw.createdAt, 40),
      quote: draft,
      template: template,
      assets: isPlainObject(raw.assets) ? clone(raw.assets) : null,
      manifest: manifest,
      totalsAuthority: "quote-core",
      /* 저장된 합계는 절대 계산 권위가 아니다. 값이 있어도 즉시 폐기한다. */
      totals: null,
      app: isPlainObject(raw.app) ? clone(raw.app) : null
    };

    return {
      ok: true,
      package: pkg,
      byteLength: Number.isFinite(Number(opts.byteLength)) ? Number(opts.byteLength) : byteLength(JSON.stringify(pkg)),
      totalsIgnored: raw.totals !== undefined && raw.totals !== null
    };
  }

  /* ── 템플릿 참조 검증 ──
     지원하지 않거나 비활성인 Skill 을 다른 템플릿으로 대체하지 않는다. */
  function resolveTemplateReference(ref, availableTemplates) {
    if (!ref) return { status: "none", reason: null, resolved: null };
    var list = Array.isArray(availableTemplates) ? availableTemplates : [];
    var match = null;
    for (var i = 0; i < list.length; i += 1) {
      var candidate = list[i];
      if (candidate && candidate.savedSkillId === ref.savedSkillId) { match = candidate; break; }
    }
    if (!match) {
      return { status: "unresolved", reason: "saved_skill_unavailable", resolved: null };
    }
    if (match.approved !== true || match.active === false) {
      return { status: "inactive", reason: "saved_skill_inactive", resolved: match };
    }
    if (ref.fingerprint && match.fingerprint && ref.fingerprint !== match.fingerprint) {
      return { status: "mismatch", reason: "template_fingerprint_mismatch", resolved: match };
    }
    return { status: "resolved", reason: null, resolved: match };
  }

  /* ── 불러오기 → QuoteCore 재계산 ── */
  function importPackage(pkg, options) {
    var opts = options || {};
    var normalized;
    if (isPlainObject(pkg) && pkg.kind === PACKAGE_KIND) {
      var result = normalizePackage(pkg, {});
      if (!result.ok) return { ok: false, code: result.code };
      normalized = result.package;
    } else {
      return { ok: false, code: "invalid_package" };
    }

    var draft = Core.normalizeDraft(normalized.quote);
    if (!draft) return { ok: false, code: "invalid_quote_draft" };

    var totals = Core.computeDraftTotals(draft);
    if (!totals) return { ok: false, code: "recalculation_failed" };

    var template = resolveTemplateReference(normalized.template, opts.templates);
    var warnings = [];
    if (template.status === "unresolved") warnings.push("saved_skill_unavailable");
    if (template.status === "inactive") warnings.push("saved_skill_inactive");
    if (template.status === "mismatch") warnings.push("template_fingerprint_mismatch");

    return {
      ok: true,
      draft: draft,
      totals: totals,
      template: template,
      warnings: warnings,
      totalsAuthority: "quote-core",
      recalculated: true,
      /* 인증 PDF 경로는 템플릿이 해결된 경우에만 준비된다. 대체 템플릿을 자동 선택하지 않는다. */
      certifiedPdfReady: template.status === "resolved",
      packageId: normalized.packageId,
      schemaVersion: normalized.schemaVersion
    };
  }

  /* ── 업로드 결과 · 부분 실패 ──
     한쪽만 저장된 상태를 조용히 넘기지 않고 정확한 코드와 복구 방법을 돌려준다. */
  function buildUploadOutcome(options) {
    var opts = options || {};
    var jsonResult = opts.json || null;
    var pdfResult = opts.pdf || null;
    var jsonOk = Boolean(jsonResult && jsonResult.ok === true);
    var pdfOk = Boolean(pdfResult && pdfResult.ok === true);

    var status = "complete";
    var code = "saved";
    var partial = false;
    var missing = null;
    var message = "견적 JSON과 PDF를 내 Google Drive에 저장했습니다.";

    if (jsonOk && pdfOk) {
      status = "complete";
    } else if (jsonOk && !pdfOk) {
      status = "partial_json";
      code = pdfResult && pdfResult.code ? pdfResult.code : "pdf_upload_failed";
      partial = true;
      missing = "pdf";
      message = "견적 JSON은 저장했지만 PDF 저장에 실패했습니다. PDF만 다시 저장할 수 있습니다.";
    } else if (!jsonOk && pdfOk) {
      status = "partial_pdf";
      code = jsonResult && jsonResult.code ? jsonResult.code : "json_upload_failed";
      partial = true;
      missing = "json";
      message = "PDF는 저장했지만 견적 JSON 저장에 실패했습니다. JSON만 다시 저장할 수 있습니다.";
    } else {
      status = "failed";
      code = jsonResult && jsonResult.code ? jsonResult.code : "upload_failed";
      message = "Google Drive 저장에 실패했습니다. 연결 상태와 남은 용량을 확인한 뒤 다시 시도해 주세요.";
    }

    var errorText = null;
    if (!jsonOk && jsonResult && jsonResult.message) errorText = jsonResult.message;
    if (!pdfOk && pdfResult && pdfResult.message && !errorText) errorText = pdfResult.message;

    return {
      ok: status === "complete",
      status: status,
      code: code,
      partial: partial,
      missing: missing,
      /* 부분 실패는 반드시 화면에 보고되어야 한다. 조용한 성공으로 표시하지 않는다. */
      reported: true,
      retryable: partial === true,
      recovery: partial ? { action: "retry_missing", target: missing } : null,
      message: message,
      errorText: errorText,
      packageId: opts.packageId || null,
      json: jsonOk ? { id: jsonResult.id, name: jsonResult.name, mimeType: JSON_MIME } : null,
      pdf: pdfOk ? { id: pdfResult.id, name: pdfResult.name, mimeType: PDF_MIME } : null
    };
  }

  return Object.freeze({
    CONTRACT_ID: CONTRACT_ID,
    PACKAGE_KIND: PACKAGE_KIND,
    CURRENT_SCHEMA_VERSION: CURRENT_SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS: SUPPORTED_SCHEMA_VERSIONS.slice(),
    RENDERER_CONTRACT: RENDERER_CONTRACT,
    JSON_MIME: JSON_MIME,
    PDF_MIME: PDF_MIME,
    MAX_JSON_BYTES: MAX_JSON_BYTES,
    MAX_PDF_BYTES: MAX_PDF_BYTES,
    MIN_PDF_BYTES: MIN_PDF_BYTES,
    MAX_FILE_NAME_CHARS: MAX_FILE_NAME_CHARS,
    MAX_DUPLICATE_SUFFIX: MAX_DUPLICATE_SUFFIX,
    PDF_MAGIC: PDF_MAGIC,
    FORBIDDEN_IDENTITY_KEYS: FORBIDDEN_IDENTITY_KEYS.slice(),
    ALLOWED_TOP_LEVEL_KEYS: ALLOWED_TOP_LEVEL_KEYS.slice(),
    isSupportedSchemaVersion: isSupportedSchemaVersion,
    sanitizeFileNamePart: sanitizeFileNamePart,
    buildBaseName: buildBaseName,
    planUniqueFileNames: planUniqueFileNames,
    validatePdfBytes: validatePdfBytes,
    normalizeTemplateReference: normalizeTemplateReference,
    assertLosslessDraft: assertLosslessDraft,
    buildPackage: buildPackage,
    serializePackage: serializePackage,
    readPackage: readPackage,
    normalizePackage: normalizePackage,
    resolveTemplateReference: resolveTemplateReference,
    importPackage: importPackage,
    buildUploadOutcome: buildUploadOutcome
  });
});
