// #7812 R5 B4-1 - account section (password reset, password change, account delete).
// Moved out of chat-auth-module.js. No behavior, copy, DOM id, request, body or
// confirm-step change. Shared state and shared DOM stay app.js-owned and are read
// through deps getters/setters. B7: the password reset/change 12 are reached
// through the registry (app.provide("account")); the account-deletion 7 keep
// their one-line forwarders until their registry step. The wire export is named
// wireAccountControls because localPcPanel owns the registry name "wire".
(() => {
  "use strict";
  window.PadiemChatAccountModule = {
    create(deps) {
      // #7812 R5 B4-1: account-only DOM lookups happen here, never at load.
      const accountDeleteOpen = document.getElementById("accountDeleteOpen");
      const accountSharedDeleteOpen = document.getElementById("accountSharedDeleteOpen");
      const accountDeleteConfirmEmail = document.getElementById("accountDeleteConfirmEmail");
      const accountDeleteButton = document.getElementById("accountDeleteButton");
      const accountDeleteError = document.getElementById("accountDeleteError");
      const accountSharedDeleteConfirm = document.getElementById("accountSharedDeleteConfirm");
      const accountSharedDeleteConfirmEmail = document.getElementById("accountSharedDeleteConfirmEmail");
      const accountSharedDeleteButton = document.getElementById("accountSharedDeleteButton");
      const accountSharedDeleteError = document.getElementById("accountSharedDeleteError");
      const passwordChangeOpen = document.getElementById("passwordChangeOpen");
      const passwordChangeDialog = document.getElementById("passwordChangeDialog");
      const passwordChangeDialogClose = document.getElementById("passwordChangeDialogClose");
      const passwordChangeForm = document.getElementById("passwordChangeForm");
      const passwordChangeCurrent = document.getElementById("passwordChangeCurrent");
      const passwordChangeNew = document.getElementById("passwordChangeNew");
      const passwordChangeConfirm = document.getElementById("passwordChangeConfirm");
      const passwordChangeError = document.getElementById("passwordChangeError");
      const passwordChangeSubmit = document.getElementById("passwordChangeSubmit");
      const passwordResetRequestForm = document.getElementById("passwordResetRequestForm");
      const passwordResetRequestSubmit = document.getElementById("passwordResetRequestSubmit");
      const passwordResetConfirmForm = document.getElementById("passwordResetConfirmForm");
      const passwordResetConfirm = document.getElementById("passwordResetConfirm");
      const passwordResetConfirmSubmit = document.getElementById("passwordResetConfirmSubmit");
      const passwordResetBack = document.getElementById("passwordResetBack");
      const passwordResetConfirmBack = document.getElementById("passwordResetConfirmBack");

  function passwordResetTokenFromLocation() {
    try {
      const raw = window.location.hash || "";
      const match = /^#reset=([A-Za-z0-9_-]{16,256})$/.exec(raw);
      return match ? match[1] : "";
    } catch (_) {
      return "";
    }
  }
  function clearPasswordResetFragment() {
    // The one-time token leaves the address bar as soon as the member leaves
    // the reset view, so a shared link never lingers in the browser history
    // of the next person who opens this window.
    try {
      if (!window.location.hash) return;
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
    } catch (_) {}
  }
  function showPasswordResetView(view) {
    deps.authDialogView = view;
    if (deps.passwordResetPanel) deps.passwordResetPanel.hidden = false;
    const emailContinue = deps.passwordLoginContinue;
    if (emailContinue) emailContinue.hidden = view !== "login";
    if (deps.passwordResetRequestView) deps.passwordResetRequestView.hidden = view !== "request";
    if (deps.passwordResetConfirmView) deps.passwordResetConfirmView.hidden = view !== "confirm";
  }
  function hidePasswordResetViews() {
    deps.passwordResetToken = "";
    deps.authDialogView = "login";
    clearPasswordResetFragment();
    if (deps.passwordResetPanel) deps.passwordResetPanel.hidden = true;
    if (deps.passwordResetRequestView) deps.passwordResetRequestView.hidden = true;
    if (deps.passwordResetConfirmView) deps.passwordResetConfirmView.hidden = true;
    if (deps.passwordResetOpen) deps.passwordResetOpen.hidden = !deps.authMethodEnabled("password");
    if (deps.passwordResetEmail) deps.passwordResetEmail.value = "";
    if (deps.passwordResetNew) deps.passwordResetNew.value = "";
    if (passwordResetConfirm) passwordResetConfirm.value = "";
    deps.setAuthFormError(deps.passwordResetRequestError);
    deps.setAuthFormError(deps.passwordResetConfirmError);
    deps.setAuthStatusMessage(deps.passwordResetRequestStatus);
    deps.setAuthStatusMessage(deps.passwordResetConfirmStatus);
  }
  function openPasswordResetRequest() {
    if (!deps.authMethodEnabled("password")) return;
    deps.setAuthFormError(deps.passwordResetRequestError);
    deps.setAuthStatusMessage(deps.passwordResetRequestStatus);
    showPasswordResetView("request");
    deps.passwordResetEmail?.focus();
  }
  function openPasswordResetConfirm(token) {
    if (!deps.authMethodEnabled("password")) return;
    deps.passwordResetToken = typeof token === "string" ? token : "";
    deps.setAuthFormError(deps.passwordResetConfirmError);
    deps.setAuthStatusMessage(deps.passwordResetConfirmStatus);
    showPasswordResetView("confirm");
    deps.passwordResetNew?.focus();
  }
  function closePasswordResetViews() {
    deps.passwordResetToken = "";
    hidePasswordResetViews();
    if (deps.passwordResetEmail) deps.passwordResetEmail.value = "";
    if (deps.passwordResetNew) deps.passwordResetNew.value = "";
    if (passwordResetConfirm) passwordResetConfirm.value = "";
    deps.setAuthFormError(deps.passwordResetRequestError);
    deps.setAuthFormError(deps.passwordResetConfirmError);
    deps.setAuthStatusMessage(deps.passwordResetRequestStatus);
    deps.setAuthStatusMessage(deps.passwordResetConfirmStatus);
  }
  async function submitPasswordResetRequest(event) {
    event.preventDefault();
    if (!deps.authMethodEnabled("password") || !passwordResetRequestForm) return;
    deps.setAuthFormError(deps.passwordResetRequestError);
    deps.setAuthStatusMessage(deps.passwordResetRequestStatus);
    passwordResetRequestSubmit.disabled = true;
    try {
      await deps.passwordAuthRequest("/api/auth/password/reset/request", {
        email: deps.passwordResetEmail.value,
      });
      // The server answers the same way for every address, so the browser
      // shows the same confirmation either way.
      deps.setAuthStatusMessage(deps.passwordResetRequestStatus, deps.uiT("auth-reset-request-sent"));
    } catch (error) {
      deps.setAuthFormError(
        deps.passwordResetRequestError,
        error instanceof Error ? error.message : deps.uiT("auth-error-generic"),
      );
    } finally {
      passwordResetRequestSubmit.disabled = false;
    }
  }
  async function submitPasswordResetConfirm(event) {
    event.preventDefault();
    if (!deps.authMethodEnabled("password") || !passwordResetConfirmForm) return;
    deps.setAuthFormError(deps.passwordResetConfirmError);
    deps.setAuthStatusMessage(deps.passwordResetConfirmStatus);
    const newPassword = deps.passwordResetNew?.value || "";
    const confirmPassword = passwordResetConfirm?.value || "";
    if (!newPassword || !confirmPassword) {
      deps.setAuthFormError(deps.passwordResetConfirmError, deps.uiT("auth-reset-confirm-incomplete"));
      return;
    }
    if (newPassword !== confirmPassword) {
      deps.setAuthFormError(deps.passwordResetConfirmError, deps.uiT("auth-reset-confirm-mismatch"));
      return;
    }
    if (!deps.passwordResetToken) {
      deps.setAuthFormError(deps.passwordResetConfirmError, deps.uiT("auth-reset-expired"));
      return;
    }
    passwordResetConfirmSubmit.disabled = true;
    try {
      await deps.passwordAuthRequest("/api/auth/password/reset/confirm", {
        token: deps.passwordResetToken,
        new_password: newPassword,
      }, { retryUnreachable: true });
      deps.passwordResetToken = "";
      clearPasswordResetFragment();
      if (deps.passwordResetNew) deps.passwordResetNew.value = "";
      if (passwordResetConfirm) passwordResetConfirm.value = "";
      deps.setAuthStatusMessage(deps.passwordResetConfirmStatus, deps.uiT("auth-reset-confirm-done"));
      deps.closeAuthDialog();
      await deps.loadAuthStatus();
    } catch (error) {
      deps.setAuthFormError(
        deps.passwordResetConfirmError,
        error instanceof Error ? error.message : deps.uiT("auth-error-generic"),
      );
    } finally {
      passwordResetConfirmSubmit.disabled = false;
    }
  }
  function openPasswordChangeDialog() {
    if (!passwordChangeDialog) return;
    deps.setAuthFormError(passwordChangeError);
    if (passwordChangeCurrent) passwordChangeCurrent.value = "";
    if (passwordChangeNew) passwordChangeNew.value = "";
    if (passwordChangeConfirm) passwordChangeConfirm.value = "";
    if (typeof passwordChangeDialog.showModal === "function") passwordChangeDialog.showModal();
    else passwordChangeDialog.setAttribute("open", "");
    passwordChangeCurrent?.focus();
  }
  function closePasswordChangeDialog() {
    if (!passwordChangeDialog) return;
    if (passwordChangeDialog.open && typeof passwordChangeDialog.close === "function") passwordChangeDialog.close();
    else passwordChangeDialog.removeAttribute("open");
  }
  // #5434: the signed-in account changes its own password. The account is
  // never named by the browser: the server resolves it from the session.
  async function submitPasswordChange(event) {
    event.preventDefault();
    if (!passwordChangeForm) return;
    deps.setAuthFormError(passwordChangeError);
    const currentPassword = passwordChangeCurrent?.value || "";
    const newPassword = passwordChangeNew?.value || "";
    const confirmPassword = passwordChangeConfirm?.value || "";
    if (!currentPassword || !newPassword) {
      deps.setAuthFormError(passwordChangeError, deps.uiT("password-change-incomplete"));
      return;
    }
    if (newPassword !== confirmPassword) {
      deps.setAuthFormError(passwordChangeError, deps.uiT("password-change-mismatch"));
      return;
    }
    if (newPassword === currentPassword) {
      deps.setAuthFormError(passwordChangeError, deps.uiT("password-change-unchanged"));
      return;
    }
    passwordChangeSubmit.disabled = true;
    try {
      await deps.passwordAuthRequest("/api/auth/password/change", {
        current_password: currentPassword,
        new_password: newPassword,
      });
      // The server ends the session it changed the credential for, so the
      // browser signs in again with the new password.
      if (passwordChangeCurrent) passwordChangeCurrent.value = "";
      if (passwordChangeNew) passwordChangeNew.value = "";
      if (passwordChangeConfirm) passwordChangeConfirm.value = "";
      closePasswordChangeDialog();
      deps.closeSettings();
      await deps.loadAuthStatus();
      if (deps.authDialog && !deps.authDialog.open) deps.openAuthDialog();
      deps.setAuthFormError(deps.passwordLoginError, deps.uiT("password-change-done"));
    } catch (error) {
      deps.setAuthFormError(
        passwordChangeError,
        error instanceof Error ? error.message : deps.uiT("auth-error-generic"),
      );
    } finally {
      passwordChangeSubmit.disabled = false;
    }
  }
  function resetAccountDeleteConfirm() {
    if (accountDeleteConfirmEmail) accountDeleteConfirmEmail.value = "";
    if (accountDeleteButton) accountDeleteButton.disabled = true;
    deps.setAuthFormError(accountDeleteError);
  }
  function resetAccountSharedDeleteConfirm() {
    if (accountSharedDeleteConfirmEmail) accountSharedDeleteConfirmEmail.value = "";
    if (accountSharedDeleteButton) accountSharedDeleteButton.disabled = true;
    deps.setAuthFormError(accountSharedDeleteError);
  }
  function openAccountDeleteConfirm() {
    if (!deps.accountDeleteConfirm) return;
    resetAccountDeleteConfirm();
    resetAccountSharedDeleteConfirm();
    if (accountSharedDeleteConfirm) accountSharedDeleteConfirm.hidden = true;
    deps.accountDeleteConfirm.hidden = false;
    accountDeleteConfirmEmail?.focus();
  }
  function openAccountSharedDeleteConfirm() {
    if (!accountSharedDeleteConfirm) return;
    resetAccountDeleteConfirm();
    resetAccountSharedDeleteConfirm();
    if (deps.accountDeleteConfirm) deps.accountDeleteConfirm.hidden = true;
    accountSharedDeleteConfirm.hidden = false;
    accountSharedDeleteConfirmEmail?.focus();
  }
  function syncAccountDeleteButton() {
    syncDeleteButton(accountDeleteButton, accountDeleteConfirmEmail);
  }
  function syncAccountSharedDeleteButton() {
    syncDeleteButton(accountSharedDeleteButton, accountSharedDeleteConfirmEmail);
  }
  async function submitAccountDelete(deleteAllServices = false) {
    const button = deleteAllServices ? accountSharedDeleteButton : accountDeleteButton;
    const inputElement = deleteAllServices ? accountSharedDeleteConfirmEmail : accountDeleteConfirmEmail;
    const errorElement = deleteAllServices ? accountSharedDeleteError : accountDeleteError;
    if (!button || button.disabled) return;
    deps.setAuthFormError(errorElement);
    const typed = inputElement?.value || "";
    button.disabled = true;
    try {
      const endpoint = deleteAllServices ? "/api/account/shared-delete" : "/api/account/delete";
      const result = await deps.passwordAuthRequest(endpoint, { confirm: typed });
      // #7557: the account is gone, but some stored files or connections may
      // still be erasing in the background. Say so instead of "all done".
      const cleanup = (result && result.cleanup) || null;
      const cleanupPending = Boolean(cleanup && cleanup.complete === false);
      // #7647: a pending shared-login finish is its own retried item and the
      // answer names it, not only the stored files and connections. The
      // pending count includes that one finish item, so a count above one
      // means stored files or connections are pending as well.
      const sharedLoginPending = Boolean(cleanup && cleanup.shared_login_pending === true);
      const cleanupMessageKey = !cleanupPending
        ? (deleteAllServices ? "account-shared-delete-done" : "account-delete-done")
        : (!sharedLoginPending
          ? "account-delete-cleanup-pending"
          : (Number(cleanup.pending) > 1
            ? "account-delete-cleanup-pending-shared-login"
            : "account-delete-cleanup-pending-shared-login-only"));
      resetAccountDeleteConfirm();
      resetAccountSharedDeleteConfirm();
      if (deps.accountDeleteConfirm) deps.accountDeleteConfirm.hidden = true;
      if (accountSharedDeleteConfirm) accountSharedDeleteConfirm.hidden = true;
      // Successful deletion revokes this service session and clears its cookie.
      deps.closeSettings();
      await deps.loadAuthStatus();
      if (deps.authDialog && !deps.authDialog.open) deps.openAuthDialog();
      deps.setAuthFormError(
        deps.passwordLoginError,
        deps.uiT(cleanupMessageKey),
      );
    } catch (error) {
      deps.setAuthFormError(
        errorElement,
        error instanceof Error ? error.message : deps.uiT("auth-error-generic"),
      );
      button.disabled = false;
    }
  }
  function syncDeleteButton(button, inputElement) {
    if (!button) return;
    const typed = inputElement?.value ?? "";
    const email = deps.authState.user && typeof deps.authState.user.email === "string"
      ? deps.authState.user.email : "";
    button.disabled = !email || typed !== email;
  }

      function wire() {
        if (deps.passwordResetOpen) {
          deps.passwordResetOpen.addEventListener("click", openPasswordResetRequest);
        }
        if (passwordResetRequestForm) {
          passwordResetRequestForm.addEventListener("submit", submitPasswordResetRequest);
        }
        if (passwordResetConfirmForm) {
          passwordResetConfirmForm.addEventListener("submit", submitPasswordResetConfirm);
        }
        if (passwordResetBack) {
          passwordResetBack.addEventListener("click", () => {
            hidePasswordResetViews();
            deps.syncAuthDialogMethods();
          });
        }
        if (passwordResetConfirmBack) {
          passwordResetConfirmBack.addEventListener("click", () => {
            hidePasswordResetViews();
            deps.syncAuthDialogMethods();
          });
        }
        if (passwordChangeForm) passwordChangeForm.addEventListener("submit", submitPasswordChange);
        if (passwordChangeOpen) passwordChangeOpen.addEventListener("click", openPasswordChangeDialog);
        if (accountDeleteOpen) accountDeleteOpen.addEventListener("click", openAccountDeleteConfirm);
        if (accountSharedDeleteOpen) {
          accountSharedDeleteOpen.addEventListener("click", openAccountSharedDeleteConfirm);
        }
        if (accountDeleteConfirmEmail) {
          accountDeleteConfirmEmail.addEventListener("input", syncAccountDeleteButton);
        }
        if (accountDeleteButton) {
          accountDeleteButton.addEventListener("click", () => submitAccountDelete(false));
        }
        if (accountSharedDeleteConfirmEmail) {
          accountSharedDeleteConfirmEmail.addEventListener("input", syncAccountSharedDeleteButton);
        }
        if (accountSharedDeleteButton) {
          accountSharedDeleteButton.addEventListener("click", () => submitAccountDelete(true));
        }
        if (passwordChangeDialogClose) passwordChangeDialogClose.addEventListener("click", closePasswordChangeDialog);
        if (passwordChangeDialog) {
          passwordChangeDialog.addEventListener("cancel", (event) => {
            event.preventDefault();
            closePasswordChangeDialog();
          });
        }
      }

      return {
        passwordResetTokenFromLocation,
        clearPasswordResetFragment,
        showPasswordResetView,
        hidePasswordResetViews,
        openPasswordResetRequest,
        openPasswordResetConfirm,
        closePasswordResetViews,
        submitPasswordResetRequest,
        submitPasswordResetConfirm,
        openPasswordChangeDialog,
        closePasswordChangeDialog,
        submitPasswordChange,
        resetAccountDeleteConfirm,
        resetAccountSharedDeleteConfirm,
        openAccountDeleteConfirm,
        openAccountSharedDeleteConfirm,
        syncAccountDeleteButton,
        syncAccountSharedDeleteButton,
        submitAccountDelete,
        syncDeleteButton,
        wireAccountControls: wire,
      };
    },
  };
})();
