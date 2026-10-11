/* B66 — 견적 불러오기 적용의 원자성 (#3871, CENTRAL revision-3 지적).
   불러오기 실패가 사용자가 작성 중이던 내용이나 선택한 승인 템플릿을 바꾸면 안 된다.

   이 모듈은 편집기를 직접 만지지 않는다. 호출자가 넘긴 훅(readDraft/writeDraft/
   snapshot/restore/fingerprint)만 사용해 다음 순서를 강제한다.

     1) 가져올 draft 정규화 (실패 → 변이 없음)
     2) 승인 템플릿 권위 사전 확인 (불일치 → 변이 없음)
     3) 내용 지문 사전 확인 (불일치 → 변이 없음)
     4) 기존 상태 스냅샷 + 기존 내용 지문 기록
     5) 적용 직전 가드(계정 권위·세션 세대) 재확인
     6) 적용
     7) 되읽어 지문 검증
     8) 실패하면 복구하고, 복구가 실제로 되었는지 다시 지문으로 확인

   복구에 실패했거나 확인할 수 없으면 `preserved=false` 로 보고한다.
   보존을 주장하지 않는다.

   DOM 없음. 브라우저/Node 양쪽에서 실행된다. */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.B66QuoteImportAtomic = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var CODES = {
    INVALID_DRAFT: "invalid_draft",
    TEMPLATE_MISMATCH: "template_authority_mismatch",
    FINGERPRINT_MISMATCH: "content_fingerprint_mismatch",
    FINGERPRINT_UNAVAILABLE: "fingerprint_unavailable",
    GUARD_REJECTED: "apply_guard_rejected",
    REPLACE_FAILED: "replace_failed",
    REPLACE_EXCEPTION: "replace_exception",
    VERIFY_FAILED: "apply_verification_failed",
    HELPER_UNAVAILABLE: "import_helper_unavailable",
    SNAPSHOT_UNAVAILABLE: "snapshot_unavailable"
  };

  var MAX_CODE_CHARS = 64;

  function boundedCode(value, fallback) {
    if (typeof value !== "string") return fallback;
    var text = value.trim();
    if (!text) return fallback;
    return text.slice(0, MAX_CODE_CHARS);
  }

  /* 템플릿 권위 비교: 표시용 이름이 아니라 savedSkillId + fingerprint 만 본다. */
  function sameTemplateAuthority(left, right) {
    return Boolean(
      left && right &&
      typeof left.savedSkillId === "string" && left.savedSkillId &&
      typeof right.savedSkillId === "string" && right.savedSkillId &&
      left.savedSkillId === right.savedSkillId &&
      typeof left.fingerprint === "string" && left.fingerprint &&
      typeof right.fingerprint === "string" && right.fingerprint &&
      left.fingerprint === right.fingerprint
    );
  }

  function safeFingerprint(fn, draft) {
    if (typeof fn !== "function") return null;
    try {
      var value = fn(draft);
      return typeof value === "string" && value ? value : null;
    } catch (err) {
      return null;
    }
  }

  function safeReadDraft(fn) {
    if (typeof fn !== "function") return null;
    try {
      return fn();
    } catch (err) {
      return null;
    }
  }

  function outcome(ok, code, applied, restored, preserved, extra) {
    return Object.assign({
      ok: ok === true,
      code: code ? boundedCode(code, null) : null,
      applied: applied === true,
      restored: restored === true,
      /* preserved=true 는 "기존 내용과 템플릿이 지문으로 확인된 상태로 그대로" 라는 뜻이다. */
      preserved: preserved === true,
      draft: null,
      originalFingerprint: null,
      finalFingerprint: null
    }, extra || {});
  }

  function applyImport(options) {
    var opts = options || {};

    var hooks = ["readDraft", "writeDraft", "snapshot", "restore"];
    for (var index = 0; index < hooks.length; index += 1) {
      if (typeof opts[hooks[index]] !== "function") {
        return outcome(false, CODES.HELPER_UNAVAILABLE, false, false, false);
      }
    }

    /* 1) 가져올 draft 정규화 — 실패하면 편집기를 건드리지 않는다. */
    var nextDraft = opts.nextDraft;
    if (typeof opts.normalize === "function") {
      try {
        nextDraft = opts.normalize(nextDraft);
      } catch (err) {
        nextDraft = null;
      }
      if (!nextDraft) return outcome(false, CODES.INVALID_DRAFT, false, false, true);
    }

    /* 2) 승인 템플릿 권위 사전 확인 — 변이 없음. */
    var activeTemplate = typeof opts.resolveActiveTemplate === "function"
      ? opts.resolveActiveTemplate()
      : opts.activeTemplate;
    if (!sameTemplateAuthority(opts.template, activeTemplate)) {
      return outcome(false, CODES.TEMPLATE_MISMATCH, false, false, true);
    }

    /* 3) 내용 지문 사전 확인 — 변이 없음. */
    var nextFingerprint = safeFingerprint(opts.fingerprint, nextDraft);
    if (!nextFingerprint) {
      return outcome(false, CODES.FINGERPRINT_UNAVAILABLE, false, false, true);
    }
    var expectedFingerprint = typeof opts.expectedFingerprint === "string" && opts.expectedFingerprint
      ? opts.expectedFingerprint
      : nextFingerprint;
    if (nextFingerprint !== expectedFingerprint) {
      return outcome(false, CODES.FINGERPRINT_MISMATCH, false, false, true);
    }

    /* 4) 기존 상태 스냅샷 + 기존 내용 지문 기록. */
    var snapshot = null;
    try {
      snapshot = opts.snapshot();
    } catch (err) {
      snapshot = null;
    }
    if (!snapshot) {
      return outcome(false, CODES.SNAPSHOT_UNAVAILABLE, false, false, false);
    }
    var originalFingerprint = safeFingerprint(opts.fingerprint, safeReadDraft(opts.readDraft));

    /* 5) 적용 직전 가드: 계정 권위·세션 세대를 여기서 마지막으로 확인한다. */
    if (typeof opts.beforeApply === "function") {
      var guard = null;
      try {
        guard = opts.beforeApply();
      } catch (err) {
        guard = { ok: false, code: CODES.GUARD_REJECTED };
      }
      if (!guard || guard.ok !== true) {
        return outcome(false, (guard && guard.code) || CODES.GUARD_REJECTED, false, false, true);
      }
    }

    /* 6) 적용. */
    var applied = null;
    var threw = false;
    try {
      applied = opts.writeDraft(nextDraft);
    } catch (err) {
      threw = true;
      applied = { ok: false, error: CODES.REPLACE_EXCEPTION };
    }

    /* 7) 되읽어 지문 검증. */
    var verified = false;
    if (!threw && applied && applied.ok === true) {
      var readBack = safeFingerprint(opts.fingerprint, safeReadDraft(opts.readDraft));
      verified = Boolean(readBack) && readBack === expectedFingerprint;
    }
    if (verified) {
      return outcome(true, null, true, false, false, {
        draft: safeReadDraft(opts.readDraft),
        originalFingerprint: originalFingerprint,
        finalFingerprint: expectedFingerprint
      });
    }

    /* 8) 복구. 복구 결과를 지문으로 다시 확인한 뒤에만 보존을 주장한다. */
    var restored = false;
    try {
      restored = opts.restore(snapshot) === true;
    } catch (err) {
      restored = false;
    }
    var finalFingerprint = safeFingerprint(opts.fingerprint, safeReadDraft(opts.readDraft));
    var preserved = restored === true &&
      Boolean(originalFingerprint) &&
      finalFingerprint === originalFingerprint;

    var code = CODES.VERIFY_FAILED;
    if (threw) code = CODES.REPLACE_EXCEPTION;
    else if (applied && applied.ok === false) code = boundedCode(applied.error, CODES.REPLACE_FAILED);

    return outcome(false, code, false, restored, preserved, {
      originalFingerprint: originalFingerprint,
      finalFingerprint: finalFingerprint
    });
  }

  return Object.freeze({
    CODES: CODES,
    sameTemplateAuthority: sameTemplateAuthority,
    applyImport: applyImport
  });
});
