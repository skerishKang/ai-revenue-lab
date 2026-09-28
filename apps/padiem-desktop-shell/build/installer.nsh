; #3093 (reopen) — install-time `padiem://` registration for the packaged app.
;
; Measured packaged failure (CLAW3 real-Windows evidence, exact main
; 6fffd5a0): the silent per-user NSIS install did not register `padiem://` in
; HKCU, so a browser handoff after a fresh install had no OS handler at all
; (and on this machine a stale dev-host registration from an unrelated
; checkout was left in place, pointing the scheme at a temp directory).
;
; The runtime half (#3093 protocol-registration.ts) still re-registers for the
; current launch shape on every boot; this macro is the install-time half of
; the same contract and must stay byte-consistent with the scheme name in
; electron-builder.yml `protocols:` / PAIRING_SEAM.SCHEME.
;
;   SECOND_DEEPLINK_PARSER=0     (registration only, no parsing anywhere)
;   PUBLIC_INBOUND_PORT=0
;   PRODUCTION_SIGNING=NO
;
; #3152 - the supported per-user uninstall must leave nothing this installer
; owns behind. CLAW3 real-Windows evidence (PR #3146) recorded, twice, that a
; per-user uninstall left the installed payload directory and
; `HKCU\Software\Classes\padiem` in place: a `padiem://` handoff then
; resolved to an executable that no longer existed, and the handoff failed
; inside the shell instead of reaching the user.
;
; Why the sweep lives in `customUnInstall` and NOT in a "cleanup section":
; `customUnInstallSection` is a supported hook, but defining it makes
; electron-builder add a components page to the uninstaller
; (`MUI_UNPAGE_COMPONENTS` + `MUI_COMPONENTSPAGE_NODESC`). Real-Windows
; evidence on this branch measured exactly what that does to the SUPPORTED
; path: the silent uninstaller ran and removed nothing at all - payload,
; protocol key and shortcuts all survived. That hook is therefore not used,
; and `tests/packaging-uninstall-cleanup-3152.test.ts` guards the decision so
; the regression cannot come back through a well-meaning refactor.
;
; `customUnInstall` is the other supported uninstaller hook, and it runs
; before the builder's own removal sequence. Doing the owned sweep here makes
; the outcome this installer's own rather than an artefact of the order in
; which the default sequence happens to run, and every step is idempotent, so
; the default sequence that follows has nothing left to do.

!macro customInstall
  ; Remove any previous registration (including a stale dev-host one) before
  ; writing the packaged shape, so exactly one handler exists per user.
  DeleteRegKey HKCU "Software\Classes\padiem"
  WriteRegStr HKCU "Software\Classes\padiem" "" "URL:Padiem Pairing Handoff"
  WriteRegStr HKCU "Software\Classes\padiem" "URL Protocol" ""
  WriteRegStr HKCU "Software\Classes\padiem\DefaultIcon" "" '"$INSTDIR\${APP_EXECUTABLE_FILENAME}"'
  WriteRegStr HKCU "Software\Classes\padiem\shell\open\command" "" '"$INSTDIR\${APP_EXECUTABLE_FILENAME}" "%1"'
!macroend

; #3152 - the owned uninstall sweep.
;
;   INSTALLED_PAYLOAD_REMOVED_BY_UNINSTALL=YES
;   HKCU_PADIEM_HANDLER_AFTER_UNINSTALL=0
;   START_MENU_SHORTCUT_AFTER_UNINSTALL=0
;   DESKTOP_SHORTCUT_AFTER_UNINSTALL=0
;   HKCU_UNINSTALL_ENTRY_AFTER_UNINSTALL=0
;   UNRELATED_HKLM_REGISTRATION_TOUCHED=0
;   UNRELATED_DEV_HOST_REGISTRATION_TOUCHED=0
;
; Ownership boundary, deliberately narrow: every key below lives in HKCU (this
; installer's own per-user hive) and every path is this install's own payload
; or shortcut location. No HKLM write or delete appears here, no other URL
; scheme key is named, and a machine-wide `padiem` handler or another
; application's registration is never read or removed - this installer did not
; create them, so it does not own them.
!macro customUnInstall
  ; 1. Installed payload. Move out of the directory first: removing the
  ;    uninstaller's own current directory is a classic way to leave an install
  ;    half-removed. The default sequence that follows re-runs the same removal,
  ;    so nothing changes when the first pass already worked.
    SetOutPath "$TEMP"
    RMDir /r "$INSTDIR"
    RMDir "$INSTDIR"

  ; 2. Per-user `padiem://` handler written by customInstall. Deleting the
  ;    exact key we wrote leaves every other scheme untouched. A dev checkout
  ;    re-creates its own registration on its next launch (#3093 runtime half).
    DeleteRegKey HKCU "Software\Classes\padiem"

  ; 3. Shortcuts, at the paths this install actually created. The shortcut
  ;    name and menu directory come from the builder's own `setLinkVars`
  ;    (a registry read, with the product file name as fallback) rather than
  ;    from a product-name constant: that constant is only defined when the
  ;    product file name differs from the app file name, so naming it here
  ;    would be an unresolved identifier for this configuration.
    !insertmacro setLinkVars
    Delete "$oldDesktopLink"
    Delete "$oldStartMenuLink"
    RMDir "$SMPROGRAMS\$oldMenuDirectory"

  ; 4. The per-user uninstall registration this installer wrote.
    DeleteRegKey HKCU "${UNINSTALL_REGISTRY_KEY}"
    !ifdef UNINSTALL_REGISTRY_KEY_2
      DeleteRegKey HKCU "${UNINSTALL_REGISTRY_KEY_2}"
    !endif
!macroend
