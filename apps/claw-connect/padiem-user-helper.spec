# -*- mode: python ; coding: utf-8 -*-
"""#7108 PR-1 — single-file, windowed PyInstaller shape for the user helper.

No COLLECT block: the EXE carries the archive itself, so the one-click installer
downloads exactly one file. ``console=False`` is the no-console half of the
shape; the entrypoint adds ``CREATE_NO_WINDOW`` to child shells.
"""
import os

ROOT = os.path.abspath(SPECPATH)

a = Analysis(
    [os.path.join(ROOT, "user_helper_entry.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[],
    hiddenimports=[
        "claw_connect.user_helper_service",
        "claw_connect.user_session_helper",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="padiem-user-helper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
