(() => {
  "use strict";
  const API = "/api/padiem/b66/admin";
  const el = (id) => document.getElementById(id);
  const access = el("access");
  const status = el("inquiryStatus");
  async function req(path, init = {}) {
    const r = await fetch(API + path, {
      credentials: "same-origin", cache: "no-store",
      headers: {"Accept": "application/json", ...(init.headers || {})},
      ...init
    });
    const payload = await r.json().catch(() => ({}));
    if (!r.ok || payload.ok !== true) {
      throw new Error(payload?.error?.code || "request_failed");
    }
    return payload;
  }
  function div(text, className = "") {
    const node = document.createElement("div");
    node.textContent = text;
    node.className = className;
    return node;
  }
  async function refresh() {
    const list = el("inquiryList");
    list.replaceChildren();
    status.textContent = "문의 목록을 불러오는 중입니다.";
    try {
      const value = el("inquiryFilter").value;
      const data = await req("/inquiries?status=" + encodeURIComponent(value));
      for (const item of data.inquiries || []) {
        const article = document.createElement("article");
        article.style.cssText = "padding:18px 0;border-bottom:1px solid #ccd5e1;white-space:pre-wrap;overflow-wrap:anywhere";
        article.append(
          div((item.status === "resolved" ? "[처리 완료] " : "[미처리] ") +
              (item.subject || ""), "member-email"),
          div((item.email || "") + " · " + (item.category || "") +
              " · " + (item.created_at || "").slice(0, 16), "note"),
          div(item.body || ""),
          div("문의번호: " + (item.inquiry_id || ""), "note")
        );
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = item.status === "resolved" ? "미처리로 변경" : "처리 완료";
        button.addEventListener("click", async () => {
          button.disabled = true;
          try {
            await req("/inquiries/" + encodeURIComponent(item.inquiry_id), {
              method:"PATCH", headers:{"Content-Type":"application/json"},
              body:JSON.stringify({status:item.status === "resolved" ? "open" : "resolved"})
            });
            await refresh();
          } catch (_) {
            status.textContent = "처리 상태를 변경하지 못했습니다.";
            button.disabled = false;
          }
        });
        article.append(button);
        list.append(article);
      }
      status.textContent = "문의 " + (data.inquiries || []).length + "건 표시 중입니다.";
      el("inquiryRetry").hidden = data.notification_delivery_configured !== true;
    } catch (e) {
      status.textContent = "조회 실패: " + e.message;
    }
  }
  async function initialize() {
    try {
      const r = await req("/me");
      if (r.admin !== true) throw new Error("관리자 권한이 없습니다.");
      access.hidden = true;
      el("inquiryContent").hidden = false;
      await refresh();
    } catch (_e) {
      access.textContent = "관리자 계정으로 로그인해 주세요.";
    }
  }
  el("inquiryFilter").addEventListener("change", refresh);
  el("inquiryReload").addEventListener("click", refresh);
  el("inquiryRetry").addEventListener("click", async () => {
    try {
      const r = await req("/inquiries/dispatch", {method:"POST"});
      status.textContent = "발송 완료 " + r.result.sent + "건, 실패 " + r.result.failed + "건";
      await refresh();
    } catch (e) {
      status.textContent = "알림 재전송 실패: " + e.message;
    }
  });
  initialize();
})();
