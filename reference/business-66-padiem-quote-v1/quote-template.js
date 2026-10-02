/* B66 · Quote Beta — quote-template.js
   견적서 템플릿(QuoteTemplateProfile) 계약: 표현과 배치만 소유한다.
   금액·세금·유효일 계산의 authority 는 quote-core.js 이며, 이 파일은 아무것도 계산하지 않는다.
   (DOM 없음 · 브라우저/Node 양쪽에서 실행) */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.QuoteTemplate = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var TEMPLATE_SCHEMA_VERSION = 1;
  var BUILTIN_TEMPLATE_ID = "builtin-default";
  var BUILTIN_TEMPLATE_NAME = "기본 견적서";

  var MAX_TEMPLATE_ID_CHARS = 64;
  var MAX_TEMPLATE_NAME_CHARS = 80;
  var MAX_TEMPLATE_STRING_CHARS = 512;
  var MAX_TEMPLATE_COLLECTION_ITEMS = 64;
  var MAX_TEMPLATE_DEPTH = 8;
  var MAX_TEMPLATE_NODES = 512;
  var MAX_TEMPLATE_CONTENT_BYTES = 64 * 1024;

  /* 승인 증거(#3181 semantics). candidate 는 승인 없이 활성 profile 이 될 수 없다. */
  var APPROVAL_SCHEMA_VERSION = 1;
  var MAX_APPROVER_REF_CHARS = 128;

  /* #3402: logo/stamp 는 raw bytes/URL 이 아니라 account-bound private asset id 만 보존한다. */
  var SLOT_SUPPORT = "private_asset_v1";

  var ALLOWED_SECTIONS = ["title", "meta", "parties", "items", "totals", "memo", "mark"];
  var ALLOWED_COLUMN_KEYS = ["sequence", "name", "specification", "unit", "qty", "unitPrice", "amount", "rowNote"];
  var REQUIRED_COLUMN_KEYS = ["name", "qty", "unitPrice", "amount"];
  var ALLOWED_ALIGNMENTS = ["left", "right", "center"];
  var ALLOWED_JUSTIFY = ["flex-start", "center", "flex-end", "space-between", "space-around"];
  var ALLOWED_PAGE_SIZES = ["A4", "A5", "Legal", "Letter"];
  var ALLOWED_ORIENTATIONS = ["portrait", "landscape"];
  var ALLOWED_TAX_MODES = ["EXCLUSIVE", "INCLUSIVE", "EXEMPT"];

  var ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/;
  var HEX_COLOR_PATTERN = /^#[0-9a-fA-F]{3,8}$/;
  var CSS_TOKEN_PATTERN = /^[0-9A-Za-z#.,%()\- ]{1,64}$/;
  var MEASURE_PATTERN = /^[0-9A-Za-z.%]{1,16}$/;
  var PAGE_MARGIN_PATTERN = /^\d{1,2}(?:\.\d{1,2})?(?:mm|cm|in)$/;
  var SLOT_REF_PATTERN = /^b66asset_[0-9a-f]{32}$/;
  var APPROVER_REF_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:@/-]{2,127}$/;
  var ISO_UTC_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/;
  var SHA256_HEX_PATTERN = /^[0-9a-f]{64}$/;

  /* 계산 authority 침범 / 자격증명 / 원본 파일 바이트를 템플릿에 저장하는 키.
     정규화는 허용 키 화이트리스트로 동작하므로 이런 키는 애초에 보존되지 않지만,
     저장 시점에는 명시적으로 거부해 조용한 손실 대신 안전한 실패를 만든다. */
  var FORBIDDEN_TEMPLATE_KEYS = [
    /* authority / credential / routing surfaces */
    "authority", "authorization", "permission", "permissions",
    "permissiongrant", "permissiongrants", "toolgrant", "toolgrants",
    "tool", "tools", "allowedtoolids", "connectorgrant", "connectorgrants",
    "connector", "connectors", "connectorrequirementids", "entitlement", "entitlements", "entitlementref",
    "accesstoken", "refreshtoken", "authtoken", "bearertoken", "apikey",
    "credential", "credentials", "secret", "secrets", "password",
    "privatekey", "clientsecret", "provider", "providerid",
    "model", "modelid", "modelfamily", "modelpolicyref",
    /* raw uploaded file bytes */
    "rawbytes", "filebytes", "uploadedbytes", "arraybuffer", "dataurl",
    "blob", "bytes", "base64", "file", "files",
    /* trusted totals (QuoteCore 만이 계산 authority) */
    "subtotal", "supply", "vat", "grand", "total", "grandtotal",
    "subtotalamount", "supplyamount", "vatamount", "amounttotal",
    "trustedtotals", "computedtotals"
  ];

  var FORBIDDEN_KEY_LOOKUP = (function () {
    var lookup = Object.create(null);
    FORBIDDEN_TEMPLATE_KEYS.forEach(function (key) { lookup[key] = true; });
    return lookup;
  })();

  /* ── 내장 기본 프로필 = 현재 B66 견적서 화면/인쇄 디자인 ── */

  var BUILTIN_TEMPLATE_CONTENT = {
    layoutVersion: 1,
    page: { size: "A4", margin: "10mm", orientation: "portrait" },
    sections: ["title", "meta", "parties", "items", "totals", "memo", "mark"],
    title: { text: "견 적 서" },
    meta: {
      quoteNoPrefix: "견적번호  ",
      issueDatePrefix: "견적일  ",
      validityPrefix: "유효기간  ",
      validUntilPrefix: "유효일  ",
      taxPrefix: "세금  ",
      validityUnit: "일",
      taxReviewText: "세금  확인 필요"
    },
    sender: {
      heading: "공급자",
      repPrefix: "대표자  ",
      bizNoPrefix: "사업자번호  ",
      contactSeparator: " · "
    },
    recipient: { heading: "공급받는 자", personPrefix: "담당자  " },
    items: {
      columns: [
        { key: "name", label: "품목", width: "42%", align: "left" },
        { key: "qty", label: "수량", width: "", align: "right" },
        { key: "unitPrice", label: "단가", width: "", align: "right" },
        { key: "amount", label: "금액", width: "", align: "right" }
      ],
      emptyNameText: "품목을 입력하세요"
    },
    totals: {
      supplyLabel: "공급가액",
      grandLabel: "합계",
      vatLabels: {
        EXCLUSIVE: "부가세",
        INCLUSIVE: "부가세 (포함가 분리)",
        EXEMPT: "부가세 (면세)"
      },
      provisional: {
        subtotalLabel: "품목 합계(세금 확인 전)",
        vatLabel: "부가세",
        vatText: "확인 필요",
        grandLabel: "최종 합계",
        grandText: "확정 전"
      }
    },
    memo: { emptyText: "비고 없음" },
    mark: { text: "견적서 베타" },
    slots: { logo: "", stamp: "" },
    style: {
      accent: "#17202a",
      titleRule: "2px solid #111827",
      tableHeaderRule: "1px solid #111827",
      tableRowRule: "1px solid #e4e7ec",
      partyRule: "1px solid #cfd5dd",
      memoRule: "1px solid #d0d5dd",
      headerAlignment: "space-between",
      metaAlignment: "right",
      numericAlignment: "right",
      textAlignment: "left",
      totalsWidth: "310px"
    },
    fallbackText: "-"
  };

  /* ── 공통 유틸 ── */

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function cloneJson(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function boundString(value, fallback) {
    if (typeof value !== "string") return fallback;
    return value.slice(0, MAX_TEMPLATE_STRING_CHARS);
  }

  function cleanToken(value, fallback) {
    if (typeof value !== "string" || !CSS_TOKEN_PATTERN.test(value)) return fallback;
    return value;
  }

  function cleanMeasure(value, fallback) {
    if (typeof value !== "string" || !MEASURE_PATTERN.test(value)) return fallback;
    return value;
  }

  function cleanAlignment(value, fallback) {
    return ALLOWED_ALIGNMENTS.indexOf(value) === -1 ? fallback : value;
  }

  function cleanEnum(value, allowed, fallback) {
    return allowed.indexOf(value) === -1 ? fallback : value;
  }

  function cleanJustify(value, fallback) {
    return ALLOWED_JUSTIFY.indexOf(value) === -1 ? fallback : value;
  }

  function cleanPageMargin(value, fallback) {
    if (typeof value !== "string" || !PAGE_MARGIN_PATTERN.test(value)) return fallback;
    return value;
  }

  function cleanSlotRef(value, fallback) {
    if (typeof value !== "string") return fallback;
    var trimmed = value.trim();
    if (!trimmed) return fallback;
    if (!SLOT_REF_PATTERN.test(trimmed)) return fallback;
    return trimmed.slice(0, MAX_TEMPLATE_STRING_CHARS);
  }

  function normalizeTemplateId(value) {
    if (typeof value !== "string" || !ID_PATTERN.test(value)) return null;
    return value.slice(0, MAX_TEMPLATE_ID_CHARS);
  }

  function normalizeTemplateName(value, fallback) {
    if (typeof value !== "string") return fallback;
    var trimmed = value.trim();
    if (!trimmed) return fallback;
    return trimmed.slice(0, MAX_TEMPLATE_NAME_CHARS);
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  /* ── 금지 키 탐지 (authority·자격증명·원본 바이트·신뢰 합계) ── */

  function normalizeKeyName(key) {
    return String(key).toLowerCase().replace(/[_\-\s]/g, "");
  }

  function findForbiddenKeys(value) {
    var found = [];
    var visited = 0;
    (function walk(node, path, depth) {
      if (visited > MAX_TEMPLATE_NODES || depth > MAX_TEMPLATE_DEPTH) return;
      visited += 1;
      if (Array.isArray(node)) {
        node.slice(0, MAX_TEMPLATE_COLLECTION_ITEMS).forEach(function (item, index) {
          walk(item, path + "[" + index + "]", depth + 1);
        });
        return;
      }
      if (!isPlainObject(node)) return;
      Object.keys(node).forEach(function (key) {
        var keyPath = path ? path + "." + key : key;
        if (FORBIDDEN_KEY_LOOKUP[normalizeKeyName(key)]) found.push(keyPath);
        walk(node[key], keyPath, depth + 1);
      });
    })(value, "", 0);
    return found;
  }

  /* ── 결정적 직렬화 + SHA-256 (의존성 없이 브라우저/Node 동일 결과) ── */

  function canonicalJson(value) {
    var nodes = 0;
    function serialize(node, depth) {
      nodes += 1;
      if (nodes > MAX_TEMPLATE_NODES) throw new Error("template_too_large");
      if (depth > MAX_TEMPLATE_DEPTH) throw new Error("template_too_deep");
      if (node === null) return "null";
      if (typeof node === "string") return JSON.stringify(node);
      if (typeof node === "number") {
        if (!Number.isFinite(node)) throw new Error("template_number_not_finite");
        return JSON.stringify(node);
      }
      if (typeof node === "boolean") return node ? "true" : "false";
      if (Array.isArray(node)) {
        if (node.length > MAX_TEMPLATE_COLLECTION_ITEMS) throw new Error("template_collection_too_long");
        return "[" + node.map(function (item) { return serialize(item, depth + 1); }).join(",") + "]";
      }
      if (isPlainObject(node)) {
        var keys = Object.keys(node).sort();
        if (keys.length > MAX_TEMPLATE_COLLECTION_ITEMS) throw new Error("template_collection_too_long");
        return "{" + keys.map(function (key) {
          return JSON.stringify(key) + ":" + serialize(node[key], depth + 1);
        }).join(",") + "}";
      }
      throw new Error("template_value_not_serializable");
    }
    return serialize(value, 0);
  }

  function utf8Bytes(text) {
    var bytes = [];
    for (var i = 0; i < text.length; i += 1) {
      var code = text.charCodeAt(i);
      var paired = false;
      if (code >= 0xd800 && code <= 0xdbff && i + 1 < text.length) {
        var next = text.charCodeAt(i + 1);
        if (next >= 0xdc00 && next <= 0xdfff) {
          code = 0x10000 + ((code - 0xd800) << 10) + (next - 0xdc00);
          paired = true;
          i += 1;
        }
      }
      /* lone surrogate 는 표준 UTF-8 규칙대로 U+FFFD 로 대체해
         Node crypto / 브라우저 TextEncoder 와 같은 바이트를 만든다. */
      if (!paired && code >= 0xd800 && code <= 0xdfff) code = 0xfffd;
      if (code < 0x80) {
        bytes.push(code);
      } else if (code < 0x800) {
        bytes.push(0xc0 | (code >> 6), 0x80 | (code & 0x3f));
      } else if (code < 0x10000) {
        bytes.push(0xe0 | (code >> 12), 0x80 | ((code >> 6) & 0x3f), 0x80 | (code & 0x3f));
      } else {
        bytes.push(
          0xf0 | (code >> 18),
          0x80 | ((code >> 12) & 0x3f),
          0x80 | ((code >> 6) & 0x3f),
          0x80 | (code & 0x3f)
        );
      }
    }
    return bytes;
  }

  var SHA256_K = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
  ];

  function rotr(value, bits) {
    return ((value >>> bits) | (value << (32 - bits))) >>> 0;
  }

  function sha256Hex(text) {
    var bytes = utf8Bytes(String(text));
    var bitLength = bytes.length * 8;
    bytes.push(0x80);
    while (bytes.length % 64 !== 56) bytes.push(0);
    var high = Math.floor(bitLength / 0x100000000);
    var low = bitLength >>> 0;
    bytes.push((high >>> 24) & 0xff, (high >>> 16) & 0xff, (high >>> 8) & 0xff, high & 0xff);
    bytes.push((low >>> 24) & 0xff, (low >>> 16) & 0xff, (low >>> 8) & 0xff, low & 0xff);

    var h0 = 0x6a09e667, h1 = 0xbb67ae85, h2 = 0x3c6ef372, h3 = 0xa54ff53a;
    var h4 = 0x510e527f, h5 = 0x9b05688c, h6 = 0x1f83d9ab, h7 = 0x5be0cd19;
    var w = new Array(64);

    for (var offset = 0; offset < bytes.length; offset += 64) {
      for (var i = 0; i < 16; i += 1) {
        var j = offset + i * 4;
        w[i] = ((bytes[j] << 24) | (bytes[j + 1] << 16) | (bytes[j + 2] << 8) | bytes[j + 3]) >>> 0;
      }
      for (var t = 16; t < 64; t += 1) {
        var s0 = (rotr(w[t - 15], 7) ^ rotr(w[t - 15], 18) ^ (w[t - 15] >>> 3)) >>> 0;
        var s1 = (rotr(w[t - 2], 17) ^ rotr(w[t - 2], 19) ^ (w[t - 2] >>> 10)) >>> 0;
        w[t] = (w[t - 16] + s0 + w[t - 7] + s1) >>> 0;
      }

      var a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, h = h7;

      for (var step = 0; step < 64; step += 1) {
        var bigS1 = (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) >>> 0;
        var ch = ((e & f) ^ (~e & g)) >>> 0;
        var temp1 = (h + bigS1 + ch + SHA256_K[step] + w[step]) >>> 0;
        var bigS0 = (rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) >>> 0;
        var maj = ((a & b) ^ (a & c) ^ (b & c)) >>> 0;
        var temp2 = (bigS0 + maj) >>> 0;
        h = g; g = f; f = e;
        e = (d + temp1) >>> 0;
        d = c; c = b; b = a;
        a = (temp1 + temp2) >>> 0;
      }

      h0 = (h0 + a) >>> 0; h1 = (h1 + b) >>> 0; h2 = (h2 + c) >>> 0; h3 = (h3 + d) >>> 0;
      h4 = (h4 + e) >>> 0; h5 = (h5 + f) >>> 0; h6 = (h6 + g) >>> 0; h7 = (h7 + h) >>> 0;
    }

    return [h0, h1, h2, h3, h4, h5, h6, h7].map(function (word) {
      return ("00000000" + word.toString(16)).slice(-8);
    }).join("");
  }

  /* ── content 정규화: 화이트리스트 기반. 모르는 키는 버리고, 구조가 깨지면 실패 ── */

  function normalizeColumns(raw) {
    if (!Array.isArray(raw) || raw.length < REQUIRED_COLUMN_KEYS.length || raw.length > ALLOWED_COLUMN_KEYS.length) return null;
    var seen = Object.create(null);
    var columns = [];
    for (var i = 0; i < raw.length; i += 1) {
      var entry = raw[i];
      if (!isPlainObject(entry)) return null;
      var key = entry.key;
      if (ALLOWED_COLUMN_KEYS.indexOf(key) === -1 || seen[key]) return null;
      seen[key] = true;
      columns.push({
        key: key,
        label: boundString(entry.label, key),
        width: cleanMeasure(entry.width, ""),
        align: cleanAlignment(entry.align, "left")
      });
    }
    for (var r = 0; r < REQUIRED_COLUMN_KEYS.length; r += 1) {
      if (!seen[REQUIRED_COLUMN_KEYS[r]]) return null;
    }
    return columns;
  }

  function normalizeSections(raw) {
    if (!Array.isArray(raw) || raw.length === 0) return null;
    var seen = Object.create(null);
    var sections = [];
    for (var i = 0; i < raw.length; i += 1) {
      var name = raw[i];
      if (ALLOWED_SECTIONS.indexOf(name) === -1 || seen[name]) return null;
      seen[name] = true;
      sections.push(name);
    }
    return sections;
  }

  function normalizeTaxLabels(raw, fallback) {
    var source = isPlainObject(raw) ? raw : {};
    var labels = {};
    ALLOWED_TAX_MODES.forEach(function (mode) {
      labels[mode] = boundString(source[mode], fallback[mode]);
    });
    return labels;
  }

  function normalizeStyle(raw) {
    var fallback = BUILTIN_TEMPLATE_CONTENT.style;
    var source = isPlainObject(raw) ? raw : {};
    return {
      accent: typeof source.accent === "string" && HEX_COLOR_PATTERN.test(source.accent)
        ? source.accent
        : fallback.accent,
      titleRule: cleanToken(source.titleRule, fallback.titleRule),
      tableHeaderRule: cleanToken(source.tableHeaderRule, fallback.tableHeaderRule),
      tableRowRule: cleanToken(source.tableRowRule, fallback.tableRowRule),
      partyRule: cleanToken(source.partyRule, fallback.partyRule),
      memoRule: cleanToken(source.memoRule, fallback.memoRule),
      headerAlignment: cleanJustify(source.headerAlignment, fallback.headerAlignment),
      metaAlignment: cleanAlignment(source.metaAlignment, fallback.metaAlignment),
      numericAlignment: cleanAlignment(source.numericAlignment, fallback.numericAlignment),
      textAlignment: cleanAlignment(source.textAlignment, fallback.textAlignment),
      totalsWidth: cleanMeasure(source.totalsWidth, fallback.totalsWidth)
    };
  }

  function normalizeTemplateContent(raw) {
    var defaults = BUILTIN_TEMPLATE_CONTENT;
    if (!isPlainObject(raw)) return null;

    var sections = normalizeSections(raw.sections);
    if (!sections) return null;
    var columns = normalizeColumns(raw.items && raw.items.columns);
    if (!columns) return null;

    var page = isPlainObject(raw.page) ? raw.page : {};
    var meta = isPlainObject(raw.meta) ? raw.meta : {};
    var sender = isPlainObject(raw.sender) ? raw.sender : {};
    var recipient = isPlainObject(raw.recipient) ? raw.recipient : {};
    var totals = isPlainObject(raw.totals) ? raw.totals : {};
    var provisional = isPlainObject(totals.provisional) ? totals.provisional : {};
    var title = isPlainObject(raw.title) ? raw.title : {};
    var memo = isPlainObject(raw.memo) ? raw.memo : {};
    var mark = isPlainObject(raw.mark) ? raw.mark : {};
    var slots = isPlainObject(raw.slots) ? raw.slots : {};

    var content = {
      layoutVersion: Number.isInteger(raw.layoutVersion) && raw.layoutVersion > 0
        ? raw.layoutVersion
        : defaults.layoutVersion,
      page: {
        size: cleanEnum(page.size, ALLOWED_PAGE_SIZES, defaults.page.size),
        margin: cleanPageMargin(page.margin, defaults.page.margin),
        orientation: cleanEnum(page.orientation, ALLOWED_ORIENTATIONS, defaults.page.orientation)
      },
      sections: sections,
      title: { text: boundString(title.text, defaults.title.text) },
      meta: {
        quoteNoPrefix: boundString(meta.quoteNoPrefix, defaults.meta.quoteNoPrefix),
        issueDatePrefix: boundString(meta.issueDatePrefix, defaults.meta.issueDatePrefix),
        validityPrefix: boundString(meta.validityPrefix, defaults.meta.validityPrefix),
        validUntilPrefix: boundString(meta.validUntilPrefix, defaults.meta.validUntilPrefix),
        taxPrefix: boundString(meta.taxPrefix, defaults.meta.taxPrefix),
        validityUnit: boundString(meta.validityUnit, defaults.meta.validityUnit),
        taxReviewText: boundString(meta.taxReviewText, defaults.meta.taxReviewText)
      },
      sender: {
        heading: boundString(sender.heading, defaults.sender.heading),
        repPrefix: boundString(sender.repPrefix, defaults.sender.repPrefix),
        bizNoPrefix: boundString(sender.bizNoPrefix, defaults.sender.bizNoPrefix),
        contactSeparator: boundString(sender.contactSeparator, defaults.sender.contactSeparator)
      },
      recipient: {
        heading: boundString(recipient.heading, defaults.recipient.heading),
        personPrefix: boundString(recipient.personPrefix, defaults.recipient.personPrefix)
      },
      items: {
        columns: columns,
        emptyNameText: boundString(
          raw.items && raw.items.emptyNameText,
          defaults.items.emptyNameText
        )
      },
      totals: {
        supplyLabel: boundString(totals.supplyLabel, defaults.totals.supplyLabel),
        grandLabel: boundString(totals.grandLabel, defaults.totals.grandLabel),
        vatLabels: normalizeTaxLabels(totals.vatLabels, defaults.totals.vatLabels),
        provisional: {
          subtotalLabel: boundString(provisional.subtotalLabel, defaults.totals.provisional.subtotalLabel),
          vatLabel: boundString(provisional.vatLabel, defaults.totals.provisional.vatLabel),
          vatText: boundString(provisional.vatText, defaults.totals.provisional.vatText),
          grandLabel: boundString(provisional.grandLabel, defaults.totals.provisional.grandLabel),
          grandText: boundString(provisional.grandText, defaults.totals.provisional.grandText)
        }
      },
      memo: { emptyText: boundString(memo.emptyText, defaults.memo.emptyText) },
      mark: { text: boundString(mark.text, defaults.mark.text) },
      slots: {
        logo: cleanSlotRef(slots.logo, defaults.slots.logo),
        stamp: cleanSlotRef(slots.stamp, defaults.slots.stamp)
      },
      style: normalizeStyle(raw.style),
      fallbackText: boundString(raw.fallbackText, defaults.fallbackText)
    };

    /* #3411 additive fidelity primitives. They are emitted only when explicitly
       declared so canonical legacy/builtin content keeps its byte/fingerprint identity. */
    if (Object.prototype.hasOwnProperty.call(meta, "projectNamePrefix")) {
      content.meta.projectNamePrefix = boundString(meta.projectNamePrefix, "건명  ");
    }
    if (Object.prototype.hasOwnProperty.call(totals, "showWrittenGrand")) {
      content.totals.showWrittenGrand = totals.showWrittenGrand === true;
    }
    if (Object.prototype.hasOwnProperty.call(totals, "writtenGrandPrefix")) {
      content.totals.writtenGrandPrefix = boundString(totals.writtenGrandPrefix, "일금 ");
    }

    var serialized;
    try {
      serialized = canonicalJson(content);
    } catch (err) {
      return null;
    }
    if (utf8Bytes(serialized).length > MAX_TEMPLATE_CONTENT_BYTES) return null;
    return content;
  }

  /* ── 지문(fingerprint): 내용만 반영한다. id/name 변경은 지문을 바꾸지 않는다 ── */

  function templateFingerprint(input) {
    var content = isPlainObject(input) && "content" in input ? input.content : input;
    if (!isPlainObject(content)) return null;
    try {
      return sha256Hex(canonicalJson(content));
    } catch (err) {
      return null;
    }
  }

  /* trusted built-in 은 (1) canonical BUILTIN_TEMPLATE_ID 와
     (2) canonical built-in content/fingerprint 를 모두 만족할 때만 성립한다.
     builtin:true 플래그만 붙인 외부/사용자 profile 은 승인을 우회할 수 없다. */
  var BUILTIN_TEMPLATE_FINGERPRINT = templateFingerprint(BUILTIN_TEMPLATE_CONTENT);
  var BUILTIN_TEMPLATE_CANONICAL = canonicalJson(BUILTIN_TEMPLATE_CONTENT);

  function isCanonicalBuiltInContent(content) {
    if (!isPlainObject(content)) return false;
    try {
      return canonicalJson(content) === BUILTIN_TEMPLATE_CANONICAL;
    } catch (err) {
      return false;
    }
  }

  function isCanonicalBuiltIn(candidate) {
    if (!isPlainObject(candidate)) return false;
    if (candidate.id !== BUILTIN_TEMPLATE_ID) return false;
    if (candidate.builtin !== true) return false;
    if (!isCanonicalBuiltInContent(candidate.content)) return false;
    return templateFingerprint(candidate.content) === BUILTIN_TEMPLATE_FINGERPRINT;
  }

  /* ── 승인 증거: 지문이 일치하는 explicit approval 만 유효하다 ── */

  function normalizeApproval(raw, contentFingerprint) {
    if (!isPlainObject(raw)) return null;
    if (raw.schemaVersion !== APPROVAL_SCHEMA_VERSION) return null;
    if (raw.status !== "approved") return null;
    if (typeof contentFingerprint !== "string" || !SHA256_HEX_PATTERN.test(contentFingerprint)) return null;
    /* 승인 이후 내용이 바뀌면 여기서 무효가 된다(조용한 보존 금지). */
    if (raw.contentFingerprint !== contentFingerprint) return null;

    var approvedBy = typeof raw.approvedBy === "string" ? raw.approvedBy.trim() : "";
    if (!APPROVER_REF_PATTERN.test(approvedBy)) return null;

    var approvedAt = typeof raw.approvedAt === "string" ? raw.approvedAt.trim() : "";
    if (!ISO_UTC_PATTERN.test(approvedAt)) return null;

    var approvalRef = typeof raw.approvalRef === "string" ? raw.approvalRef.trim() : "";
    if (approvalRef && !APPROVER_REF_PATTERN.test(approvalRef)) return null;

    return {
      schemaVersion: APPROVAL_SCHEMA_VERSION,
      status: "approved",
      contentFingerprint: contentFingerprint,
      approvedBy: approvedBy.slice(0, MAX_APPROVER_REF_CHARS),
      approvedAt: approvedAt,
      approvalRef: approvalRef.slice(0, MAX_APPROVER_REF_CHARS)
    };
  }

  function approvalIsValid(approval, contentFingerprint) {
    return normalizeApproval(approval, contentFingerprint) !== null;
  }

  /* 내장 기본은 별도의 trusted built-in 예외다 — 코드와 테스트에 명시한다.
     id 만이나 builtin 플래그 만으로는 신뢰하지 않는다(canonical 일치까지 요구). */
  function isBuiltInException(profile) {
    return isCanonicalBuiltIn(profile);
  }

  function isApprovedProfile(profile) {
    if (!profile) return false;
    if (isBuiltInException(profile)) return true;
    return approvalIsValid(profile.approval, profile.fingerprint);
  }

  function buildProfile(source) {
    var content = cloneJson(source.content);
    var fingerprint = templateFingerprint(content);
    /* builtin 플래그는 주장일 뿐이다. canonical id + canonical content 일치까지 확인한다. */
    var builtin = isCanonicalBuiltIn({ id: source.id, builtin: source.builtin, content: content });
    var approval = builtin ? null : normalizeApproval(source.approval, fingerprint);
    return {
      schemaVersion: TEMPLATE_SCHEMA_VERSION,
      id: source.id,
      name: source.name,
      builtin: builtin,
      isDefault: source.isDefault === true,
      approved: builtin || approval !== null,
      approvalBasis: builtin ? "trusted_builtin" : (approval ? "explicit_approval" : "unapproved"),
      approval: approval,
      createdAt: typeof source.createdAt === "string" ? source.createdAt : "",
      updatedAt: typeof source.updatedAt === "string" ? source.updatedAt : "",
      fingerprint: fingerprint,
      content: content
    };
  }

  function builtInTemplate() {
    return buildProfile({
      id: BUILTIN_TEMPLATE_ID,
      name: BUILTIN_TEMPLATE_NAME,
      builtin: true,
      isDefault: true,
      createdAt: "",
      updatedAt: "",
      content: BUILTIN_TEMPLATE_CONTENT
    });
  }

  /* 손상/구버전/금지 키/지문 불일치 → null (호출측이 내장 기본으로 fallback) */
  function normalizeTemplate(raw) {
    if (!isPlainObject(raw)) return null;
    if (raw.schemaVersion !== TEMPLATE_SCHEMA_VERSION) return null;
    if (findForbiddenKeys(raw).length > 0) return null;

    var id = normalizeTemplateId(raw.id);
    if (!id) return null;

    var content = normalizeTemplateContent(raw.content);
    if (!content) return null;

    var computed = templateFingerprint(content);
    if (typeof raw.fingerprint === "string" && raw.fingerprint !== computed) return null;

    return buildProfile({
      id: id,
      name: normalizeTemplateName(raw.name, id),
      builtin: raw.builtin === true,
      isDefault: raw.isDefault === true,
      approval: raw.approval,
      createdAt: typeof raw.createdAt === "string" ? raw.createdAt.slice(0, 40) : "",
      updatedAt: typeof raw.updatedAt === "string" ? raw.updatedAt.slice(0, 40) : "",
      content: content
    });
  }

  function isBuiltInTemplate(value) {
    return Boolean(value) && value.id === BUILTIN_TEMPLATE_ID;
  }

  function serializeTemplate(profile) {
    return {
      schemaVersion: TEMPLATE_SCHEMA_VERSION,
      id: profile.id,
      name: profile.name,
      builtin: profile.builtin === true,
      isDefault: profile.isDefault === true,
      approval: profile.approval ? cloneJson(profile.approval) : null,
      createdAt: profile.createdAt,
      updatedAt: profile.updatedAt,
      fingerprint: profile.fingerprint,
      content: profile.content
    };
  }

  return {
    TEMPLATE_SCHEMA_VERSION: TEMPLATE_SCHEMA_VERSION,
    BUILTIN_TEMPLATE_ID: BUILTIN_TEMPLATE_ID,
    BUILTIN_TEMPLATE_NAME: BUILTIN_TEMPLATE_NAME,
    MAX_TEMPLATE_NAME_CHARS: MAX_TEMPLATE_NAME_CHARS,
    MAX_TEMPLATE_STRING_CHARS: MAX_TEMPLATE_STRING_CHARS,
    MAX_TEMPLATE_COLLECTION_ITEMS: MAX_TEMPLATE_COLLECTION_ITEMS,
    MAX_TEMPLATE_DEPTH: MAX_TEMPLATE_DEPTH,
    MAX_TEMPLATE_NODES: MAX_TEMPLATE_NODES,
    MAX_TEMPLATE_CONTENT_BYTES: MAX_TEMPLATE_CONTENT_BYTES,
    ALLOWED_SECTIONS: ALLOWED_SECTIONS,
    ALLOWED_COLUMN_KEYS: ALLOWED_COLUMN_KEYS,
    ALLOWED_ALIGNMENTS: ALLOWED_ALIGNMENTS,
    ALLOWED_TAX_MODES: ALLOWED_TAX_MODES,
    ALLOWED_JUSTIFY: ALLOWED_JUSTIFY,
    ALLOWED_PAGE_SIZES: ALLOWED_PAGE_SIZES,
    ALLOWED_ORIENTATIONS: ALLOWED_ORIENTATIONS,
    APPROVAL_SCHEMA_VERSION: APPROVAL_SCHEMA_VERSION,
    MAX_APPROVER_REF_CHARS: MAX_APPROVER_REF_CHARS,
    SLOT_SUPPORT: SLOT_SUPPORT,
    BUILTIN_TEMPLATE_FINGERPRINT: BUILTIN_TEMPLATE_FINGERPRINT,
    isCanonicalBuiltIn: isCanonicalBuiltIn,
    isCanonicalBuiltInContent: isCanonicalBuiltInContent,
    normalizeApproval: normalizeApproval,
    approvalIsValid: approvalIsValid,
    isBuiltInException: isBuiltInException,
    isApprovedProfile: isApprovedProfile,
    FORBIDDEN_TEMPLATE_KEYS: FORBIDDEN_TEMPLATE_KEYS,
    findForbiddenKeys: findForbiddenKeys,
    canonicalJson: canonicalJson,
    sha256Hex: sha256Hex,
    escapeHtml: escapeHtml,
    templateFingerprint: templateFingerprint,
    normalizeTemplateContent: normalizeTemplateContent,
    normalizeTemplate: normalizeTemplate,
    normalizeTemplateId: normalizeTemplateId,
    normalizeTemplateName: normalizeTemplateName,
    buildProfile: buildProfile,
    builtInTemplate: builtInTemplate,
    isBuiltInTemplate: isBuiltInTemplate,
    serializeTemplate: serializeTemplate
  };
});