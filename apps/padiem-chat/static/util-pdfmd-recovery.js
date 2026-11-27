(() => {
  "use strict";

  /* #8812·#8814 PDF→MD 수리 1차 — 한도 경고 상자와 실패 카드의 [다시 하기].
     util-pdfmd.js 의 줄 상한(#7216)이 "새 기능은 새 모듈 파일로"를 요구하므로
     이 수리의 새 동작을 여기 둔다. 토큰만 쓰고 덮어쓰기는 없다. */

  /* #8812 D5: 하루·쪽수·크기 한도 끊김은 끌어다 놓기 상자 아래 경고 상자 하나로
     나른다. 그 밖의 실패는 카드·상태 줄의 기존 문장을 그대로 쓴다. */
  const LIMIT_NOTICE_CODES = new Set([
    "conversion_quota_exhausted", "document_page_limit", "document_size_limit", "document_too_large",
  ]);

  /* #8812 D6: 하루 한도 0 — 실행 답(429)이 remaining 0을 실어 오거나 코드가
     한도 코드일 때다. */
  function isQuotaExhausted(err) {
    return Boolean(err && (err.code === "conversion_quota_exhausted" ||
      (err.body && err.body.conversion && Number(err.body.conversion.remaining) === 0)));
  }

  window.PadiemPdfMdRecovery = {
    LIMIT_NOTICE_CODES,
    isQuotaExhausted,

    /* deps: el, api, describeError, loadJob, pollItemUntilTerminal,
       uploadStatus, quotaNote, onExhausted, currentJobId */
    create(deps) {
      const el = deps.el;
      const note = el("div", "pdfmd-limit-note");
      note.id = "pdfmdLimitNote";
      note.hidden = true;
      note.setAttribute("role", "alert");
      /* #8812 D1·D2 (CTO 검토): 아이콘+제목은 한 줄, 설명은 그 아래 줄 —
         판이 좁아도 두 칸으로 갈라지지 않는다. */
      const head = el("span", "pdfmd-limit-head");
      head.appendChild(el("span", "pdfmd-limit-icon", "!"));
      const title = el("strong", "pdfmd-limit-title", "");
      head.appendChild(title);
      note.appendChild(head);
      const desc = el("span", "pdfmd-limit-desc", "");
      note.appendChild(desc);

      /* 확인된 문장은 두 문장이다 — 앞문이 상자 제목, 뒷문이 설명. 나머지
         한도 문구는 판정대로 그대로 한 문장 제목으로 나른다. */
      function show(code) {
        const sentence = deps.describeError({ code: code });
        const cut = code === "conversion_quota_exhausted" ? sentence.indexOf(". ") + 1 : sentence.length;
        title.textContent = sentence.slice(0, cut).trim();
        desc.textContent = cut < sentence.length ? sentence.slice(cut).trim() : "";
        desc.hidden = !desc.textContent;
        note.hidden = false;
      }

      function hide() {
        note.hidden = true;
      }

      /* #8812 D6: 하루 한도가 0으로 끝난 순간 — 올리기 상자가 단추 역할을
         내려놓고([파일 고르기] 비활성), 경고 상자가 이유를 말한다. */
      function exhaust() {
        deps.onExhausted();
        show("conversion_quota_exhausted");
      }

      /* #8814 D6·D7: [다시 하기] — 같은 파일·같은 방식. 서버에 저장된 원본을
         다시 읽어 run 한 건으로 끝난다. */
      async function rerun(item) {
        try {
          const data = await deps.api("/api/document-conversions/items/" + item.id + "/run", { method: "POST" });
          hide();
          if (data && data.item && data.item.status === "working") {
            void deps.pollItemUntilTerminal(deps.currentJobId(), data.item);
          }
          await deps.loadJob();
        } catch (e) {
          if (isQuotaExhausted(e)) {
            deps.quotaNote.textContent = "오늘 0건 더 바꿀 수 있어요.";
            exhaust();
          } else {
            deps.uploadStatus.textContent = deps.describeError(e);
          }
        }
      }

      function retryButton(item) {
        const btn = el("button", "pdfmd-btn pdfmd-btn-primary", "다시 하기");
        btn.type = "button";
        btn.setAttribute("aria-label", item.name + " 같은 파일로 다시 하기");
        btn.addEventListener("click", () => { void rerun(item); });
        return btn;
      }

      return { note, show, hide, exhaust, rerun, retryButton };
    },
  };
})();
