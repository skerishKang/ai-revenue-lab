/* B66 · Quote Beta — local file intake preflight.
   This module never uploads, persists, OCRs, or calls a model. Server-side
   validation remains authoritative once a same-origin adapter is deployed. */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.B66FileIntake = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var MAX_DOCUMENT_BYTES = 2 * 1024 * 1024;
  var MAX_IMAGE_BYTES = 4 * 1024 * 1024;

  var TYPES = Object.freeze({
    ".pdf": Object.freeze({
      media: Object.freeze(["application/pdf"]),
      category: "native_document",
      label: "PDF",
      maxBytes: MAX_DOCUMENT_BYTES,
      pathHint: "문서의 텍스트를 먼저 확인하고, 스캔 문서이면 이미지 분석 경로로 넘길 예정입니다."
    }),
    ".docx": Object.freeze({
      media: Object.freeze(["application/vnd.openxmlformats-officedocument.wordprocessingml.document"]),
      category: "native_document",
      label: "DOCX",
      maxBytes: MAX_DOCUMENT_BYTES,
      pathHint: "문서 텍스트를 안전하게 추출한 뒤 견적 정보 구조화 단계로 넘길 예정입니다."
    }),
    ".pptx": Object.freeze({
      media: Object.freeze(["application/vnd.openxmlformats-officedocument.presentationml.presentation"]),
      category: "native_document",
      label: "PPTX",
      maxBytes: MAX_DOCUMENT_BYTES,
      pathHint: "슬라이드 텍스트를 안전하게 추출한 뒤 견적 정보 구조화 단계로 넘길 예정입니다."
    }),
    ".xlsx": Object.freeze({
      media: Object.freeze(["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"]),
      category: "native_document",
      label: "XLSX",
      maxBytes: MAX_DOCUMENT_BYTES,
      pathHint: "셀 텍스트를 안전하게 추출한 뒤 견적 정보 구조화 단계로 넘길 예정입니다."
    }),
    ".hwpx": Object.freeze({
      media: Object.freeze(["application/hwp+zip"]),
      category: "native_document",
      label: "HWPX",
      maxBytes: MAX_DOCUMENT_BYTES,
      pathHint: "HWPX 문서 텍스트를 안전하게 추출한 뒤 견적 정보 구조화 단계로 넘길 예정입니다."
    }),
    ".jpg": Object.freeze({
      media: Object.freeze(["image/jpeg"]),
      category: "image",
      label: "JPEG 이미지",
      maxBytes: MAX_IMAGE_BYTES,
      pathHint: "이미지 분석 모델이 연결되면 견적 내용을 읽는 경로로 넘길 예정입니다."
    }),
    ".jpeg": Object.freeze({
      media: Object.freeze(["image/jpeg"]),
      category: "image",
      label: "JPEG 이미지",
      maxBytes: MAX_IMAGE_BYTES,
      pathHint: "이미지 분석 모델이 연결되면 견적 내용을 읽는 경로로 넘길 예정입니다."
    }),
    ".png": Object.freeze({
      media: Object.freeze(["image/png"]),
      category: "image",
      label: "PNG 이미지",
      maxBytes: MAX_IMAGE_BYTES,
      pathHint: "이미지 분석 모델이 연결되면 견적 내용을 읽는 경로로 넘길 예정입니다."
    }),
    ".webp": Object.freeze({
      media: Object.freeze(["image/webp"]),
      category: "image",
      label: "WebP 이미지",
      maxBytes: MAX_IMAGE_BYTES,
      pathHint: "이미지 분석 모델이 연결되면 견적 내용을 읽는 경로로 넘길 예정입니다."
    })
  });

  function extensionOf(name) {
    if (typeof name !== "string") return "";
    var cleaned = name.trim().toLowerCase();
    var index = cleaned.lastIndexOf(".");
    return index >= 0 ? cleaned.slice(index) : "";
  }

  function safeName(name) {
    if (typeof name !== "string") return null;
    var cleaned = name.trim();
    if (!cleaned || cleaned.length > 255) return null;
    for (var i = 0; i < cleaned.length; i += 1) {
      var code = cleaned.charCodeAt(i);
      if (code < 32 || code === 127) return null;
    }
    return cleaned;
  }

  function formatBytes(bytes) {
    if (!Number.isFinite(bytes) || bytes < 0) return "";
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function isGenericMedia(extension, declared) {
    if (!declared) return true;
    if (declared === "application/octet-stream") return true;
    if (
      (declared === "application/zip" || declared === "application/x-zip-compressed") &&
      [".docx", ".pptx", ".xlsx", ".hwpx"].indexOf(extension) >= 0
    ) {
      return true;
    }
    return false;
  }

  function classifyFile(fileLike) {
    if (!fileLike || typeof fileLike !== "object") {
      return { ok: false, error: "invalid_file" };
    }

    var name = safeName(fileLike.name);
    if (!name) return { ok: false, error: "invalid_file_name" };

    var extension = extensionOf(name);
    if (extension === ".hwp") {
      return { ok: false, error: "legacy_hwp_unsupported" };
    }

    var spec = TYPES[extension];
    if (!spec) return { ok: false, error: "unsupported_file_type" };

    var size = Number(fileLike.size);
    if (!Number.isFinite(size) || size < 0 || !Number.isInteger(size)) {
      return { ok: false, error: "invalid_file_size" };
    }
    if (size === 0) return { ok: false, error: "empty_file" };
    if (size > spec.maxBytes) {
      return {
        ok: false,
        error: spec.category === "image" ? "image_too_large" : "document_too_large",
        maxBytes: spec.maxBytes
      };
    }

    var declared = typeof fileLike.type === "string"
      ? fileLike.type.trim().toLowerCase()
      : "";
    if (!isGenericMedia(extension, declared) && spec.media.indexOf(declared) < 0) {
      return { ok: false, error: "media_extension_mismatch" };
    }

    return {
      ok: true,
      value: {
        name: name,
        extension: extension,
        category: spec.category,
        label: spec.label,
        mediaType: isGenericMedia(extension, declared) ? spec.media[0] : declared,
        byteSize: size,
        displaySize: formatBytes(size),
        maxBytes: spec.maxBytes,
        pathHint: spec.pathHint,
        serverAnalysisReady: false
      }
    };
  }


  /* #3586: reusable-template REGISTRATION source allowlist, not generic
     quote fact extraction nor #3884 private original-file custody. */
  var TEMPLATE_SOURCE_EXTENSIONS = Object.freeze([".xlsx"]);

  function classifyTemplateSourceFile(fileLike) {
    var extension = extensionOf(fileLike && fileLike.name);
    if (extension === ".xls") return { ok: false, error: "legacy_xls_unsupported" };
    if (extension === ".hwp") return { ok: false, error: "legacy_hwp_unsupported" };
    if (extension === ".hwpx") return { ok: false, error: "template_hwpx_not_available" };
    if (TEMPLATE_SOURCE_EXTENSIONS.indexOf(extension) === -1) {
      return { ok: false, error: "template_source_format_not_allowed" };
    }
    return classifyFile(fileLike);
  }

  /* Accepts FileIntake {ok,value}, or legacy analyzer preflight {ok,name,
     extension,media,size}, or file-source registration metadata. Re-check
     filename/extension/MIME/size on every registration entrypoint. */
  function validateTemplateSourcePreflight(preflight) {
    if (!preflight || preflight.ok !== true) {
      return preflight && preflight.error
        ? { ok: false, error: preflight.error }
        : { ok: false, error: "invalid_preflight" };
    }
    var source = preflight.value && typeof preflight.value === "object"
      ? preflight.value : preflight;
    var name = typeof source.name === "string" ? source.name : source.filename;
    var declaredExtension = source.extension;
    if (declaredExtension !== undefined &&
        declaredExtension !== extensionOf(name)) {
      return { ok: false, error: "template_source_extension_mismatch" };
    }
    var size = source.byteSize !== undefined ? source.byteSize : source.size;
    var type = source.mediaType !== undefined ? source.mediaType : source.media;
    var checked = classifyTemplateSourceFile({ name: name, type: type, size: size });
    if (!checked.ok) return checked;
    return {
      ok: true,
      name: checked.value.name,
      extension: checked.value.extension,
      media: checked.value.mediaType,
      size: checked.value.byteSize,
      value: checked.value
    };
  }

  function errorMessage(result) {
    var code = result && result.error;
    if (code === "legacy_xls_unsupported") {
      return "이 형식은 구형 Excel(.xls) 문서라 양식 등록에서 지원하지 않습니다. Excel에서 .xlsx로 저장한 뒤 업로드해 주세요.";
    }
    if (code === "template_hwpx_not_available") {
      return "HWPX 양식 등록은 추후 지원합니다. 현재 재사용 양식은 Excel .xlsx만 등록할 수 있습니다.";
    }
    if (code === "template_source_format_not_allowed") {
      return "재사용 견적서 양식 등록은 .xlsx 파일만 지원합니다. PDF·이미지는 일반 견적 내용 분석에서 사용할 수 있습니다.";
    }
    if (code === "template_source_extension_mismatch") {
      return "양식 등록 파일 이름과 확장자 정보가 일치하지 않습니다. .xlsx 파일을 다시 선택해 주세요.";
    }
    if (code === "legacy_hwp_unsupported") {
      return "기존 HWP(.hwp)는 아직 지원하지 않습니다. 가능하면 HWPX 또는 PDF로 저장해 주세요.";
    }
    if (code === "unsupported_file_type") {
      return "PDF, DOCX, PPTX, XLSX, HWPX, JPG, PNG, WebP 파일을 선택해 주세요.";
    }
    if (code === "empty_file") return "빈 파일은 사용할 수 없습니다.";
    if (code === "image_too_large") return "이미지는 4 MB 이하만 선택할 수 있습니다.";
    if (code === "document_too_large") return "문서는 2 MB 이하만 선택할 수 있습니다.";
    if (code === "media_extension_mismatch") return "파일 확장자와 브라우저가 확인한 파일 형식이 서로 다릅니다.";
    if (code === "invalid_file_name") return "파일 이름을 확인해 주세요.";
    return "이 파일을 안전하게 확인하지 못했습니다.";
  }

  return {
    MAX_DOCUMENT_BYTES: MAX_DOCUMENT_BYTES,
    MAX_IMAGE_BYTES: MAX_IMAGE_BYTES,
    TYPES: TYPES,
    extensionOf: extensionOf,
    formatBytes: formatBytes,
    isGenericMedia: isGenericMedia,
    classifyFile: classifyFile,
    TEMPLATE_SOURCE_EXTENSIONS: TEMPLATE_SOURCE_EXTENSIONS,
    classifyTemplateSourceFile: classifyTemplateSourceFile,
    validateTemplateSourcePreflight: validateTemplateSourcePreflight,
    errorMessage: errorMessage
  };
});
