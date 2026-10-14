/* Padiem Claw first-use destinations: reuse the existing Chat four-card shell.
 * No copy of the composer, image, auth, approval, or connector implementation.
 * Cards open the already-existing Connectors dialog and owner-scoped PC list.
 * No download URL, device connection, GitHub write access or success is forged.
 */
(() => {
  "use strict";

  const actions = Object.freeze({
    clawComputerWorkspace: "connectorComputerCard",
    clawDriveWorkspace: 'capability-card[data-connector="google-drive"]',
    clawGithubWorkspace: "connectorGithubCard",
  });

  function install() {
    const shell = document.querySelector(".app-shell");
    const opener = document.getElementById("connectorsNavButton");
    const dialog = document.getElementById("connectorsDialog");
    if (!shell || !opener || !dialog) return;

    function isClawHome() {
      return shell.dataset.state === "claw" &&
        document.getElementById("clawWorkspace")?.dataset.view === "general";
    }

    function openWorkspaceConnector(target) {
      if (!isClawHome()) return;
      // Use the EXACT existing authenticated owner Connectors UI flow.
      opener.click();
      if (!dialog.open && !dialog.hasAttribute("open")) return;
      const selector = target === actions.clawDriveWorkspace
        ? ".capability-card[data-connector=\"google-drive\"]"
        : "#" + target;
      const card = dialog.querySelector(selector);
      if (!card) return;
      if (!card.hasAttribute("tabindex")) card.setAttribute("tabindex", "-1");
      card.focus({ preventScroll: true });
      if (typeof card.scrollIntoView === "function") {
        card.scrollIntoView({ block: "nearest", behavior: "instant" });
      }
    }

    for (const [id, target] of Object.entries(actions)) {
      const card = document.getElementById(id);
      if (card) card.addEventListener("click", () => openWorkspaceConnector(target));
    }

    const web = document.getElementById("clawWebWorkspace");
    web?.addEventListener("click", () => {
      if (!isClawHome()) return;
      // General Claw is already Web-first. Keep the user's current draft
      // and reuse the same shared #messageInput as Padiem Chat.
      document.getElementById("messageInput")?.focus();
    });

    const deviceStatus = document.getElementById("clawComputerDeviceStatusButton");
    const statusText = document.getElementById("clawComputerLiveStatus");
    deviceStatus?.addEventListener("click", async () => {
      if (!isClawHome() || !statusText || deviceStatus.disabled) return;
      // Use the SAME existing, owner-scoped GET endpoint as the Claw device
      // manager; this is status-only and cannot issue a pairing or task grant.
      const en = document.documentElement.lang === "en";
      const show = (ko, english) => {
        statusText.textContent = en ? english : ko;
        statusText.hidden = false;
      };
      deviceStatus.disabled = true;
      show("컴퓨터 연결 상태를 확인하고 있습니다.", "Checking your computer connection.");
      try {
        const response = await fetch("/api/claw/local-access/devices", {
          method: "GET", credentials: "same-origin", cache: "no-store",
          headers: { Accept: "application/json" },
        });
        if (response.status === 401 || response.status === 403) {
          show("먼저 로그인해 주세요.", "Please sign in first.");
        } else if (!response.ok) {
          show("컴퓨터 연결을 아직 확인할 수 없습니다.", "Computer connection is not yet available.");
        } else {
          const raw = await response.text();
          if (raw.length > 32768) throw new Error("invalid device response");
          const data = JSON.parse(raw);
          if (data?.ok !== true || data?.available !== true ||
              data?.ownerScoped !== true || !Array.isArray(data.devices)) {
            throw new Error("unverified device response");
          }
          const count = data.devices.length;
          show(
            count ? "승인된 컴퓨터 " + count + "대가 있습니다. 작업 시 별도 승인이 필요합니다." : "아직 승인된 컴퓨터가 없습니다.",
            count ? count + " approved computer(s). Tasks still require approval." : "No approved computers yet.",
          );
        }
      } catch (_) {
        show("컴퓨터 연결 상태를 확인하지 못했습니다.", "Could not verify computer connection.");
      } finally {
        deviceStatus.disabled = false;
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", install, { once: true });
  } else {
    install();
  }
})();
