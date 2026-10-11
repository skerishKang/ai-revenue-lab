(() => {
  "use strict";
  const open = document.getElementById("b66OpenInquiry");
  const dialog = document.getElementById("b66InquiryDialog");
  const close = document.getElementById("b66CloseInquiry");
  const form = document.getElementById("b66InquiryForm");
  const message = document.getElementById("b66InquiryStatus");
  if (!open || !dialog || !form) return;
  open.addEventListener("click", () => {
    message.textContent = "";
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.hidden = false;
  });
  close?.addEventListener("click", () => {
    if (typeof dialog.close === "function") dialog.close();
    else dialog.hidden = true;
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    message.textContent = "문의를 접수하고 있습니다.";
    const data = {
      category: document.getElementById("b66InquiryCategory").value,
      subject: document.getElementById("b66InquirySubject").value.trim(),
      body: document.getElementById("b66InquiryBody").value.trim(),
    };
    try {
      const response = await fetch("/api/padiem/b66/inquiries", {
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify(data),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || result.ok !== true) {
        const code = result?.error?.code;
        const errors = {
          auth_required: "로그인 후 문의할 수 있습니다.",
          inquiry_rate_limited: "문의는 한 시간에 3건까지 접수할 수 있습니다.",
          inquiries_unavailable: "문의 서비스가 준비되지 않았습니다. 잠시 후 다시 시도해 주세요.",
          invalid_inquiry: "제목과 문의 내용을 확인해 주세요."
        };
        message.textContent = errors[code] || "문의 접수에 실패했습니다. 다시 시도해 주세요.";
        return;
      }
      form.reset();
      message.textContent = "문의가 접수되었습니다. 번호: " + result.inquiry_id;
    } catch (_error) {
      message.textContent = "연결 문제가 발생했습니다. 다시 시도해 주세요.";
    } finally {
      button.disabled = false;
    }
  });
})();
