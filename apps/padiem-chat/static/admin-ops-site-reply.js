/* #7690 역방향 — 사이트 의견 카드의 '고객에게 보일 답글' + 러브트리 보내기 줄.

운영센터 메모(고객에게 보이지 않음)와 달리, 답글은 고객에게 간다.
상태 알림(운영센터>러브트리)도 여기 보이는 줄 상태(대기·보냄·보내기 실패)와
다시 보내기 버튼으로 눈앞에 남긴다. 색상·간격은 admin.css의 ops-reply
클래스를 그대로 쓴다. */
(() => {
  "use strict";
  let deps = null;
  const SITE_ENDPOINT = "/api/admin/site-feedback";
  const STATE_LABELS = Object.freeze({
    sent: "러브트리로 보냄", pending: "보내기 대기 중", waiting: "보낼 주소·비밀이 없어 줄에 대기 중",
    failed: "보내기 실패", exhausted: "보내기 실패",
  });

  function bind(wired) {
    deps = wired;
  }

  function node(tag, value, className) {
    if (!deps || !deps.node) return null;
    return deps.node(tag, value, className);
  }

  function notifyState(entry) {
    if (entry.kind === "status") {
      return "상태 알림: " + (entry.status || "") + " — " +
        (STATE_LABELS[entry.state] || entry.state);
    }
    return "답글: " + deps.fmtDate(entry.reply_created_at) + " — " +
      (STATE_LABELS[entry.state] || entry.state);
  }

  function resendButton(item, entry) {
    const again = node("button", "다시 보내기", "ops-reply-send");
    again.type = "button";
    again.dataset.eventKey = entry.event_key;
    again.addEventListener("click", () => { void resendOutbox(item, entry.event_key, again); });
    return again;
  }

  function rows(item) {
    const out = [];
    const replies = (item.outbox || []).filter((entry) => entry.kind === "reply");
    const status = (item.outbox || []).filter((entry) => entry.kind === "status")[0];
    for (const entry of replies) {
      out.push(node("p", "고객 답글: " + entry.reply_body, "ops-reply"));
      out.push(node("p", notifyState(entry), "ops-row-news"));
      if (entry.state === "failed" || entry.state === "exhausted") {
        out.push(resendButton(item, entry));
      }
    }
    if (status) {
      out.push(node("p", notifyState(status), "ops-row-news"));
      if (status.state === "failed" || status.state === "exhausted") {
        out.push(resendButton(item, status));
      }
    }
    return out;
  }

  function replyForm(item) {
    const wrap = node("div", null, "ops-reply-form");
    wrap.append(node("p",
      "운영 메모와 다릅니다. 아래 답글은 고객에게 보입니다.", "ops-row-news"));
    const input = document.createElement("textarea");
    input.className = "ops-reply-input";
    input.rows = 2;
    input.maxLength = 2000;
    input.placeholder = "고객에게 보일 답글(2000자까지)";
    input.setAttribute("aria-label", "고객에게 보일 답글 입력");
    const send = node("button", "답글 보내기", "ops-reply-send");
    send.type = "button";
    send.addEventListener("click", () => { void sendReply(item.id, input); });
    wrap.append(input, send);
    return wrap;
  }

  async function sendReply(id, input) {
    const text = input.value;
    const send = input.parentElement ? input.parentElement.querySelector(".ops-reply-send") : null;
    if (send) send.disabled = true;
    try {
      const { status: code, body } = await deps.call(
        SITE_ENDPOINT + "/" + encodeURIComponent(id) + "/reply", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ body: text }),
        });
      if (code === 201 && body?.ok === true) {
        deps.setStatus("opsStatus", "");
        deps.refreshInbox();
      } else {
        deps.setStatus("opsStatus", "답글을 보내지 못했습니다(" +
          (body?.error?.code || code) + ").");
        if (send) send.disabled = false;
      }
    } catch (_) {
      deps.setStatus("opsStatus", "답글을 보내는 중 연결이 끊겼습니다.");
      if (send) send.disabled = false;
    }
  }

  async function resendOutbox(item, eventKey, button) {
    button.disabled = true;
    try {
      const { status: code, body } = await deps.call(
        SITE_ENDPOINT + "/" + encodeURIComponent(item.id) + "/resend", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ eventKey }),
        });
      if (code === 200 && body?.ok === true) {
        deps.refreshInbox();
      } else {
        deps.setStatus("opsStatus", "다시 보내지 못했습니다(" +
          (body?.error?.code || code) + ").");
        button.disabled = false;
      }
    } catch (_) {
      deps.setStatus("opsStatus", "다시 보내는 중 연결이 끊겼습니다.");
      button.disabled = false;
    }
  }

  window.PadiemOpsSiteReply = Object.freeze({ bind, rows, replyForm });
})();
