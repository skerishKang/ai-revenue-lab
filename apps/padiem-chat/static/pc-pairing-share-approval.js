// #8081 — share-unit approval for the owner's own connection card.
// The card stays a connect-and-name surface; this module renders only the
// reported share candidates and calls the existing owner-scoped roots endpoint.
// It uses existing theme tokens and adds no CSS rule or colour literal.
(() => {
  "use strict";

  const COPY = Object.freeze({
    ko: { shareConsent: "이 공유 폴더 안만 열린다" },
    en: { shareConsent: "이 공유 폴더 안만 열린다" },
  });

  function language() {
    const lang = (document.documentElement.lang || "ko").toLowerCase();
    return lang.startsWith("en") ? "en" : "ko";
  }

  function copy(code) {
    return COPY[code === "en" ? "en" : "ko"];
  }

  async function approve(link, candidate, onApproved) {
    if (!link || !candidate || typeof candidate.root_ref !== "string") return false;
    const response = await fetch(
      "/api/pc/pairings/" + encodeURIComponent(link.link_id) + "/roots",
      {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          root_ref: candidate.root_ref,
          consent: copy(language()).shareConsent,
        }),
      },
    );
    if (!response.ok) return false;
    if (typeof onApproved === "function") await onApproved();
    return true;
  }

  function mount(row, link, onApproved) {
    const candidates = Array.isArray(link.share_candidates) ? link.share_candidates : [];
    if (!candidates.length) return;
    const wrap = document.createElement("div");
    wrap.className = "pc-pairing-shares";
    wrap.setAttribute("style", "display:grid;flex:1 1 100%;gap:6px;");
    for (const candidate of candidates) {
      if (!candidate || typeof candidate.root_ref !== "string") continue;
      const share = document.createElement("div");
      share.className = "pc-pairing-share";
      share.setAttribute("style", "display:flex;align-items:center;gap:8px;min-height:32px;"
        + "padding:4px 8px;border:1px solid var(--line);border-radius:var(--radius-sm);"
        + "background:var(--panel);");
      share.dataset.rootRef = candidate.root_ref;
      const name = document.createElement("span");
      name.className = "pc-pairing-share-name";
      name.textContent = (candidate.mapped_drive ? candidate.mapped_drive + " " : "")
        + (candidate.label || candidate.path || "");
      name.setAttribute("style", "overflow:hidden;text-overflow:ellipsis;"
        + "white-space:nowrap;font-size:12px;color:var(--muted);");
      const button = document.createElement("button");
      button.className = "pc-pairing-share-approve";
      button.type = "button";
      button.textContent = copy(language()).shareConsent;
      button.setAttribute("style", "flex:none;min-height:32px;padding:4px 10px;"
        + "border:1px solid var(--line);border-radius:var(--radius-xs);"
        + "background:var(--panel);color:var(--accent-strong);cursor:pointer;"
        + "font:inherit;font-size:11px;font-weight:700;");
      button.addEventListener("click", () => { void approve(link, candidate, onApproved); });
      share.append(name, button);
      wrap.append(share);
    }
    row.append(wrap);
  }

  window.PadiemPcShareApproval = Object.freeze({ copy, mount, approve });
})();
