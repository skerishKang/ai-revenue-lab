/* PADIEM connector management: links and credential removal only in this view.
 * A Claw OFF toggle must never be confused with deleting a provider grant.
 */
(() => {
  "use strict";
  const dialog = document.getElementById("connectorsDialog");
  const github = document.getElementById("connectorGithubCard");
  const drive = dialog?.querySelector('[data-connector-id="connector:google:drive@1"]');
  const githubState = document.getElementById("connectorGithubState");
  const githubPrimary = document.getElementById("connectorGithubPrimary");
  const githubRemove = document.getElementById("connectorGithubRemove");
  const githubPermissions = document.getElementById("connectorGithubPermissions");
  const githubFeedback = document.getElementById("connectorGithubFeedback");
  const driveRemove = document.getElementById("connectorDriveRemove");
  const driveFeedback = document.getElementById("connectorDriveFeedback");
  if (!dialog || !github || !drive || !githubState || !githubPrimary ||
      !githubRemove || !driveRemove) return;

  const english = () => document.documentElement.lang === "en";
  const tr = (ko, en) => english() ? en : ko;
  const githubUrl = "/api/connectors/github/start";
  const state = {github: "unknown", linked: false, pending: false, drivePending: false};
  const show = (element, visible) => {if (element) element.hidden = !visible;};
  const write = (element, value) => {if (element) element.textContent = value;};
  let readGeneration = 0;
  const updateClaw = () => window.dispatchEvent(new Event("focus"));

  function updateGithub() {
    const {github:connection,linked,pending} = state;
    const known = connection === "on" || connection === "off";
    github.dataset.connectorStatus = known
      ? (connection === "on" ? "connected" : "not_connected") : "unavailable";
    write(githubState, connection === "on" ? tr("연결됨 · ON","Connected · ON") :
      connection === "off" && linked ? tr("일시 중지 · OFF","Paused · OFF") :
      connection === "off" ? tr("연결 안 됨","Not connected") :
      tr("연결 상태 확인 불가","Connection status unavailable"));
    show(githubPrimary, known);
    show(githubRemove, known && linked);
    show(githubPermissions, known && linked);
    githubPrimary.disabled = pending;
    githubRemove.disabled = pending;
    write(githubPrimary, linked
      ? (connection === "on" ? tr("일시 중지","Pause") : tr("다시 켜기","Resume"))
      : tr("GitHub 연결","Connect GitHub"));
  }

  function updateDrive() {
    const connected = drive.dataset.connectorStatus === "connected";
    show(driveRemove, connected);
    driveRemove.disabled = state.drivePending;
  }

  async function json(url, options = {}) {
    const response = await fetch(url, {
      credentials: "same-origin", cache: "no-store",
      headers: {Accept:"application/json"}, ...options
    });
    const document = await response.json().catch(() => null);
    if (!response.ok || document?.ok !== true) throw new Error("unverified authority");
    return document;
  }

  async function readGithub() {
    if (!dialog.open) return;
    const generation = ++readGeneration;
    try {
      const data = await json("/api/connectors/github/status");
      if (generation !== readGeneration || !dialog.open) return;
      state.github = ["on","off"].includes(data.state) ? data.state : "unknown";
      state.linked = data.linked === true;
      write(githubFeedback, "");
      show(githubFeedback, false);
    } catch (_) {
      if (generation !== readGeneration || !dialog.open) return;
      state.github = "unknown";
      state.linked = false;
      // A missing backend/credential is NOT proof of OFF or an OAuth permission.
      write(githubFeedback, tr("서버 연결 상태를 확인하지 못했습니다.","Unable to verify the GitHub connection."));
      show(githubFeedback, true);
    }
    updateGithub();
  }

  function confirmRemoval(button, feedback, name) {
    if (button.dataset.confirmRemove === "yes") return true;
    button.dataset.confirmRemove = "yes";
    write(button,tr("연결 삭제 확인","Confirm removal"));
    write(feedback, tr(name+"의 연결 정보를 삭제하면 다시 로그인해야 합니다. 계속하려면 한 번 더 누르세요.",
      "Removing "+name+" authorization requires signing in again. Click once more to confirm."));
    show(feedback,true);
    return false;
  }

  function resetRemoval(button, label) {
    delete button.dataset.confirmRemove;
    write(button,label);
  }

  githubPrimary.addEventListener("click", async () => {
    if (state.pending || state.github === "unknown") return;
    if (!state.linked) {
      window.location.assign(githubUrl);
      return;
    }
    const next = state.github === "on" ? "pause" : "resume";
    state.pending = true; updateGithub();
    try {
      await json("/api/connectors/github/"+next,{method:"POST"});
      await readGithub(); // Server truth only.
      updateClaw();
    } catch (_) {
      write(githubFeedback,tr("연결 상태를 바꾸지 못했습니다. 다시 확인해 주세요.",
          "The connection could not be changed. Check its status."));
      show(githubFeedback,true);
      await readGithub();
    } finally {
      state.pending = false; updateGithub();
    }
  });

  githubRemove.addEventListener("click", async () => {
    if (state.pending || !state.linked ||
        !confirmRemoval(githubRemove,githubFeedback,"GitHub")) return;
    state.pending = true; updateGithub();
    try {
      await json("/api/connectors/github/disconnect",{method:"POST"});
      resetRemoval(githubRemove,tr("연결 삭제","Remove connection"));
      await readGithub();
      updateClaw();
    } catch (_) {
      write(githubFeedback,tr("GitHub 연결을 삭제하지 못했습니다.","Could not remove GitHub authorization."));
      show(githubFeedback,true);
      await readGithub();
    } finally {
      state.pending = false; updateGithub();
    }
  });

  driveRemove.addEventListener("click", async () => {
    if (state.drivePending || drive.dataset.connectorStatus !== "connected" ||
        !confirmRemoval(driveRemove,driveFeedback,"Google Drive")) return;
    state.drivePending = true; updateDrive();
    try {
      await json("/api/connectors/google/drive/disconnect",{method:"POST"});
      resetRemoval(driveRemove,tr("연결 삭제","Remove connection"));
      // The canonical workspace GET owns any change to the display.
      document.getElementById("connectorsRetry")?.click();
      updateClaw();
      write(driveFeedback,tr("연결 정보를 삭제했습니다.","Connection removed."));
      show(driveFeedback,true);
    } catch (_) {
      write(driveFeedback,tr("연결을 삭제하지 못했습니다. 상태를 다시 확인해 주세요.",
          "Could not remove the connection. Check its status."));
      show(driveFeedback,true);
    } finally {
      state.drivePending = false; updateDrive();
    }
  });

  new MutationObserver(updateDrive).observe(drive,
    {attributes:true,attributeFilter:["data-connector-status"]});
  dialog.addEventListener("close",()=>{++readGeneration;});
  // All dialog entry routes (sidebar, Claw cards, OAuth return) share this readback.
  new MutationObserver(() => {
    if (dialog.open) {updateDrive(); void readGithub();}
    else ++readGeneration;
  }).observe(dialog,{attributes:true,attributeFilter:["open"]});
  dialog.addEventListener("click",event=>{
    const button=event.target?.closest?.("#connectorsRetry");
    if (button) void readGithub();
  });
  document.getElementById("connectorsNavButton")?.addEventListener("click",
    ()=>{queueMicrotask(()=>{updateDrive();void readGithub();});});
  updateDrive();
  updateGithub();
})();
