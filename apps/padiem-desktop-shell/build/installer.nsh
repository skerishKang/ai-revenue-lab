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

!macro customInstall
  ; Remove any previous registration (including a stale dev-host one) before
  ; writing the packaged shape, so exactly one handler exists per user.
  DeleteRegKey HKCU "Software\Classes\padiem"
  WriteRegStr HKCU "Software\Classes\padiem" "" "URL:Padiem Pairing Handoff"
  WriteRegStr HKCU "Software\Classes\padiem" "URL Protocol" ""
  WriteRegStr HKCU "Software\Classes\padiem\DefaultIcon" "" '"$INSTDIR\${APP_EXECUTABLE_FILENAME}"'
  WriteRegStr HKCU "Software\Classes\padiem\shell\open\command" "" '"$INSTDIR\${APP_EXECUTABLE_FILENAME}" "%1"'
!macroend

!macro customUnInstall
  ; The uninstall removes the packaged registration. A dev checkout re-creates
  ; its own registration on its next launch (#3093 runtime half).
  DeleteRegKey HKCU "Software\Classes\padiem"
!macroend
