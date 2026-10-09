/* B66 — 고객 본인 Google Drive(BYOS) 견적 저장·불러오기 계약 (#3871 Slice A).
   이 모듈은 저장 데이터 계약만 소유한다. 네트워크·OAuth·Picker 는 quote-drive-client.js,
   화면 연결은 quote-drive-ui.js 가 소유한다.

   절대 규칙
   - 저장된 합계는 어떤 경우에도 계산 권위가 아니다. 불러오면 항상 QuoteCore 가 다시 계산한다.
   - 파일 안의 사용자 ID/이메일/계정 값은 접근 권한의 근거로 쓰지 않는다(명시 거부).
   - 승인되지 않았거나 비활성인 템플릿/Skill 을 임의의 다른 것으로 대체하지 않는다.
     템플릿 권위를 확인할 수 없으면 편집기에 적용하지 않는다.
   - 무손실은 필드 단위로 증명한다. 편집 데이터가 하나라도 달라지면 저장도 불러오기도 거부한다.
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
    "contentFingerprint", "quote", "template", "assets", "manifest",
    "totalsAuthority", "totals", "app"
  ];

  var UNSAFE_JSON_KEYS = ["__proto__", "constructor", "prototype"];

  var ITEM_FIELDS = ["id", "name", "qty", "unitPrice", "spec", "unit", "note"];
  var DETAIL_ITEM_FIELDS = ["id", "name", "spec", "unit", "qty", "unitPrice", "note", "section"];

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

  /* ── 결정적 직렬화 · 지문 ──
     내용 지문은 견적 편집 데이터와 템플릿 참조 전체에 대해 계산한다.
     부분 실패 재시도가 다른 내용을 같은 쌍으로 묶는 것을 막는 근거다. */
  function stableStringify(value) {
    if (value === null || typeof value !== "object") {
      return JSON.stringify(value === undefined ? null : value);
    }
    if (Array.isArray(value)) return "[" + value.map(stableStringify).join(",") + "]";
    var keys = Object.keys(value).sort();
    return "{" + keys.map(function (key) {
      return JSON.stringify(key) + ":" + stableStringify(value[key]);
    }).join(",") + "}";
  }

  function fnv1a(text) {
    var hash = 0x811c9dc5;
    var source = String(text);
    for (var index = 0; index < source.length; index += 1) {
      hash ^= source.charCodeAt(index);
      hash = Math.imul(hash, 0x01000193) >>> 0;
    }
    return ("0000000" + hash.toString(16)).slice(-8);
  }

  function fingerprintOf(value) {
    return "fnv1a-" + fnv1a(stableStringify(value));
  }

  function normalizeBytesLike(bytes) {
    if (bytes == null) return null;
    if (bytes instanceof Uint8Array) return bytes;
    if (typeof ArrayBuffer !== "undefined" && bytes instanceof ArrayBuffer) return new Uint8Array(bytes);
    if (Array.isArray(bytes)) return new Uint8Array(bytes);
    return null;
  }

  function pdfFingerprint(bytes) {
    var data = normalizeBytesLike(bytes);
    if (!data || !data.length) return null;
    var parts = [];
    for (var index = 0; index < data.length; index += 1) parts.push(data[index]);
    return "fnv1a-" + fnv1a(parts.join(","));
  }

  /* ── 편집 데이터 필드 단위 무손실 검증 ──
     QuoteCore 정규화가 보존해야 하는 편집 필드 전체를 나열하고
     원본과 정규화 결과를 필드마다 비교한다. 하나라도 다르면 손실로 본다. */
  function sameField(rawValue, normalizedValue) {
    var rawEmpty = rawValue === undefined || rawValue === null || rawValue === "";
    var normEmpty = normalizedValue === undefined || normalizedValue === null || normalizedValue === "";
    if (rawEmpty || normEmpty) return rawEmpty && normEmpty;
    if (typeof rawValue === "number" || typeof normalizedValue === "number") {
      return Number(rawValue) === Number(normalizedValue);
    }
    return rawValue === normalizedValue;
  }

  function draftFieldPairs(rawDraft, normalized) {
    var raw = isPlainObject(rawDraft) ? rawDraft : {};
    var pairs = [];

    var rawMeta = isPlainObject(raw.meta) ? raw.meta : {};
    ["quoteNo", "issueDate", "validDays", "source", "projectName"].forEach(function (key) {
      pairs.push({ path: "meta." + key, raw: rawMeta[key], normalized: normalized.meta[key] });
    });

    var rawSender = isPlainObject(raw.sender) ? raw.sender : {};
    ["company", "rep", "contactPerson", "bizNo", "address", "phone", "email", "presetId"].forEach(function (key) {
      pairs.push({ path: "sender." + key, raw: rawSender[key], normalized: normalized.sender[key] });
    });

    var rawRecipient = isPlainObject(raw.recipient) ? raw.recipient : {};
    ["company", "person", "address", "email"].forEach(function (key) {
      pairs.push({ path: "recipient." + key, raw: rawRecipient[key], normalized: normalized.recipient[key] });
    });

    var rawItems = Array.isArray(raw.items) ? raw.items : [];
    if (rawItems.length !== normalized.items.length) {
      pairs.push({ path: "items.length", raw: rawItems.length, normalized: normalized.items.length });
    }
    normalized.items.forEach(function (item, index) {
      var rawItem = isPlainObject(rawItems[index]) ? rawItems[index] : {};
      ITEM_FIELDS.forEach(function (key) {
        pairs.push({ path: "items[" + index + "]." + key, raw: rawItem[key], normalized: item[key] });
      });
    });

    var rawTax = isPlainObject(raw.tax) ? raw.tax : {};
    pairs.push({ path: "tax.mode", raw: rawTax.mode, normalized: normalized.tax.mode });
    pairs.push({ path: "tax.rate", raw: rawTax.rate, normalized: normalized.tax.rate });
    pairs.push({ path: "memo", raw: raw.memo, normalized: normalized.memo });

    var rawGroups = Array.isArray(raw.detailGroups) ? raw.detailGroups : [];
    var normGroups = Array.isArray(normalized.detailGroups) ? normalized.detailGroups : [];
    if (rawGroups.length !== normGroups.length) {
      pairs.push({ path: "detailGroups.length", raw: rawGroups.length, normalized: normGroups.length });
    }
    normGroups.forEach(function (group, groupIndex) {
      var rawGroup = isPlainObject(rawGroups[groupIndex]) ? rawGroups[groupIndex] : {};
      ["id", "summaryItemId", "title"].forEach(function (key) {
        pairs.push({
          path: "detailGroups[" + groupIndex + "]." + key,
          raw: rawGroup[key],
          normalized: group[key]
        });
      });
      var rawGroupItems = Array.isArray(rawGroup.items) ? rawGroup.items : [];
      if (rawGroupItems.length !== group.items.length) {
        pairs.push({
          path: "detailGroups[" + groupIndex + "].items.length",
          raw: rawGroupItems.length,
          normalized: group.items.length
        });
      }
      group.items.forEach(function (item, itemIndex) {
        var rawItem = isPlainObject(rawGroupItems[itemIndex]) ? rawGroupItems[itemIndex] : {};
        DETAIL_ITEM_FIELDS.forEach(function (key) {
          pairs.push({
            path: "detailGroups[" + groupIndex + "].items[" + itemIndex + "]." + key,
            raw: rawItem[key],
            normalized: item[key]
          });
        });
      });
    });

    var rawPolicy = isPlainObject(raw.calculationPolicy) ? raw.calculationPolicy : null;
    var normPolicy = normalized.calculationPolicy || null;
    if (Boolean(rawPolicy) !== Boolean(normPolicy)) {
      pairs.push({ path: "calculationPolicy", raw: rawPolicy, normalized: normPolicy });
    } else if (rawPolicy && normPolicy) {
      var rawRounding = isPlainObject(rawPolicy.grandRounding) ? rawPolicy.grandRounding : {};
      var normRounding = isPlainObject(normPolicy.grandRounding) ? normPolicy.grandRounding : {};
      pairs.push({
        path: "calculationPolicy.grandRounding.mode",
        raw: rawRounding.mode,
        normalized: normRounding.mode
      });
      pairs.push({
        path: "calculationPolicy.grandRounding.unit",
        raw: rawRounding.unit,
        normalized: normRounding.unit
      });
    }

    return pairs;
  }

  /* 저장 전과 불러오기 후 모두에서 호출한다. */
  function assertLosslessDraft(rawDraft) {
    var normalized = Core.normalizeDraft(rawDraft);
    if (!normalized) return { lossless: false, lost: ["draft"], draft: null };
    var lost = [];
    draftFieldPairs(rawDraft, normalized).forEach(function (pair) {
      if (!sameField(pair.raw, pair.normalized)) lost.push(pair.path);
    });
    return { lossless: lost.length === 0, lost: lost, draft: normalized };
  }

  /* 편집 데이터 전체를 필드 단위로 재구성했을 때의 정규형(재시도 쌍 고정 근거). */
  function canonicalQuote(rawDraft) {
    var normalized = Core.normalizeDraft(rawDraft);
    if (!normalized) return null;
    var canonical = {};
    draftFieldPairs(normalized, normalized).forEach(function (pair) {
      canonical[pair.path] = pair.normalized === undefined ? null : pair.normalized;
    });
    return canonical;
  }

  /* 템플릿 권위에 해당하는 값만 지문에 넣는다. 표시용 label 은 제외한다. */
  function templateIdentity(template) {
    var ref = normalizeTemplateReference(template);
    if (!ref) return null;
    return { savedSkillId: ref.savedSkillId, fingerprint: ref.fingerprint || null };
  }

  function contentFingerprint(draft, template) {
    var canonical = canonicalQuote(draft);
    if (!canonical) return null;
    return fingerprintOf({ quote: canonical, template: templateIdentity(template) });
  }

  /* ── 파일명 규칙 ── */
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

  /* ── PDF 바이트 검증 ── */
  function validatePdfBytes(bytes) {
    var data = normalizeBytesLike(bytes);
    if (!data) return { ok: false, code: "pdf_missing" };
    if (data.length <= 0) return { ok: false, code: "pdf_missing" };
    if (data.length < MIN_PDF_BYTES) return { ok: false, code: "pdf_too_small" };
    if (data.length > MAX_PDF_BYTES) return { ok: false, code: "pdf_too_large" };
    for (var index = 0; index < PDF_MAGIC_BYTES.length; index += 1) {
      if (data[index] !== PDF_MAGIC_BYTES[index]) return { ok: false, code: "pdf_format_invalid" };
    }
    return { ok: true, byteLength: data.length };
  }

  /* ── 템플릿 참조 ── */
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

  /* ── 저장 패키지 ── */
  function createPackageId(opts) {
    var now = opts && opts.now ? opts.now : null;
    var stamp = String(now instanceof Date ? now.getTime() : Date.now());
    var random = "";
    if (opts && typeof opts.random === "function") {
      random = String(opts.random());
    } else if (typeof Math !== "undefined" && typeof Math.random === "function") {
      random = Math.random().toString(36).slice(2, 10);
    }
    return ("pkg-" + stamp + "-" + random).replace(/[^0-9a-zA-Z-]/g, "").slice(0, 64);
  }

  function buildPackage(options) {
    var opts = options || {};
    var guard = assertLosslessDraft(opts.draft);
    if (!guard.draft) return { ok: false, code: "invalid_draft" };
    if (!guard.lossless) return { ok: false, code: "draft_lossy_round_trip", lost: guard.lost };
    var draft = guard.draft;

    var packageId = boundedText(opts.packageId, 64) || createPackageId(opts);
    var savedAt = boundedText(opts.savedAt, 40) || null;
    var template = normalizeTemplateReference(opts.template);
    var baseName = buildBaseName(draft);

    var pkg = {
      kind: PACKAGE_KIND,
      contract: CONTRACT_ID,
      schemaVersion: CURRENT_SCHEMA_VERSION,
      packageId: packageId,
      createdAt: savedAt,
      contentFingerprint: contentFingerprint(draft, template),
      quote: draft,
      template: template,
      assets: {
        json: { role: "quote-json", mimeType: JSON_MIME, packageId: packageId },
        pdf: { role: "quote-pdf", mimeType: PDF_MIME, packageId: packageId }
      },
      manifest: {
        quoteNo: boundedText(draft.meta.quoteNo, 80),
        issueDate: boundedText(draft.meta.issueDate, 40),
        recipientCompany: boundedText(draft.recipient.company, MAX_MANIFEST_TEXT_CHARS),
        recipientPerson: boundedText(draft.recipient.person, MAX_MANIFEST_TEXT_CHARS),
        itemCount: draft.items.length,
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

  function serializePackage(pkg) {
    if (!isPlainObject(pkg)) return null;
    return JSON.stringify(pkg, null, 2);
  }

  /* ── 읽기 검증 ── */
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
    for (var index = 0; index < keys.length; index += 1) {
      var key = keys[index];
      if (ALLOWED_TOP_LEVEL_KEYS.indexOf(key) === -1) return { ok: false, code: "unsupported_package_field" };
      if (FORBIDDEN_IDENTITY_KEYS.indexOf(key) !== -1) {
        return { ok: false, code: "identity_authority_field_rejected" };
      }
    }

    /* 편집 데이터 무손실: 정규화가 편집 필드를 바꾸거나 버리면 거부한다. */
    var guard = assertLosslessDraft(raw.quote);
    if (!guard.draft) return { ok: false, code: "invalid_quote_draft" };
    if (!guard.lossless) return { ok: false, code: "quote_lossy_round_trip", lost: guard.lost };
    var draft = guard.draft;

    var template = normalizeTemplateReference(raw.template);
    if (raw.template !== undefined && raw.template !== null && !template) {
      return { ok: false, code: "invalid_template_reference" };
    }

    /* 내용 지문은 견적 본문과 템플릿 참조에 대한 무결성 근거다. */
    var expectedFingerprint = contentFingerprint(draft, template);
    if (typeof raw.contentFingerprint !== "string" || !raw.contentFingerprint) {
      return { ok: false, code: "content_fingerprint_missing" };
    }
    if (raw.contentFingerprint !== expectedFingerprint) {
      return { ok: false, code: "content_fingerprint_mismatch" };
    }

    var packageId = boundedText(raw.packageId, 64);
    var manifest = isPlainObject(raw.manifest) ? clone(raw.manifest) : {};

    var pkg = {
      kind: PACKAGE_KIND,
      contract: CONTRACT_ID,
      schemaVersion: CURRENT_SCHEMA_VERSION,
      packageId: packageId || null,
      createdAt: boundedText(raw.createdAt, 40),
      contentFingerprint: expectedFingerprint,
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
    if (!ref) return { status: "none", reason: "template_reference_missing", resolved: null };
    var list = Array.isArray(availableTemplates) ? availableTemplates : [];
    var match = null;
    for (var index = 0; index < list.length; index += 1) {
      var candidate = list[index];
      if (candidate && candidate.savedSkillId === ref.savedSkillId) { match = candidate; break; }
    }
    if (!match) return { status: "unresolved", reason: "saved_skill_unavailable", resolved: null };
    if (match.approved !== true || match.active === false) {
      return { status: "inactive", reason: "saved_skill_inactive", resolved: match };
    }
    if (!ref.fingerprint || !match.fingerprint || ref.fingerprint !== match.fingerprint) {
      return {
        status: "mismatch",
        reason: ref.fingerprint ? "template_fingerprint_mismatch" : "template_fingerprint_missing",
        resolved: match
      };
    }
    return { status: "resolved", reason: null, resolved: match };
  }

  var TEMPLATE_BLOCK_CODES = {
    none: "template_authority_unverified",
    unresolved: "saved_skill_unavailable",
    inactive: "saved_skill_inactive",
    mismatch: "template_fingerprint_mismatch"
  };

  /* ── 불러오기 → QuoteCore 재계산 ──
     requireApprovedTemplate(기본 true)이면 템플릿 권위가 확인된 경우에만 적용 가능하다. */
  function importPackage(pkg, options) {
    var opts = options || {};
    var normalized;
    if (isPlainObject(pkg) && pkg.kind === PACKAGE_KIND && pkg.contentFingerprint) {
      normalized = pkg;
    } else {
      var result = normalizePackage(pkg, {});
      if (!result.ok) return { ok: false, code: result.code, lost: result.lost };
      normalized = result.package;
    }

    var draft = Core.normalizeDraft(normalized.quote);
    if (!draft) return { ok: false, code: "invalid_quote_draft" };

    var totals = Core.computeDraftTotals(draft);
    if (!totals) return { ok: false, code: "recalculation_failed" };

    var template = resolveTemplateReference(normalized.template, opts.templates);
    var warnings = [];
    if (template.status !== "resolved") warnings.push(template.reason || "template_authority_unverified");

    if (opts.requireApprovedTemplate !== false && template.status !== "resolved") {
      return {
        ok: false,
        code: TEMPLATE_BLOCK_CODES[template.status] || "template_authority_unverified",
        template: template,
        warnings: warnings,
        /* 권위를 확인할 수 없으면 편집기에 적용할 draft 를 돌려주지 않는다. */
        draft: null,
        message: "이 견적이 사용한 승인된 견적서 양식을 이 계정에서 확인할 수 없습니다. 다른 양식으로 자동 대체하지 않았습니다."
      };
    }

    return {
      ok: true,
      draft: draft,
      totals: totals,
      template: template,
      warnings: warnings,
      totalsAuthority: "quote-core",
      recalculated: true,
      certifiedPdfReady: template.status === "resolved",
      packageId: normalized.packageId,
      contentFingerprint: normalized.contentFingerprint,
      schemaVersion: normalized.schemaVersion
    };
  }

  /* ── 부분 실패: 원래 쌍을 고정한다 ──
     packageId · 계획된 파일명 · createdAt · 내용 지문 · PDF 지문을 결과에 묶어
     재시도가 다른 내용이나 다른 이름으로 "완성" 을 만들지 못하게 한다. */
  function buildPairBinding(options) {
    var opts = options || {};
    return {
      packageId: opts.packageId || null,
      createdAt: opts.createdAt || null,
      baseName: opts.baseName || null,
      renamed: opts.renamed === true,
      jsonName: opts.jsonName || null,
      pdfName: opts.pdfName || null,
      draftFingerprint: opts.draftFingerprint || null,
      pdfFingerprint: opts.pdfFingerprint || null
    };
  }

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
      message = "견적 JSON은 저장했지만 PDF 저장에 실패했습니다. 같은 견적 내용으로 PDF만 다시 저장할 수 있습니다.";
    } else if (!jsonOk && pdfOk) {
      status = "partial_pdf";
      code = jsonResult && jsonResult.code ? jsonResult.code : "json_upload_failed";
      partial = true;
      missing = "json";
      message = "PDF는 저장했지만 견적 JSON 저장에 실패했습니다. 같은 견적 내용으로 JSON만 다시 저장할 수 있습니다.";
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
      retryable: partial === true && Boolean(opts.pair && opts.pair.draftFingerprint),
      recovery: partial ? { action: "retry_missing", target: missing } : null,
      message: message,
      errorText: errorText,
      packageId: opts.packageId || null,
      pair: opts.pair ? clone(opts.pair) : null,
      json: jsonOk ? { id: jsonResult.id, name: jsonResult.name, mimeType: JSON_MIME } : null,
      pdf: pdfOk ? { id: pdfResult.id, name: pdfResult.name, mimeType: PDF_MIME } : null
    };
  }

  /* 재시도 전에 원래 쌍이 그대로인지 확인한다. 하나라도 달라지면 새 쌍으로 저장해야 한다. */
  function pairRetryGuard(outcome, current) {
    var opts = current || {};
    if (!outcome || !outcome.pair) return { ok: false, code: "pending_pair_missing" };
    if (outcome.partial !== true || (outcome.missing !== "json" && outcome.missing !== "pdf")) {
      return { ok: false, code: "pending_pair_incomplete" };
    }
    var pair = outcome.pair;
    if (!pair.draftFingerprint) return { ok: false, code: "pending_pair_missing" };

    var currentFingerprint = contentFingerprint(opts.draft, opts.template);
    if (!currentFingerprint || currentFingerprint !== pair.draftFingerprint) {
      return {
        ok: false,
        code: "pending_pair_stale",
        message: "저장 도중 견적 내용이 바뀌었습니다. 이어서 저장하지 않고 새 견적서로 저장해야 합니다."
      };
    }
    if (outcome.missing === "pdf") {
      var currentPdf = pdfFingerprint(opts.pdfBytes);
      if (!currentPdf || currentPdf !== pair.pdfFingerprint) {
        return {
          ok: false,
          code: "pending_pdf_changed",
          message: "저장하려던 PDF와 지금 만들어진 PDF가 다릅니다. 새 견적서로 저장해 주세요."
        };
      }
    }
    return { ok: true, pair: clone(pair), target: outcome.missing };
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
    TEMPLATE_BLOCK_CODES: TEMPLATE_BLOCK_CODES,
    ITEM_FIELDS: ITEM_FIELDS.slice(),
    DETAIL_ITEM_FIELDS: DETAIL_ITEM_FIELDS.slice(),
    isSupportedSchemaVersion: isSupportedSchemaVersion,
    stableStringify: stableStringify,
    fingerprintOf: fingerprintOf,
    pdfFingerprint: pdfFingerprint,
    contentFingerprint: contentFingerprint,
    templateIdentity: templateIdentity,
    canonicalQuote: canonicalQuote,
    draftFieldPairs: draftFieldPairs,
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
    buildPairBinding: buildPairBinding,
    buildUploadOutcome: buildUploadOutcome,
    pairRetryGuard: pairRetryGuard
  });
});
