// #7780 — 프로필 메뉴(위로 열림). 계정 영역 로직은 모듈 쪽에 둔다(#7216).
// 기존 id·동작은 그대로 재사용한다: 설정은 settingsButton, 앱 연결은
// connectorsNavButton, 로그아웃은 설정 창 안 settingsLogoutButton을 그대로
// 누르는 것으로 같은 signOut 경로를 탄다. app.js는 profileToggle의 클릭
// 한 줄만 이 모듈의 toggle로 연결한다.
(() => {
  "use strict";
  let lastToggle = null;
  let wired = false;

  function menu() { return document.getElementById("profileMenu"); }
  function toggles() {
    return [
      document.getElementById("accountProfileButton"),
      document.getElementById("profileGuestMenuButton"),
    ].filter(Boolean);
  }
  function isOpen() { const m = menu(); return Boolean(m && !m.hidden); }

  function closeProfileMenu(restoreFocus = false) {
    const m = menu();
    if (!m) return;
    m.hidden = true;
    for (const t of toggles()) t.setAttribute("aria-expanded", "false");
    if (restoreFocus && lastToggle && document.contains(lastToggle)) lastToggle.focus();
  }

  function toggleProfileMenu() {
    const m = menu();
    if (!m) return;
    if (!m.hidden) { closeProfileMenu(true); return; }
    const active = document.activeElement;
    lastToggle = toggles().includes(active) ? active : (toggles()[0] || null);
    m.hidden = false;
    for (const t of toggles()) t.setAttribute("aria-expanded", "true");
    const first = m.querySelector("button:not([hidden]), a[href]");
    if (first && typeof first.focus === "function") first.focus();
  }

  function syncLogoutVisibility() {
    const account = document.querySelector(".sidebar-account");
    const logout = document.getElementById("profileLogoutButton");
    if (!account || !logout) return;
    const state = account.dataset.accountState || "pending";
    logout.hidden = !(state === "signed_in");
  }

  function wire() {
    if (wired) return;
    wired = true;
    const m = menu();
    if (!m) return;
    const profileToggle = document.getElementById("accountProfileButton");
    if (profileToggle) {
      profileToggle.setAttribute("aria-controls", "profileMenu");
      profileToggle.setAttribute("aria-haspopup", "menu");
    }
    const guestButton = document.getElementById("profileGuestMenuButton");
    if (guestButton) guestButton.addEventListener("click", toggleProfileMenu);
    const logout = document.getElementById("profileLogoutButton");
    if (logout) {
      logout.addEventListener("click", () => {
        closeProfileMenu(false);
        const settingsLogout = document.getElementById("settingsLogoutButton");
        if (settingsLogout) settingsLogout.click();
      });
    }
    m.addEventListener("click", (event) => {
      const item = event.target.closest("button, a");
      if (!item || item === logout) return;
      closeProfileMenu(false);
    });
    document.addEventListener("pointerdown", (event) => {
      if (!isOpen()) return;
      const inside = m.contains(event.target) || toggles().some((t) => t.contains(event.target));
      if (!inside) closeProfileMenu(false);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape" || event.isComposing) return;
      if (isOpen()) closeProfileMenu(true);
    });
    window.addEventListener("padiem:auth-state", syncLogoutVisibility);
    const account = document.querySelector(".sidebar-account");
    if (account && typeof MutationObserver === "function") {
      new MutationObserver(syncLogoutVisibility).observe(account, {
        attributes: true, attributeFilter: ["data-account-state"],
      });
    }
    syncLogoutVisibility();
  }

  window.PadiemChatProfileMenuModule = {
    create() { return { toggleProfileMenu, closeProfileMenu, syncLogoutVisibility, wireProfileMenu: wire }; },
  };
  // app.js의 profileToggle 클릭 한 줄이 이 toggle을 호출한다.
  window.PadiemChatProfileMenu = { toggle: toggleProfileMenu, close: closeProfileMenu };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wire, { once: true });
  else wire();
})();
