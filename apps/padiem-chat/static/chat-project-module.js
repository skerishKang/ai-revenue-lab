(() => {
  "use strict";
  const factory = {
    create(deps) {
      const projectsNavButton = document.getElementById("projectsNavButton");
      const projectsBadge = document.getElementById("projectsBadge");
      const projectsSection = document.getElementById("projectsSection");
      const projectsList = document.getElementById("projectsList");
      const projectsEmpty = document.getElementById("projectsEmpty");
      const projectCreateButton = document.getElementById("projectCreateButton");
      const projectBanner = document.getElementById("projectBanner");
      const activeProjectName = document.getElementById("activeProjectName");
      const activeProjectFiles = document.getElementById("activeProjectFiles");
      const editProjectButton = document.getElementById("editProjectButton");
      const exitProjectButton = document.getElementById("exitProjectButton");
      const projectDialog = document.getElementById("projectDialog");
      const projectForm = document.getElementById("projectForm");
      const projectDialogTitle = document.getElementById("projectDialogTitle");
      const projectDialogClose = document.getElementById("projectDialogClose");
      const projectDialogCancel = document.getElementById("projectDialogCancel");
      const projectNameInput = document.getElementById("projectNameInput");
      const projectInstructionsInput = document.getElementById("projectInstructionsInput");
      const projectFormError = document.getElementById("projectFormError");
      const projectSaveButton = document.getElementById("projectSaveButton");
      const projectFormActions = projectForm.querySelector(".project-form-actions");
      const projectDeleteButton = document.createElement("button");
      projectDeleteButton.id = "projectDeleteButton";
      projectDeleteButton.type = "button";
      projectDeleteButton.className = "project-danger";
      projectDeleteButton.hidden = true;
      const projectFilesPanel = document.getElementById("projectFilesPanel");
      const projectFileInput = document.getElementById("projectFileInput");
      const projectFilesList = document.getElementById("projectFilesList");
      const projectFilesUsage = document.getElementById("projectFilesUsage");
      const projectFilesEmpty = document.getElementById("projectFilesEmpty");
      const projectFileStatus = document.getElementById("projectFileStatus");
      const drivePanel = document.getElementById("projectDrivePanel");

      const PROJECT_BINARY_EXTENSION_MEDIA = new Map([
        [".pdf", "application/pdf"],
        [".hwpx", "application/hwp+zip"],
        [".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
      ]);

      let projects = [];
      // #5882: next-page cursor from the server. When present a "load more" button is
      // appended; on the last page there is none, so the list no longer stops silently at 50.
      let projectsNextCursor = null;
      let projectsLoadingMore = false;
      let editingProjectId = null;
      let dialogProjectFiles = [];
      let highlightedProjectFileId = null;
      let projectFileBusy = false;

      // #4489: the Library entry is owned by static/library.js. The old
      // filesNavAvailable()/syncFilesNav() gate that also required project-file
      // storage was removed, because Library navigation must work for a signed-in
      // owner even when that storage is not provisioned.
      function clearProjectsUI() {
        projects = [];
        deps.projectsReady = false;
        deps.activeProject = null;
        deps.activeProjectFileCount = 0;
        projectsList.replaceChildren();
        // #7365: the materials group (projects and recent conversations) stays
        // visible even with nothing in it — the section heading and the
        // empty-state note are the honest empty answer (a guest sees the same
        // group a signed-in account sees).
        projectsSection.hidden = false;
        projectsEmpty.hidden = false;
        setProjectsListNote("");
        if (projectsNavButton) {
          projectsNavButton.disabled = true;
          projectsNavButton.setAttribute("aria-disabled", "true");
        }
        if (projectsBadge) projectsBadge.textContent = deps.authState.authenticated ? deps.uiT("setup-needed") : deps.uiT("login-after");
        renderProjectState();
      }
      function renderProjectState() {
        projectBanner.hidden = !deps.activeProject;
        activeProjectName.textContent = deps.activeProject ? deps.activeProject.name : "";
        activeProjectFiles.hidden = !deps.activeProject || deps.activeProjectFileCount < 1;
        activeProjectFiles.textContent = deps.activeProjectFileCount > 0 ? deps.uiT("project-files-count", { count: deps.activeProjectFileCount }) : "";
        projectsList.querySelectorAll(".project-item").forEach((button) => {
          button.setAttribute("aria-current", deps.activeProject && button.dataset.projectId === deps.activeProject.id ? "true" : "false");
        });
        if (!deps.selectedAttachments.length) deps.setNote(deps.idleNote());
      }
      // Static, accessible sidebar actions: keep the translated button text
      // and ARIA labels; only replace the low-contrast visual affordance.
      // R5 B7: the icon renderer lives in the sidebar module (registry-provided).
      function renderProjects() {
        projectsList.replaceChildren();
        projectsSection.hidden = !deps.projectsReady;
        projectsEmpty.hidden = !deps.projectsReady || projects.length !== 0;
        projects.forEach((project) => {
          const row = document.createElement("div");
          row.className = "project-row";
          const button = document.createElement("button");
          button.type = "button";
          button.className = "recent-item project-item";
          button.dataset.projectId = project.id;
          button.textContent = project.name;
          button.setAttribute("aria-current", deps.activeProject && deps.activeProject.id === project.id ? "true" : "false");
          button.addEventListener("click", () => selectProject(project));
          const manage = document.createElement("button");
          manage.type = "button";
          manage.className = "project-manage";
          manage.textContent = deps.uiT("manage");
          manage.prepend(deps.sidebarActionIcon("settings"));
          manage.setAttribute("aria-label", deps.uiT("project-manage-aria", { name: project.name }));
          window.PadiemSharedTooltip?.label?.(manage, deps.uiT("project-manage-aria", { name: project.name }));
          manage.addEventListener("click", () => openProjectDialog(project));
          row.append(button, manage);
          projectsList.appendChild(row);
        });
        if (projectsNextCursor && deps.projectsReady) {
          const moreRow = document.createElement("div");
          moreRow.className = "project-row project-more-row";
          const more = document.createElement("button");
          more.type = "button";
          more.className = "recent-item project-more";
          more.id = "projectsMore";
          more.textContent = deps.uiT("projects-more");
          more.setAttribute("aria-label", deps.uiT("projects-more-aria"));
          more.disabled = projectsLoadingMore;
          more.addEventListener("click", () => { void loadMoreProjects(); });
          moreRow.appendChild(more);
          projectsList.appendChild(moreRow);
        }
        if (projectsBadge) projectsBadge.textContent = projects.length ? String(projects.length) : deps.uiT("create-new");
      }
      // #6645: a stale cursor used to report through the composer note, which the
      // glass desktop frame hides (display: none). The notice belongs next to the
      // list it is about, so it is always painted.
      function setProjectsListNote(text) {
        const note = document.getElementById("projectsListNote");
        if (!note) return;
        const copy = typeof text === "string" ? text : "";
        note.textContent = copy;
        note.hidden = !copy;
      }
      async function loadMoreProjects() {
        if (!projectsNextCursor || projectsLoadingMore || !deps.authState.authenticated) return false;
        const epoch = deps.authViewEpoch;
        const cursor = projectsNextCursor;
        projectsLoadingMore = true;
        renderProjects();
        try {
          const response = await deps.fetch(
            `/api/projects?cursor=${encodeURIComponent(cursor)}`,
            { headers: { "Accept": "application/json" }, cache: "no-store" },
          );
          const data = await response.json().catch(() => null);
          if (epoch !== deps.authViewEpoch || !deps.authState.authenticated || !response.ok || !data || !Array.isArray(data.projects)) {
            // A cursor this server no longer accepts is answered 400. Refuse to loop:
            // drop it and show what is already on screen with a plain Korean notice.
            if (response.status === 400) {
              projectsNextCursor = null;
              setProjectsListNote(deps.uiT("projects-more-stale"));
            }
            return false;
          }
          const seen = new Set(projects.map((item) => item.id));
          const fresh = data.projects.filter((item) => item && typeof item.id === "string"
            && typeof item.name === "string" && !seen.has(item.id));
          projects = projects.concat(fresh);
          projectsNextCursor = typeof data.next_cursor === "string" && data.next_cursor ? data.next_cursor : null;
          setProjectsListNote("");
          return true;
        } catch (_) {
          return false;
        } finally {
          projectsLoadingMore = false;
          if (epoch === deps.authViewEpoch) renderProjects();
        }
      }
      async function loadProjects() {
        if (!deps.authState.authenticated || !deps.authState.history_ready) {
          clearProjectsUI();
          return false;
        }
        const epoch = deps.authViewEpoch;
        if (projectsNavButton) {
          projectsNavButton.disabled = true;
          projectsNavButton.setAttribute("aria-disabled", "true");
        }
        if (projectsBadge) projectsBadge.textContent = deps.uiT("checking");
        try {
          const response = await deps.fetch("/api/projects", { headers: { "Accept": "application/json" }, cache: "no-store" });
          const data = await response.json().catch(() => null);
          if (epoch !== deps.authViewEpoch || !deps.authState.authenticated) return false;
          if (!response.ok || !data || !Array.isArray(data.projects)) throw new Error("projects unavailable");
          projects = data.projects.filter((item) => item && typeof item.id === "string" && typeof item.name === "string");
          projectsNextCursor = typeof data.next_cursor === "string" && data.next_cursor ? data.next_cursor : null;
          deps.projectsReady = true;
          if (projectsNavButton) {
            projectsNavButton.disabled = false;
            projectsNavButton.setAttribute("aria-disabled", "false");
          }
          if (deps.activeProject) deps.activeProject = projects.find((item) => item.id === deps.activeProject.id) || deps.activeProject;
          renderProjects();
          return true;
        } catch (_) {
          if (epoch !== deps.authViewEpoch || !deps.authState.authenticated) return false;
          clearProjectsUI();
          return false;
        }
      }
      function projectById(id) {
        return projects.find((project) => project.id === id) || null;
      }
      async function ensureProject(id) {
        if (!id) return null;
        const known = projectById(id);
        if (known) return known;
        if (!deps.authState.authenticated || !deps.projectsReady) return null;
        const requestAuth = deps.authState;
        try {
          const response = await deps.fetch(`/api/projects/${encodeURIComponent(id)}`, { headers: { "Accept": "application/json" }, cache: "no-store" });
          const data = await response.json().catch(() => null);
          if (deps.authState !== requestAuth || !deps.authState.authenticated || !response.ok || !data || !data.project || typeof data.project.id !== "string") return null;
          projects.unshift(data.project);
          renderProjects();
          return data.project;
        } catch (_) {
          return null;
        }
      }

      // Only messages constructed by our own mapping may be shown to the user.
      function showProjectError(error, fallback) {
        projectFormError.textContent = deps.safeLocalUiMessage(error, fallback);
        const note = deps.failureCodeNote(error?.code, "");
        if (note) projectFormError.appendChild(note);
        projectFormError.hidden = false;
      }

      async function fetchProjectFiles(projectId) {
        if (!deps.authState.authenticated || !deps.authState.project_files_ready || !projectId) return [];
        const response = await deps.fetch(`/api/projects/${encodeURIComponent(projectId)}/files`, { headers: { "Accept": "application/json" }, cache: "no-store" });
        const data = await response.json().catch(() => null);
        if (!response.ok || !data || !Array.isArray(data.files)) throw deps.mappedUiError(deps.uiT("project-files-load-failed"), data);
        return data.files.filter((item) => item && typeof item.id === "string" && typeof item.name === "string");
      }
      async function refreshActiveProjectFileCount() {
        if (!deps.activeProject || !deps.authState.project_files_ready) {
          deps.activeProjectFileCount = 0;
          renderProjectState();
          return;
        }
        try {
          const files = await fetchProjectFiles(deps.activeProject.id);
          deps.activeProjectFileCount = files.length;
        } catch (_) {
          deps.activeProjectFileCount = 0;
        }
        renderProjectState();
      }
      function renderProjectFiles() {
        projectFilesList.replaceChildren();
        const totalChars = dialogProjectFiles.reduce((sum, file) => sum + Number(file.content_chars || 0), 0);
        if (projectFilesUsage) {
          projectFilesUsage.textContent = deps.uiT("project-files-usage", {
            count: dialogProjectFiles.length,
            chars: totalChars.toLocaleString(),
          });
          projectFilesUsage.hidden = false;
        }
        projectFilesEmpty.hidden = dialogProjectFiles.length !== 0;
        dialogProjectFiles.forEach((file) => {
          const row = document.createElement("div");
          row.className = "project-file-row";
          if (file.id === highlightedProjectFileId) {
            row.classList.add("quick-selected-file");
            row.tabIndex = -1;
            requestAnimationFrame(() => {
              if (projectDialog.open && editingProjectId && row.isConnected) {
                row.scrollIntoView({ block: "nearest" });
                row.focus({ preventScroll: true });
              }
            });
          }
          const copy = document.createElement("div");
          const strong = document.createElement("strong");
          strong.textContent = file.name;
          const small = document.createElement("small");
          small.textContent = `${file.media_type} · ${deps.uiT("character-count", { count: Number(file.content_chars || 0).toLocaleString() })}`;
          copy.append(strong, small);
          const remove = document.createElement("button");
          remove.type = "button";
          remove.textContent = deps.uiT("delete");
          remove.addEventListener("click", () => deleteProjectFile(file.id, file.name));
          row.append(copy, remove);
          projectFilesList.appendChild(row);
        });
      }
      async function loadProjectFilesForDialog(projectId) {
        if (!projectId || !deps.authState.project_files_ready) {
          dialogProjectFiles = [];
          renderProjectFiles();
          return;
        }
        try {
          const files = await fetchProjectFiles(projectId);
          if (!projectDialog.open || editingProjectId !== projectId) return;
          dialogProjectFiles = files;
          renderProjectFiles();
          if (deps.activeProject && deps.activeProject.id === projectId) {
            deps.activeProjectFileCount = dialogProjectFiles.length;
            renderProjectState();
          }
        } catch (error) {
          showProjectError(error, deps.uiT("project-files-load-failed"));
        }
      }
      function projectBinaryMediaType(file) {
        // Project-scoped subset preflight: PDF/DOCX only (the server allow-lists exactly these two
        // binaries). Extension-driven to mirror document-binary.js canRead/canonicalMediaType, which
        // are themselves extension-canonical. Everything else — PPTX/XLSX and unsupported text types —
        // falls through to the text path and is rejected there BEFORE any request is made.
        return PROJECT_BINARY_EXTENSION_MEDIA.get(deps.extensionOf(file && file.name)) || null;
      }
      function setProjectFileBusy(busy) {
        projectFileBusy = busy;
        if (busy) {
          projectFilesPanel.setAttribute("aria-busy", "true");
          projectFileInput.setAttribute("aria-disabled", "true");
          if (projectFileStatus) { projectFileStatus.textContent = deps.uiT("document-saving"); projectFileStatus.hidden = false; }
        } else {
          projectFilesPanel.removeAttribute("aria-busy");
          projectFileInput.removeAttribute("aria-disabled");
          if (projectFileStatus) { projectFileStatus.hidden = true; projectFileStatus.textContent = ""; }
        }
      }
      async function addProjectFile(file) {
        if (!file || !editingProjectId || !deps.authState.project_files_ready) return;
        projectFileInput.value = "";
        if (projectFileBusy) return;
        // Clear any stale error so a successful retry never leaves the old message up.
        projectFormError.hidden = true;
        projectFormError.textContent = "";
        // #6126: a project .hwp is judged by its own bytes. The older OLE2 binary
        // Hangul format is never converted — the panel answers with the ordinary
        // save-as-HWPX guidance as a status note (not the error row) — and a
        // mislabeled file whose bytes are a real HWPX (ZIP) package keeps working
        // as HWPX through the same binary upload the .hwpx extension uses.
        const hwpFamily = deps.extensionOf(file.name) === ".hwp"
          ? (await deps.binaryDocuments?.headerFamily?.(file)) || null
          : null;
        if (hwpFamily === "ole") {
          if (projectFileStatus) {
            projectFileStatus.textContent = deps.hwpLegacyGuidance();
            projectFileStatus.hidden = false;
          }
          return;
        }
        setProjectFileBusy(true);
        try {
          let projectBinary = projectBinaryMediaType(file);
          if (!projectBinary && hwpFamily === "zip" && deps.binaryDocuments?.hwpxMedia) {
            projectBinary = deps.binaryDocuments.hwpxMedia;
          }
          if (projectBinary) {
            // #6579: every binary goes through the shared tus module, which owns the
            // progress line, the resume policy and the first-party guidance copy.
            if (!window.PadiemProjectFileUpload) throw deps.mappedUiError(deps.uiT("project-file-save-failed"), null);
            const uploaded = await window.PadiemProjectFileUpload.upload({
              file,
              projectId: editingProjectId,
              mediaType: projectBinary,
              onProgress: (sent, total) => {
                if (projectFileStatus && !projectFileStatus.hidden && total > 0) {
                  const percent = Math.min(100, Math.round((sent / total) * 100));
                  projectFileStatus.textContent = `${deps.uiT("document-saving")} ${percent}%`;
                }
              },
            });
            if (!uploaded || !uploaded.file) throw deps.mappedUiError(deps.uiT("project-file-save-failed"), null);
          } else {
            const documentFile = await deps.readDocumentFile(file);
            const payload = { name: documentFile.name, media_type: documentFile.mediaType, text: documentFile.text };
            const response = await deps.fetch(`/api/projects/${encodeURIComponent(editingProjectId)}/files`, {
              method: "POST", headers: { "Content-Type": "application/json", "Accept": "application/json" },
              body: JSON.stringify(payload),
            });
            const data = await response.json().catch(() => null);
            if (!response.ok || !data || !data.file) {
              throw deps.mappedUiError(deps.uiT("project-file-save-failed"), data);
            }
          }
          await loadProjectFilesForDialog(editingProjectId);
        } catch (error) {
          showProjectError(error, deps.uiT("project-file-save-failed"));
        } finally {
          setProjectFileBusy(false);
        }
      }
      async function deleteProjectFile(fileId, name) {
        if (!editingProjectId || !deps.authState.project_files_ready) return;
        const confirmed = await window.PadiemConfirmDialog.confirm({
          title: deps.uiT("project-file-delete-title"),
          message: deps.uiT("project-file-delete-message", { name }),
          cancelLabel: deps.uiT("cancel"),
          confirmLabel: deps.uiT("delete"),
        });
        if (!confirmed) return;
        try {
          const response = await deps.fetch(`/api/projects/${encodeURIComponent(editingProjectId)}/files/${encodeURIComponent(fileId)}`, { method: "DELETE" });
          if (!response.ok) throw deps.mappedUiError(deps.uiT("project-file-delete-failed"), await response.json().catch(() => null));
          await loadProjectFilesForDialog(editingProjectId);
        } catch (error) {
          showProjectError(error, deps.uiT("project-file-delete-failed"));
        }
      }

      // #2505: the sidebar Chat entry returns to the Chat lane while the user is in
      // the Claw workspace. Inside the Chat state the same entry starts a new
      // conversation. Every other caller resets the view directly, because a
      // sign-out, a project change or a delete must clear the conversation no
      // matter which product is on screen.
      function selectProject(project) {
        if (!deps.projectsReady || !project || deps.inFlight) return;
        deps.activeProject = project;
        deps.activeProjectFileCount = 0;
        deps.resetConversationView(true);
        refreshActiveProjectFileCount();
      }
      function exitProject() {
        if (deps.inFlight) return;
        deps.activeProject = null;
        deps.activeProjectFileCount = 0;
        deps.resetConversationView(false);
      }
      function openProjectDialog(project = null, selectedFileId = null) {
        if (!deps.projectsReady || !deps.authState.authenticated || deps.inFlight) return;
        editingProjectId = project ? project.id : null;
        highlightedProjectFileId = selectedFileId;
        projectDialogTitle.textContent = project ? deps.uiT("project-edit-title") : deps.uiT("project-new");
        projectNameInput.value = project ? project.name : "";
        projectInstructionsInput.value = project && typeof project.instructions === "string" ? project.instructions : "";
        projectFormError.textContent = "";
        projectFormError.hidden = true;
        projectSaveButton.disabled = false;
        projectDeleteButton.hidden = !project;
        projectDeleteButton.disabled = false;
        projectFilesPanel.hidden = !(project && deps.authState.project_files_ready);
        dialogProjectFiles = [];
        renderProjectFiles();
        projectDialog.showModal();
        // #3190: an existing project loads its Drive case-folder status; a brand new
        // project has no project_id yet, so the Drive section stays hidden.
        if (window.padiemProjectDriveFolder) {
          window.padiemProjectDriveFolder.reset();
          if (project && project.id) {
            if (drivePanel) drivePanel.hidden = false;
            window.padiemProjectDriveFolder.loadStatus(project.id);
          } else if (drivePanel) {
            drivePanel.hidden = true;
          }
        }
        if (project && deps.authState.project_files_ready) loadProjectFilesForDialog(project.id);
        projectNameInput.focus();
      }
      function closeProjectDialog() {
        if (window.padiemProjectDriveFolder) window.padiemProjectDriveFolder.reset();
        if (projectDialog.open && typeof projectDialog.close === "function") projectDialog.close();
        editingProjectId = null;
        dialogProjectFiles = [];
        projectFileInput.value = "";
        projectFormError.textContent = "";
        projectFormError.hidden = true;
      }
      async function saveProject(event) {
        event.preventDefault();
        if (!deps.projectsReady || !deps.authState.authenticated) return;
        const name = projectNameInput.value.trim();
        const instructions = projectInstructionsInput.value.trim();
        if (!name) {
          projectFormError.textContent = deps.uiT("project-name-required");
          projectFormError.hidden = false;
          return;
        }
        projectSaveButton.disabled = true;
        projectFormError.hidden = true;
        try {
          const editing = Boolean(editingProjectId);
          const url = editing ? `/api/projects/${encodeURIComponent(editingProjectId)}` : "/api/projects";
          const response = await deps.fetch(url, {
            method: editing ? "PATCH" : "POST",
            headers: { "Content-Type": "application/json", "Accept": "application/json" },
            body: JSON.stringify({ name, instructions }),
          });
          const data = await response.json().catch(() => null);
          if (!response.ok || !data || !data.project) {
            throw deps.mappedUiError(deps.uiT("project-save-failed"), data);
          }
          const saved = data.project;
          const index = projects.findIndex((item) => item.id === saved.id);
          if (index >= 0) projects[index] = saved; else projects.unshift(saved);
          if (deps.activeProject && deps.activeProject.id === saved.id) deps.activeProject = saved;
          renderProjects();
          renderProjectState();
          closeProjectDialog();
          if (!editing) selectProject(saved);
        } catch (error) {
          showProjectError(error, deps.uiT("project-save-failed"));
          projectSaveButton.disabled = false;
        }
      }

      async function deleteProject() {
        if (!editingProjectId || !deps.projectsReady || !deps.authState.authenticated || deps.inFlight) return;
        const project = projectById(editingProjectId);
        if (!project) return;
        const confirmed = await window.PadiemConfirmDialog.confirm({
          title: deps.uiT("project-delete-title"),
          message: deps.uiT("project-delete-message", { name: project.name }),
          cancelLabel: deps.uiT("cancel"),
          confirmLabel: deps.uiT("delete"),
        });
        if (!confirmed) return;
        const deletingId = editingProjectId;
        const deletingActiveProject = Boolean(deps.activeProject && deps.activeProject.id === deletingId);
        projectDeleteButton.disabled = true;
        projectSaveButton.disabled = true;
        projectFormError.hidden = true;
        try {
          const response = await deps.fetch(`/api/projects/${encodeURIComponent(deletingId)}`, {
            method: "DELETE",
            headers: { "Accept": "application/json" },
            cache: "no-store",
          });
          const data = await response.json().catch(() => null);
          if (!response.ok || !data || data.deleted !== true || data.project_id !== deletingId) {
            throw deps.mappedUiError(deps.uiT("project-delete-failed"), data);
          }
          projects = projects.filter((item) => item.id !== deletingId);
          if (deletingActiveProject) {
            deps.activeProject = null;
            deps.activeProjectFileCount = 0;
          }
          renderProjects();
          renderProjectState();
          closeProjectDialog();
          await loadProjects();
          if (deletingActiveProject) {
            renderProjectState();
            deps.setNote(deps.idleNote());
          }
          deps.input.focus();
        } catch (error) {
          showProjectError(error, deps.uiT("project-delete-failed"));
          projectDeleteButton.disabled = false;
          projectSaveButton.disabled = false;
        }
      }

      function mountProjectControls() {
        projectDeleteButton.textContent = deps.uiT("project-delete");
        projectDeleteButton.setAttribute("aria-label", deps.uiT("project-delete-aria"));
        projectFormActions.prepend(projectDeleteButton);
      }

      function wireProjectListeners() {
        if (projectsNavButton) projectsNavButton.addEventListener("click", () => {
          if (!deps.projectsReady) return;
          if (projects.length === 0) openProjectDialog();
          else projectsSection.scrollIntoView({ block: "nearest", behavior: "smooth" });
        });
        projectCreateButton.addEventListener("click", () => openProjectDialog());
        editProjectButton.addEventListener("click", () => { if (deps.activeProject) openProjectDialog(deps.activeProject); });
        exitProjectButton.addEventListener("click", exitProject);
        projectDialogClose.addEventListener("click", closeProjectDialog);
        projectDialogCancel.addEventListener("click", closeProjectDialog);
        projectForm.addEventListener("submit", saveProject);
        projectDeleteButton.addEventListener("click", deleteProject);
        projectFileInput.addEventListener("change", () => {
          const [file] = projectFileInput.files || [];
          addProjectFile(file);
        });
        projectDialog.addEventListener("cancel", (event) => {
          event.preventDefault();
          closeProjectDialog();
        });
      }

      // #4489: the Library opens a stored project file through that file's owning
      // project in the existing Project dialog, so project-file permission, the
      // files panel and every edit guard stay on the one canonical path. The project
      // resolves from the owner list or its existing authenticated project lookup;
      // a foreign or stale id opens nothing. This handle grants no new authority.
      async function openFile(projectId, fileId) {
        if (!deps.projectsReady || !deps.authState.authenticated || deps.inFlight) return false;
        const requestAuth = deps.authState;
        const project = await ensureProject(projectId);
        if (!project || deps.authState !== requestAuth || !deps.authState.authenticated || deps.inFlight) return false;
        openProjectDialog(project, fileId);
        return true;
      }
      function open(projectId) {
        if (!deps.projectsReady || !deps.authState.authenticated || deps.inFlight) return false;
        const project = projects.find((item) => item && item.id === projectId);
        if (!project) return false;
        openProjectDialog(project);
        return true;
      }

      return {
        projectsBadge,
        projectFileStatus,
        editProjectButton,
        exitProjectButton,
        clearProjectsUI,
        renderProjectState,
        renderProjects,
        setProjectsListNote,
        loadMoreProjects,
        loadProjects,
        projectById,
        ensureProject,
        showProjectError,
        fetchProjectFiles,
        refreshActiveProjectFileCount,
        renderProjectFiles,
        loadProjectFilesForDialog,
        projectBinaryMediaType,
        setProjectFileBusy,
        addProjectFile,
        deleteProjectFile,
        selectProject,
        exitProject,
        openProjectDialog,
        closeProjectDialog,
        saveProject,
        deleteProject,
        mountProjectControls,
        wireProjectListeners,
        openFile,
        open,
      };
    },
  };
  Object.defineProperty(window, "PadiemChatProjectModule", {
    value: factory,
    writable: true,
    configurable: true,
  });
})();
