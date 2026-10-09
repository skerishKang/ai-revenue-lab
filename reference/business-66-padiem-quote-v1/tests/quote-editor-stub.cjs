/* 테스트 공용: 편집기 + B66QuoteAppBridge 스텁.
   실제 제품 모듈인 quote-import-atomic.js 를 그대로 사용해 원자적 적용 경로를 검증한다.
   (테스트가 하네스 자체를 검증하는 일이 없도록, 적용 로직은 제품 코드가 담당한다.) */
const Core = require("../quote-core.js");
const Atomic = require("../quote-import-atomic.js");

const clone = (value) => JSON.parse(JSON.stringify(value));

/* %PDF- 로 시작하는 최소 유효 바이트(형식 검증 통과용). */
function defaultPdfBytes() {
  const bytes = new Uint8Array(512);
  [37, 80, 68, 70, 45].forEach((byte, index) => { bytes[index] = byte; });
  return bytes;
}

/* writeBehavior.mode
     "ok"                 정상 적용
     "fail"               replaceDraft 가 {ok:false} 반환
     "throw"              replaceDraft 가 예외 발생(변이 없음)
     "throwAfterPartial"  replaceDraft 가 일부 수정한 뒤 예외 발생
     "mismatch"           replaceDraft 가 다른 내용을 남김(되읽기 지문 불일치)
     "dropField"          정규화가 필드를 잃는 적용(지문 불일치) */
function createEditorBridge(options) {
  const opts = options || {};
  const behavior = opts.writeBehavior || { mode: "ok" };
  const editor = {
    draft: opts.draft ? clone(opts.draft) : null,
    template: opts.activeTemplate === undefined ? null : clone(opts.activeTemplate),
    selectionRaw: "selection-initial"
  };
  const calls = [];

  function writeDraft(value) {
    const mode = behavior.mode || "ok";
    if (mode === "throwAfterPartial") {
      editor.draft = Core.normalizeDraft(Object.assign({}, value, { memo: "부분 변이" }));
      calls.push("write:throwAfterPartial");
      throw new Error("partial mutation then throw");
    }
    if (mode === "fail") {
      calls.push("write:fail");
      return { ok: false, error: "invalid_draft" };
    }
    if (mode === "mismatch") {
      editor.draft = Core.normalizeDraft(Object.assign({}, value, { memo: "다른 내용" }));
      calls.push("write:mismatch");
      return { ok: true };
    }
    if (mode === "dropField") {
      const dropped = Object.assign({}, value, {
        items: value.items.map((item, index) =>
          index === 0 ? Object.assign({}, item, { unitPrice: 0 }) : item)
      });
      editor.draft = Core.normalizeDraft(dropped);
      calls.push("write:dropField");
      return { ok: true };
    }
    if (mode === "throw") {
      calls.push("write:throw");
      throw new Error("boom");
    }
    editor.draft = Core.normalizeDraft(value);
    calls.push("write:ok");
    return { ok: true, draft: clone(editor.draft) };
  }

  const bridge = {
    getDraft: () => { calls.push("getDraft"); return clone(editor.draft); },
    replaceDraft: (draft) => {
      calls.push("replaceDraft");
      editor.draft = Core.normalizeDraft(draft);
      return { ok: true, draft: clone(editor.draft) };
    },
    applyImportedDraft: (nextDraft, applyOptions) => {
      const o = applyOptions || {};
      calls.push("applyImportedDraft");
      return Atomic.applyImport({
        nextDraft: nextDraft,
        template: o.template,
        resolveActiveTemplate: () => editor.template,
        expectedFingerprint: o.expectedFingerprint,
        fingerprint: o.fingerprint,
        normalize: (value) => Core.normalizeDraft(value),
        readDraft: () => clone(editor.draft),
        writeDraft: writeDraft,
        snapshot: () => ({
          draft: clone(editor.draft),
          template: clone(editor.template),
          selectionRaw: editor.selectionRaw
        }),
        restore: (snapshot) => {
          if (opts.restoreFails === true) {
            calls.push("restore:failed");
            return false;
          }
          try {
            editor.draft = Core.normalizeDraft(snapshot.draft);
            editor.template = clone(snapshot.template);
            editor.selectionRaw = snapshot.selectionRaw;
            calls.push("restore:ok");
            return true;
          } catch (err) {
            calls.push("restore:error");
            return false;
          }
        },
        beforeApply: o.beforeApply
      });
    },
    certifiedPdfBytes: async () => (opts.pdfOk === false
      ? { ok: false, code: "pdf_source_unavailable" }
      : { ok: true, bytes: opts.pdfBytes ? opts.pdfBytes() : defaultPdfBytes(), fileName: "a.pdf" }),
    activeTemplateReference: () => clone(editor.template),
    listApprovedSkills: () => (opts.approvedSkills === undefined ? [] : opts.approvedSkills),
    hasMeaningfulDraft: () => opts.hasMeaningfulDraft === true,
    toast: () => {}
  };

  return {
    bridge, editor, calls,
    writes: () => calls.filter((entry) => entry.indexOf("write:") === 0)
  };
}

module.exports = { createEditorBridge, clone };
