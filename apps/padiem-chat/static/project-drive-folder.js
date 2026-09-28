/* Padiem Chat — Project Google Drive case-folder section (#3190).
 *
 * Owner-gated product surface for the private Engine Drive case-folder seam.
 * Contract notes:
 *  - every Drive folder name is external metadata and is rendered with
 *    textContent only (never innerHTML), so a hostile name cannot execute;
 *  - `folder_id` is kept in JS state as selection intent only and is never
 *    shown in the UI;
 *  - stale responses are discarded with per-request sequence tokens (project
 *    status and folder search), so a late response cannot overwrite newer UI;
 *  - `folders: []` (recent-empty / search-empty) is a different state from a
 *    409 drive_not_connected.
 */
(function () {
  "use strict";

  const STATUS_TEXT = {
    loading: "불러오는 중…",
    unconfigured: "사건 폴더가 선택되지 않았습니다.",
    my_drive: "연결됨 · 내 드라이브",
    shared_drive: "연결됨 · 공유 드라이브",
    drive_not_connected: "Google Drive 연결을 확인해 주세요.",
    error: "사건 폴더 상태를 불러오지 못했습니다.",
  };

  const PICKER_TEXT = {
    loading: "폴더를 불러오는 중…",
    recent_empty: "최근 폴더가 없습니다.",
    search_empty: "검색 결과가 없습니다.",
    drive_not_connected: "Google Drive 연결을 확인해 주세요.",
    error: "폴더 목록을 불러오지 못했습니다.",
  };

  function el(id) {
    return document.getElementById(id);
  }

  function driveState() {
    const state = window.__padiemProjectDrive || (window.__padiemProjectDrive = {});
    if (!state.statusToken) state.statusToken = 0;
    if (!state.searchToken) state.searchToken = 0;
    if (!state.folders) state.folders = [];
    if (!state.pickerOpen) state.pickerOpen = false;
    if (!state.configured) state.configured = false;
    return state;
  }

  function fetchJson(path, options) {
    return fetch(path, Object.assign({ headers: { accept: "application/json" } }, options || {}));
  }

  function setStatus(text, busy) {
    const target = el("projectDriveStatus");
    if (target) target.textContent = text;
    const region = el("projectDriveStatusLive");
    if (region) {
      region.setAttribute("aria-busy", busy ? "true" : "false");
      region.textContent = text;
    }
  }

  function setSelectButtonsDisabled(disabled) {
    const list = el("projectDriveFolderList");
    if (!list) return;
    const buttons = list.querySelectorAll("button[data-folder-select]");
    for (let i = 0; i < buttons.length; i += 1) buttons[i].disabled = disabled;
  }

  function applyStatusBody(body) {
    const state = driveState();
    state.configured = Boolean(body && body.configured);
    if (!state.configured) {
      setStatus(STATUS_TEXT.unconfigured, false);
    } else if (body.space_kind === "shared_drive") {
      setStatus(STATUS_TEXT.shared_drive, false);
    } else {
      setStatus(STATUS_TEXT.my_drive, false);
    }
    const clearButton = el("projectDriveClearButton");
    if (clearButton) clearButton.hidden = !state.configured;
    const pickButton = el("projectDrivePickButton");
    if (pickButton) {
      pickButton.textContent = state.configured ? "폴더 변경" : "폴더 선택";
    }
  }

  async function isDriveNotConnected(response) {
    if (!response || response.status !== 409) return false;
    try {
      const body = await response.json();
      return Boolean(body && body.error && body.error.code === "drive_not_connected");
    } catch (error) {
      return false;
    }
  }

  async function loadStatus(projectId) {
    if (!projectId) return;
    const state = driveState();
    state.projectId = projectId;
    state.statusToken += 1;
    const token = state.statusToken;
    setStatus(STATUS_TEXT.loading, true);
    let response;
    try {
      response = await fetchJson("/api/projects/" + encodeURIComponent(projectId) + "/drive-case-folder");
    } catch (error) {
      if (token === state.statusToken) setStatus(STATUS_TEXT.error, false);
      return;
    }
    const disconnected = await isDriveNotConnected(response);
    if (token !== state.statusToken) return; // stale project status response: ignored
    if (disconnected) {
      state.configured = false;
      setStatus(STATUS_TEXT.drive_not_connected, false);
      return;
    }
    if (!response.ok) {
      state.configured = false;
      setStatus(STATUS_TEXT.error, false);
      return;
    }
    let body;
    try {
      body = await response.json();
    } catch (error) {
      if (token === state.statusToken) setStatus(STATUS_TEXT.error, false);
      return;
    }
    if (token !== state.statusToken) return;
    applyStatusBody(body);
  }

  function renderPickerState(text) {
    const empty = el("projectDrivePickerState");
    if (empty) {
      empty.hidden = false;
      empty.textContent = text;
    }
  }

  function hidePickerState() {
    const empty = el("projectDrivePickerState");
    if (empty) empty.hidden = true;
  }

  function renderFolderRows(folders) {
    const list = el("projectDriveFolderList");
    if (!list) return;
    list.textContent = "";
    folders.forEach(function (folder) {
      const row = document.createElement("div");
      row.className = "project-drive-row";

      const label = document.createElement("span");
      label.className = "project-drive-row-name";
      label.textContent = String(folder.name); // external metadata: text only

      const space = document.createElement("span");
      space.className = "project-drive-row-space";
      space.textContent = folder.space_kind === "shared_drive" ? "공유 드라이브" : "내 드라이브";

      const button = document.createElement("button");
      button.type = "button";
      button.className = "project-drive-select";
      button.setAttribute("data-folder-select", folder.folder_id);
      button.textContent = "선택";
      button.addEventListener("click", function () {
        selectFolder(folder.folder_id);
      });

      row.appendChild(label);
      row.appendChild(space);
      row.appendChild(button);
      list.appendChild(row);
    });
  }

  async function loadFolders(query) {
    const state = driveState();
    const projectId = state.projectId;
    if (!projectId) return;
    state.searchToken += 1;
    const token = state.searchToken;
    renderPickerState(PICKER_TEXT.loading);
    const path =
      "/api/projects/" +
      encodeURIComponent(projectId) +
      "/drive-folders" +
      (query ? "?query=" + encodeURIComponent(query) : "");
    let response;
    try {
      response = await fetchJson(path);
    } catch (error) {
      if (token === state.searchToken) renderPickerState(PICKER_TEXT.error);
      return;
    }
    const disconnected = await isDriveNotConnected(response);
    if (token !== state.searchToken) return; // stale search response: ignored
    if (disconnected) {
      renderFolderRows([]);
      renderPickerState(PICKER_TEXT.drive_not_connected);
      return;
    }
    if (!response.ok) {
      renderFolderRows([]);
      renderPickerState(PICKER_TEXT.error);
      return;
    }
    let body;
    try {
      body = await response.json();
    } catch (error) {
      if (token === state.searchToken) renderPickerState(PICKER_TEXT.error);
      return;
    }
    if (token !== state.searchToken) return;
    const folders = Array.isArray(body.folders) ? body.folders : [];
    state.folders = folders;
    renderFolderRows(folders);
    if (folders.length > 0) {
      hidePickerState();
      return;
    }
    renderPickerState(query ? PICKER_TEXT.search_empty : PICKER_TEXT.recent_empty);
  }

  async function selectFolder(folderId) {
    const state = driveState();
    if (!state.projectId || !folderId) return;
    setSelectButtonsDisabled(true);
    try {
      const response = await fetchJson(
        "/api/projects/" + encodeURIComponent(state.projectId) + "/drive-case-folder",
        {
          method: "PUT",
          headers: { "content-type": "application/json", accept: "application/json" },
          body: JSON.stringify({ folder_id: folderId }),
        }
      );
      if (!response.ok) {
        renderPickerState(PICKER_TEXT.error);
        setSelectButtonsDisabled(false);
        return;
      }
    } catch (error) {
      renderPickerState(PICKER_TEXT.error);
      setSelectButtonsDisabled(false);
      return;
    }
    closePicker();
    await loadStatus(state.projectId);
  }

  async function clearFolder() {
    const state = driveState();
    if (!state.projectId) return;
    try {
      const response = await fetchJson(
        "/api/projects/" + encodeURIComponent(state.projectId) + "/drive-case-folder",
        { method: "DELETE" }
      );
      if (!response.ok && response.status !== 404) return;
    } catch (error) {
      return;
    }
    await loadStatus(state.projectId);
  }

  function pickerElement() {
    return el("projectDrivePicker");
  }

  function openPicker() {
    const picker = pickerElement();
    if (!picker) return;
    const state = driveState();
    state.pickerOpen = true;
    state.opener = document.activeElement;
    picker.hidden = false;
    if (typeof picker.showModal === "function") {
      try {
        picker.showModal();
      } catch (error) {
        /* already open */
      }
    }
    const search = el("projectDriveSearchInput");
    if (search) search.focus();
    loadFolders("");
  }

  function closePicker(options) {
    const restoreFocus = !options || options.restoreFocus !== false;
    const picker = pickerElement();
    const state = driveState();
    state.pickerOpen = false;
    if (picker) {
      if (typeof picker.close === "function") {
        try {
          picker.close();
        } catch (error) {
          /* not open */
        }
      }
      picker.hidden = true;
    }
    const opener = state.opener;
    // When the parent Project dialog is closing, the opener may be hidden; only
    // restore focus when the opener is still focusable.
    if (restoreFocus && opener && typeof opener.focus === "function" && !opener.hidden) opener.focus();
  }

  function reset() {
    const state = driveState();
    state.statusToken += 1; // invalidate any in-flight status response
    state.searchToken += 1; // invalidate any in-flight search response
    state.projectId = null;
    state.folders = [];
    state.configured = false;
    state.opener = null;
    closePicker({ restoreFocus: false });
    renderFolderRows([]);
    hidePickerState();
    setStatus(STATUS_TEXT.unconfigured, false);
    const clearButton = el("projectDriveClearButton");
    if (clearButton) clearButton.hidden = true;
    const pickButton = el("projectDrivePickButton");
    if (pickButton) pickButton.textContent = "폴더 선택";
  }

  function wire() {
    const pickButton = el("projectDrivePickButton");
    if (pickButton) pickButton.addEventListener("click", openPicker);
    const clearButton = el("projectDriveClearButton");
    if (clearButton) clearButton.addEventListener("click", clearFolder);
    const closeButton = el("projectDrivePickerClose");
    if (closeButton) closeButton.addEventListener("click", closePicker);
    const search = el("projectDriveSearchInput");
    if (search) {
      search.addEventListener("keydown", function (event) {
        if (event.key === "Enter") {
          event.preventDefault();
          loadFolders(search.value.trim());
        }
      });
      search.addEventListener("change", function () {
        loadFolders(search.value.trim());
      });
    }
    const picker = pickerElement();
    if (picker) {
      picker.addEventListener("keydown", function (event) {
        if (event.key === "Escape") {
          event.preventDefault();
          closePicker();
        }
      });
      picker.addEventListener("cancel", function (event) {
        event.preventDefault();
        closePicker();
      });
    }
  }

  window.padiemProjectDriveFolder = {
    loadStatus: loadStatus,
    loadFolders: loadFolders,
    openPicker: openPicker,
    closePicker: closePicker,
    selectFolder: selectFolder,
    clearFolder: clearFolder,
    reset: reset,
    state: driveState,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }
})();
