// #7216 R5 A7 — Core helper module: UI / Claw locale text lookup, note
// presentation, error mapping, document / image readers and time / byte formatters.
// Moved verbatim from app.js; dependencies are reached through deps.
(() => {
  "use strict";

  window.PadiemChatCoreModule = {
    create(deps) {
      function uiT(key, variables = null) {
        try {
          if (window.__padiemLocale && typeof window.__padiemLocale.text === "function") {
            const value = window.__padiemLocale.text(key, variables);
            if (value && value !== key) return value;
          }
        } catch (_) {}
        return key;
      }

      function idleNote() {
        return deps.activeProject ? uiT("active-project-note", { name: deps.activeProject.name }) : deps.attachmentCopy().idleNote;
      }

      function setNote(text, state = "normal") {
        deps.runtimeNote.textContent = text;
        deps.runtimeNote.dataset.state = state;
      }

      // #6126: the one legacy-HWP answer the screens show — an ordinary save-as
      // instruction plus the three HWPX steps, never an error state.
      function hwpLegacyGuidance() {
        return uiT("hwp-legacy-guidance") + "\n" + uiT("hwp-legacy-steps");
      }

      function formatClockTime(value) {
        const date = value instanceof Date && !Number.isNaN(value.getTime()) ? value : new Date();
        return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
      }

      function formatBytes(bytes) {
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
      }

      function extensionOf(name) {
        const lower = String(name || "").toLowerCase();
        const index = lower.lastIndexOf(".");
        return index >= 0 ? lower.slice(index) : "";
      }

      function documentMediaType(file) {
        if (deps.ALLOWED_DOCUMENT_TYPES.has(file.type)) return file.type;
        return deps.DOCUMENT_EXTENSION_TYPES.get(extensionOf(file.name)) || null;
      }

      function readAsText(file) {
        return new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.addEventListener("load", () => resolve(reader.result), { once: true });
          reader.addEventListener("error", () => reject(new Error(uiT("document-read-failed"))), { once: true });
          reader.readAsText(file, "UTF-8");
        });
      }

      async function readDocumentFile(file) {
        if (extensionOf(file.name) === ".hwp") {
          // #6126 backstop: selection-time callers refuse an OLE2 .hwp by its own
          // bytes before reaching here; this guard keeps the same one code and
          // wording for any future caller that skips the sniff.
          const error = new Error(uiT("hwp-legacy-guidance"));
          error.uiMessageSafe = true;
          error.code = "legacy_hwp_unsupported";
          throw error;
        }
        const mediaType = documentMediaType(file);
        if (!mediaType) throw new Error(deps.attachmentCopy().unsupportedFormat);
        if (file.size < 1) throw new Error(uiT("empty-document"));
        const raw = await readAsText(file);
        if (typeof raw !== "string") throw new Error(uiT("document-read-failed"));
        const text = raw.replace(/^\uFEFF/, "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
        if (!text.trim()) throw new Error(uiT("empty-document"));
        if (text.includes("\u0000")) throw new Error(uiT("binary-document"));
        return { type: "document", name: file.name || "document.txt", mediaType, text, byteSize: file.size };
      }

      async function selectImage(file) {
        if (!deps.ALLOWED_IMAGE_TYPES.has(file.type)) throw new Error(deps.attachmentCopy().unsupportedFormat);
        if (file.size < 1) throw new Error(uiT("image-data-empty"));
        return { type: "image", name: file.name || "image", mediaType: file.type, file, byteSize: file.size, previewUrl: URL.createObjectURL(file) };
      }

      function mappedUiError(message, data) {
        const error = new Error(message);
        error.uiMessageSafe = true;
        const code = data?.error?.code;
        if (typeof code === "string" && /^[a-z][a-z0-9_]{0,63}$/.test(code)) error.code = code;
        return error;
      }

      function clawT(key, variables = null) {
        try {
          if (window.__padiemLocale && typeof window.__padiemLocale.text === "function") {
            const v = window.__padiemLocale.text(key, variables);
            if (v && v !== key) return v;
          }
        } catch (_) {}
        if (!variables || typeof variables !== "object") return deps.clawFallbackCopy[key] || "Unable to update this Claw status. Please try again.";
        const template = deps.clawFallbackCopy[key] || "Unable to update this Claw status. Please try again.";
        return Object.keys(variables).reduce((out, name) => out.split(`{${name}}`).join(String(variables[name])), template);
      }

      function localeOr(key, fallback) {
        try {
          if (window.__padiemLocale && typeof window.__padiemLocale.text === "function") {
            const value = window.__padiemLocale.text(key);
            if (value && value !== key) return value;
          }
        } catch (_) {}
        return fallback;
      }

      return {
        uiT,
        idleNote,
        setNote,
        hwpLegacyGuidance,
        formatClockTime,
        formatBytes,
        extensionOf,
        documentMediaType,
        readAsText,
        readDocumentFile,
        selectImage,
        mappedUiError,
        clawT,
        localeOr,
      };
    },
  };
})();
