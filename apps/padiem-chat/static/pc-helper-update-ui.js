/* Owner-only version notice and per-PC update preference. */
(() => {
  "use strict";
  const path = "/api/pc/helper-updates";
  const banner = document.getElementById("pcHelperUpdateBanner");
  const card = document.getElementById("accountSettingsSection");
  if (!banner || !card) return;
  const settings = document.createElement("section");
  settings.className = "pc-helper-update-settings";
  settings.hidden = true;
  card.append(settings);
  let epoch = 0, busy = false, rows = [], note = "";
  const authed = () => window.PadiemAuthGate?.authenticated() === true;
  const el = (tag, text) => {
    const node = document.createElement(tag);
    if (text) node.textContent = text;
    return node;
  };
  function language() { return document.documentElement.lang?.startsWith("en") ? "en" : "ko"; }
  const copy = {
    ko: {auto: "자동 업데이트", newVersion: "PC 연결 새 버전이 있어요", now: "지금 업데이트",
      required: "업데이트 후 사용할 수 있어요", close: "닫기", failed: "보내지 못했어요. PC 연결을 확인해 주세요.",
      sent: "PC에 요청을 보냈어요.", install: "자동 업데이트 포함(설정에서 끌 수 있음)", pending: "PC에 적용 중"},
    en: {auto: "Automatic updates", newVersion: "A new PC Connect version is available", now: "Update now",
      required: "Update to use PC commands", close: "Dismiss", failed: "Couldn't complete the request. Check the PC connection.",
      sent: "Request sent to the PC.", install: "Automatic updates included (can be turned off in settings)", pending: "Applying to PC"},
  };
  function render() {
    const t = copy[language()];
    banner.replaceChildren();
    settings.replaceChildren();
    banner.hidden = true;
    settings.hidden = true;
    if (!authed()) return;
    {
      settings.hidden = false;
      settings.append(el("strong", t.auto), el("p", t.install));
      for (const row of rows) {
        const line = el("label");
        const check = el("input");
        check.type = "checkbox";
        check.checked = row.auto_update === true;
        check.disabled = busy || row.online !== true;
        check.addEventListener("change", () => mutate(row, {action:"auto", enabled:check.checked}));
        line.append(check, el("span", (row.label || "PC") + " · " + t.auto));
        if (row.auto_update_applied !== null && row.auto_update_applied !== undefined &&
            row.auto_update_applied !== row.auto_update) {
          line.append(el("span", t.pending));
        }
        settings.append(line);
      }
      if (note) settings.append(el("p", note));
    }
    const eligible = rows.filter(row => row.online && (row.update_required || (!row.dismissed && row.notice)));
    for (const row of eligible) {
      const item = el("div");
      item.className = "pc-helper-update-row";
      const message = el("span", (row.label ? row.label + " · " : "") +
        (row.update_required ? t.required : t.newVersion));
      const update = el("button", t.now);
      update.type = "button"; update.className = "connector-retry"; update.disabled = busy;
      update.addEventListener("click", () => mutate(row, {action:"update"}));
      const close = el("button", t.close);
      close.type = "button"; close.className = "connector-retry"; close.disabled = busy;
      close.addEventListener("click", () => mutate(row, {action:"dismiss", version:row.latest_version}));
      item.append(message, update);
      if (!row.update_required) item.append(close);
      banner.append(item);
    }
    banner.hidden = eligible.length === 0;
    if (!banner.hidden && note) banner.append(el("p", note));
  }
  async function refresh() {
    const token = epoch;
    if (!authed()) { rows = []; note = ""; render(); return; }
    try {
      const response = await fetch(path, {credentials:"same-origin", headers:{Accept:"application/json"}});
      const data = response.ok ? await response.json() : null;
      if (token !== epoch || !authed()) return;
      rows = Array.isArray(data?.devices) ? data.devices : [];
    } catch (_) { if (token !== epoch) return; rows = []; }
    render();
  }
  async function mutate(row, body) {
    if (!authed() || busy) return;
    const token = epoch;
    busy = true; note = ""; render();
    try {
      const response = await fetch(path + "/" + encodeURIComponent(row.link_id), {
        method:"POST", credentials:"same-origin",
        headers:{"Content-Type":"application/json", Accept:"application/json"},
        body:JSON.stringify(body),
      });
      if (token === epoch && authed()) note = copy[language()][response.ok ? "sent" : "failed"];
    } catch (_) { if (token === epoch) note = copy[language()].failed; }
    finally {
      if (token === epoch) { busy = false; await refresh(); }
    }
  }
  function reset() { epoch++; busy = false; rows = []; note = ""; render(); void refresh(); }
  for (const event of ["padiem:auth-state", "padiem:auth-changed", "padiem:account-changed"]) {
    window.addEventListener(event, reset);
  }
  window.addEventListener("focus", refresh);
  setInterval(refresh, 60000);
  reset();
})();
