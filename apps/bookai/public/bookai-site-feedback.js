(() => {
  "use strict";
  const openButton = document.getElementById("bookaiFeedbackOpen");
  const dialog = document.getElementById("bookaiFeedbackDialog");
  const form = document.getElementById("bookaiFeedbackForm");
  if (!openButton || !dialog || !form) return;
  const body = document.getElementById("bookaiFeedbackBody");
  const screenToggle = document.getElementById("bookaiFeedbackScreen");
  const trap = document.getElementById("bookaiFeedbackTrap");
  const status = document.getElementById("bookaiFeedbackStatus");
  const done = document.getElementById("bookaiFeedbackDone");
  const again = document.getElementById("bookaiFeedbackAgain");
  const send = form.querySelector(".bookai-feedback-send");
  const ENDPOINT = "https://chat.padiem.net/api/site-feedback";
  const SITE = "bookai";
  const MAX = 2000;
  let renderedAt = 0;

  const setStatus = (text) => { if (status) status.textContent = text || ""; };
  const showForm = () => {
    dialog.hidden = false;
    if (typeof dialog.showModal === "function" && !dialog.open) dialog.showModal();
    if (done) done.hidden = true;
    form.hidden = false;
    renderedAt = Date.now();
    setStatus("");
    if (body) body.focus();
  };
  openButton.addEventListener("click", showForm);
  if (again) again.addEventListener("click", showForm);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = body ? body.value.trim() : "";
    if (!text) { setStatus("내용을 적어 주세요."); if (body) body.focus(); return; }
    if (Array.from(text).length > MAX) { setStatus(`${MAX}자까지 적을 수 있습니다.`); return; }
    if (trap && trap.value) { setStatus("보내지 못했습니다. 잠시 후 다시 시도해 주세요."); return; }
    const value = {
      site: SITE,
      body: text,
      rendered_at: renderedAt || Date.now() - 2000,
      honeypot: trap ? trap.value : ""
    };
    if (screenToggle && screenToggle.checked) {
      value.screen = {
        url: location.origin + location.pathname,
        width: Math.round(window.innerWidth),
        height: Math.round(window.innerHeight)
      };
    }
    if (send) send.disabled = true;
    setStatus("보내는 중입니다.");
    try {
      const response = await fetch(ENDPOINT, {
        method: "POST",
        mode: "cors",
        credentials: "omit",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(value)
      });
      if (response.status === 201) {
        form.reset();
        setStatus("");
        form.hidden = true;
        if (done) {
          done.hidden = false;
          if (again) again.focus();
        }
      } else if (response.status === 429) {
        setStatus("오늘은 더 이상 보낼 수 없습니다. 내일 다시 시도해 주세요.");
      } else if (response.status === 413) {
        setStatus(`${MAX}자까지 적을 수 있습니다.`);
      } else {
        setStatus("보내지 못했습니다. 잠시 후 다시 시도해 주세요.");
      }
    } catch (_) {
      setStatus("보내지 못했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      if (send) send.disabled = false;
    }
  });
  dialog.hidden = true;
  form.hidden = false;
  if (done) done.hidden = true;
})();
