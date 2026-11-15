(() => {
  "use strict";
  const root = document.getElementById("siteFeedback");
  const open = document.getElementById("siteFeedbackOpen");
  const form = document.getElementById("siteFeedbackForm");
  if (!root || !open || !form) return;
  const body = document.getElementById("siteFeedbackBody");
  const trap = document.getElementById("siteFeedbackTrap");
  const status = document.getElementById("siteFeedbackStatus");
  const count = document.getElementById("siteFeedbackCount");
  // #7550 동훈 3회차: a 201 receipt replaces the form with an announced notice
  // (aria-live) and a way back to the form; failures keep the form open.
  const done = document.getElementById("siteFeedbackDone");
  const again = document.getElementById("siteFeedbackAgain");
  const send = form.querySelector(".site-feedback-send");
  const ENDPOINT = "https://chat.padiem.net/api/site-feedback";
  const SITE = "miraen-home";
  const MAX = 2000;
  let renderedAt = 0;

  const setStatus = (text) => { if (status) status.textContent = text || ""; };
  const updateCount = () => { if (count && body) count.textContent = `${Array.from(body.value).length} / ${MAX}`; };
  const openForm = () => {
    root.hidden = false;
    open.hidden = true;
    if (done) done.hidden = true;
    form.hidden = false;
    renderedAt = Date.now();
    setStatus("");
    if (body) body.focus();
  };
  const resetForm = () => {
    form.reset();
    updateCount();
    if (send) send.disabled = false;
    if (body) body.focus();
  };

  open.addEventListener("click", openForm);
  if (again) again.addEventListener("click", openForm);
  if (body) body.addEventListener("input", updateCount);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = body ? body.value.trim() : "";
    if (!text) { setStatus("내용을 적어 주세요."); if (body) body.focus(); return; }
    if (Array.from(text).length > MAX) { setStatus(`${MAX}자까지 적을 수 있습니다.`); return; }
    if (trap && trap.value) { setStatus("보내지 못했습니다. 잠시 후 다시 시도해 주세요."); return; }
    const screen = {
      url: location.origin + location.pathname,
      width: Math.round(window.innerWidth),
      height: Math.round(window.innerHeight)
    };
    if (send) send.disabled = true;
    setStatus("보내는 중입니다.");
    try {
      const response = await fetch(ENDPOINT, {
        method: "POST",
        mode: "cors",
        credentials: "omit",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          site: SITE,
          body: text,
          screen,
          rendered_at: renderedAt || Date.now() - 2000,
          honeypot: trap ? trap.value : ""
        })
      });
      const data = await response.json().catch(() => null);
      if (response.status === 201 && data && data.ok === true) {
        form.reset();
        updateCount();
        if (send) send.disabled = false;
        setStatus("");
        form.hidden = true;
        if (done) done.hidden = false;
        if (again) again.focus();
      } else if (response.status === 429) {
        setStatus("오늘은 더 이상 보낼 수 없습니다. 내일 다시 시도해 주세요.");
      } else if (response.status === 413) {
        setStatus(`${MAX}자까지 적을 수 있습니다.`);
      } else {
        setStatus("보내지 못했습니다. 잠시 후 다시 시도해 주세요. 급한 일은 의원실 전화(062-613-5133)·이메일로 연락해 주세요.");
      }
    } catch (_) {
      setStatus("보내지 못했습니다. 잠시 후 다시 시도해 주세요. 급한 일은 의원실 전화(062-613-5133)·이메일로 연락해 주세요.");
    } finally {
      if (send) send.disabled = false;
    }
  });

  root.hidden = false;
  open.hidden = false;
  form.hidden = true;
  if (done) done.hidden = true;
  updateCount();
})();