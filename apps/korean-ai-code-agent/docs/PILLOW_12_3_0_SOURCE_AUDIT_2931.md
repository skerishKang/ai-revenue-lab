# Pillow 12.3.0 Immutable Source Behavior Audit — Issue #2931

Refs: #2931 · Parent: #2823 · Predecessor: #2925 (intake matrix, unchanged)
Local: LOCAL3 (클로3) · Worktree: E:\padiem-clawu-260923-3 · Branch: feat/2931-pillow-source-audit
Date: 2026-09-23

## Non-equivalence (binding)

```text
METADATA_LICENSE_REVIEW != SOURCE_BEHAVIOR_AUDIT != RUNTIME_ADOPTION
PILLOW_INTERNAL_GUARDS != PADIEM_FILE_INTAKE_AUTHORITY
SOURCE_AUDIT_PASS_WITH_RESTRICTIONS != NATIVE_WHEEL_PROVENANCE_ACCEPTED
```

This document is static source-behavior evidence only. It does not install, import,
or execute Pillow code. It does not authorize Skill registration, runtime adoption,
or file-intake trust. The OSS intake matrix of #2925 was not edited by this work.

## Key-value evidence block

```text
ISSUE=2931
PARENT_ISSUE=2823
PREDECESSOR_ISSUE=2925
PACKAGE=Pillow
PACKAGE_VERSION=12.3.0
LICENSE=MIT-CMU
UPSTREAM_REPOSITORY=https://github.com/python-pillow/Pillow
UPSTREAM_TAG=12.3.0
UPSTREAM_TAG_TYPE=LIGHTWEIGHT
UPSTREAM_COMMIT=bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d
UPSTREAM_COMMIT_VERIFIED=YES
IMMUTABLE_SOURCE_VERIFIED=YES
PYPI_SDIST_SHA256=3b8182a766685eaa002637e28b4ec8d6b18819a0c71f579bf0dbaa5830297cce
PYPI_UPLOAD_DATE=2026-07-01
PYPI_YANKED=NO
WHEEL_COUNT=90
WHEEL_DIGESTS_RECORDED=YES
GH_RELEASE_ASSETS=0
REQUIRES_PYTHON=>=3.10
REQUIRED_RUNTIME_DEPENDENCIES=0
SOURCE_AUDIT_METHOD=STATIC_READ_ONLY
SOURCE_AUDIT_CLONE_LOCATION=OUTSIDE_REPO_READ_ONLY
SOURCE_BEHAVIOR_AUDIT_COMPLETE=YES
FINAL_SOURCE_DISPOSITION=SOURCE_AUDIT_PASS_WITH_RESTRICTIONS
NATIVE_BINARY_PROVENANCE_PENDING=YES
RUNTIME_ADOPTION=0
RUNTIME_DEPENDENCY_ADDED=0
PACKAGE_INSTALL=0
CANDIDATE_EXECUTION=0
THIRD_PARTY_SOURCE_COPY=0
UNREVIEWED_CODE_EXECUTION=0
SKILL_REGISTRATION=0
LIVE_PROVIDER_CALLS=0
SECRET_READS=0
PRODUCTION_MUTATION=0
NETWORK_BEHAVIOR=NONE_IN_CORE
FILESYSTEM_READ=CALLER_CONTROLLED_PATHS_FONTS_TEMP
FILESYSTEM_WRITE=CALLER_CONTROLLED_PATHS_TEMP
SHELL_ACCESS=ONE_OS_SYSTEM_IMAGE_SHOW_ONLY
SUBPROCESS_BEHAVIOR=FORMAT_OR_API_GATED
EXTERNAL_EXECUTABLE_BEHAVIOR=FORMAT_OR_API_GATED
ENVIRONMENT_READS=PILLOW_TUNE_AT_IMPORT_FONTS_DISPLAY
CREDENTIAL_READS=NONE_FOUND
DYNAMIC_PLUGIN_LOADING=STATIC_FIXED_EXTENSION_MAP
DYNAMIC_LIBRARY_LOADING=C_SIDE_IMAGE_TK_FRIBIDI_USER32_ONLY
METADATA_BEHAVIOR=READ_WRITE_NO_AUTO_SANITIZATION
DECOMPRESSION_BOMB_PROTECTION=ENFORCED_DEFAULT
MULTIFRAME_RESOURCE_RISK=UNCAPPED_FRAME_COUNT
MALFORMED_IMAGE_FAILURE=FAIL_CLOSED
TRANSITIVE_RUNTIME_DEPENDENCIES=NONE_REQUIRED
OS_SYSTEM_CALL_COUNT=1
SHELL_TRUE_CALL_COUNT=0
PY_IMPORT_SOCKET_URLLIB_REQUESTS_COUNT=0
MAX_IMAGE_PIXELS_DEFAULT=89478485
OSS_GATE_UNCHANGED=YES
PADIEM_MATRIX_EDITED=0
CENTRAL_RECONCILIATION_REQUIRED=YES
```

## Method

- Read-only shallow clone to
  `C:\Users\limone\AppData\Local\Temp\opencode\pillow-12.3.0-src`
  (outside the repository). No Pillow module was imported, no script from the
  candidate was run, no binary wheel was installed or loaded.
- `SOURCE_AUDIT_METHOD=STATIC_READ_ONLY`: file reads, `git grep` over Python
  (`src/PIL`), C (`src`, `src/libImaging`, `src/Tk`, `src/thirdparty`),
  `setup.py`, `pyproject.toml`.
- Commit identity three-way verified: `git ls-remote` tag → clone `rev-parse`
  → `git describe --exact-match` all equal to
  `bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d`.
- Evidence links pin that commit:
  `https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/<path>#L<line>`

## 1. NETWORK_BEHAVIOR=NONE_IN_CORE

- Grep count `0` for `^import socket|^import urllib|^import requests|^from urllib|^import http|^from http`
  across `src/PIL`.
- Matches for `https?://` are comments and fixed XMP/Exif namespace marker
  strings only (e.g. `http://ns.adobe.com/xap/1.0/` in save helpers). They are
  never fetched.
- C side: no sockets/WinHTTP/WinInet for content. The only connection primitive
  is `xcb_connect` in `src/display.c:866` — the local X11 display socket used by
  screen capture (`grabscreen_x11`), display-local, not internet.
- `Image.open` accepts a filesystem path or a file object only; there is no
  URL-loading path ([Image.py:3585](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/Image.py#L3585)).

## 2. FILESYSTEM_READ=CALLER_CONTROLLED_PATHS_FONTS_TEMP

- `Image.open`/`Image.save` read/write caller-supplied paths via builtins file
  IO ([Image.py:3585](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/Image.py#L3585),
  [Image.py:2592](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/Image.py#L2592)).
- Font discovery reads system directories from `WINDIR`, `XDG_DATA_HOME`,
  `XDG_DATA_DIRS` ([ImageFont.py:894-908](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/ImageFont.py#L894)).
- No home-directory config, registry, or application-state reads were found.

## 3. FILESYSTEM_WRITE=CALLER_CONTROLLED_PATHS_TEMP

- Save writes to the caller path only.
- Temp creation: `tempfile.mkstemp` in `Image._dump`
  ([Image.py:731](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/Image.py#L731)),
  in `ImageGrab` (macOS `screencapture` output), and in `JpegImagePlugin.load_djpeg`
  ([JpegImagePlugin.py:468](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/JpegImagePlugin.py#L468)).
  All are explicit-call paths, not `Image.open` of ordinary formats.

## 4. SHELL_ACCESS / SUBPROCESS_BEHAVIOR / EXTERNAL_EXECUTABLE_BEHAVIOR=FORMAT_OR_API_GATED

- `os.system` count in `src/PIL` = `1`:
  [ImageShow.py:120](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/ImageShow.py#L120)
  (`os.system(self.get_command(path, **options))  # nosec`), reached only from
  `Image.show()` ([Image.py:2753](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/Image.py#L2753),
  [ImageShow.py:51](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/ImageShow.py#L51)),
  with `shlex.quote`d paths in the command builder.
- `shell=True` count = `0`. Windows `os.startfile(path)` at
  [ImageShow.py:165](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/ImageShow.py#L165)
  (shell-association open, `Image.show()` only).
- External-tool matrix (none on the `Image.open`/`save` path for PNG/JPEG/GIF/BMP/TIFF/WebP/AVIF):

| Module:line | Tool | Trigger | Default? | Arg form |
|---|---|---|---|---|
| EpsImagePlugin.py:45-61,68-159,405 | `gs` (Ghostscript) | decoding any EPS: `_open` sets an `eps` tile, `load()` calls `Ghostscript()`; `shutil.which`-probed, `check_call(["gs", ...])` | YES for `.eps` format | list |
| JpegImagePlugin.py:468 | `djpeg` | explicit `JpegImageFile.load_djpeg()` only; no internal callers found | NO | list |
| GifImagePlugin.py:876-919,1223 | `ppmtogif`/`ppmquant` | `_save_netpbm`; `Image.register_save(..., _save_netpbm)` is commented out at line 1223 | NO (dead by default) | list |
| ImageShow.py:120,165,333-341 | viewer (`xdg-open`/`display`/`gm`/`eog`/`xv`, Preview.app, `os.startfile`) | explicit `Image.show()`; viewer registration probes PATH with `shutil.which` | explicit API only | os.system quoted / startfile / list-form helpers |
| ImageGrab.py:33,125-129,158,199-201 | `gnome-screenshot`/`grim`/`spectacle`/`wl-paste`/`xclip`/`osascript`/`screencapture` | explicit `ImageGrab.grab()`/`grabclipboard()` (non-Windows; win32 is builtin `grabscreen` via User32) | explicit API only | list |

- Consequence: a PADIEM caller that merely opens/converts standard formats does
  not invoke external programs. The `.eps` format is the one default-path
  exception and must be treated as an external-tool format (restriction R1).

## 5. ENVIRONMENT_READS=PILLOW_TUNE_AT_IMPORT_FONTS_DISPLAY

| Variable | Location | Effect |
|---|---|---|
| `PILLOW_ALIGNMENT`, `PILLOW_BLOCK_SIZE`, `PILLOW_BLOCKS_MAX` | [Image.py:4013-4015](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/Image.py#L4013), applied by `_apply_env_variables()` at import ([Image.py:4040](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/Image.py#L4040)) | core tuning (`core.set_*`); invalid values warn, not crash |
| `WINDIR` | [ImageFont.py:896](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/ImageFont.py#L896) | Windows font directory discovery |
| `XDG_DATA_HOME`, `XDG_DATA_DIRS` | [ImageFont.py:900+](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/ImageFont.py#L900) | user font discovery |
| `DISPLAY`, `WAYLAND_DISPLAY` | [ImageGrab.py:192-201](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/ImageGrab.py#L192) | screenshot/clipboard display selection |

- `os.environ` access points in `src/PIL` are exactly the rows above (plus the
  dict taken inside `_apply_env_variables` at
  [Image.py:4010](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/Image.py#L4010)).

## 6. CREDENTIAL_READS=NONE_FOUND

- No password/token/secret/credential reads, no `HOME`-scoped auth material, no
  keychain, no provider endpoints anywhere in `src/PIL` or the C sources under
  the audit greps. `SECRET_READS=0` (safety counter), and no credential
  variables appear in the environment table above.

## 7. DYNAMIC_PLUGIN_LOADING=STATIC_FIXED_EXTENSION_MAP

- `_import_plugin_for_extension` resolves only from the fixed
  `_EXTENSION_PLUGIN` map and calls plain `__import__` of `PIL.<plugin>` —
  never a caller-supplied path or module name
  ([Image.py:405-427](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/Image.py#L405)).
- `preinit()`/`init()` iterate the static `_plugins` tuple
  ([Image.py:429](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/Image.py#L429),
  [Image.py:474-487](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/Image.py#L474)).
- Core binding: `from . import _imaging as core`
  ([Image.py:95](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/Image.py#L95));
  WebP/AVIF via `from . import _webp` / `_avif`. No `ctypes`, no arbitrary-path
  module loader in `src/PIL`.

## 8. DYNAMIC_LIBRARY_LOADING=C_SIDE_IMAGE_TK_FRIBIDI_USER32_ONLY

- `src/Tk/tkImaging.c:465` `dlopen(tkinter_libname)` — `ImageTk` path only
  ([ImageTk.py:63](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/ImageTk.py#L63)).
- `src/thirdparty/fribidi-shim/fribidi.c:46-67` `dlopen("libfribidi.so"...)`
  invoked from `_imagingft` init (`load_fribidi()`, `src/_imagingft.c:1671`) —
  text-shaping optional dependency.
- `src/display.c:327` `LoadLibraryA("User32.dll")` — Windows screen grab.
- Codecs are linked at build time (`setup.py` extensions below); no runtime
  codec download, no plugin `.so` search path.

## 9. NATIVE_MODULE_BEHAVIOR (8 extension targets)

`setup.py:1081-1094` defines: `PIL._imaging`, `PIL._imagingft`,
`PIL._imagingcms`, `PIL._webp`, `PIL._avif`, `PIL._imagingtk`,
`PIL._imagingmath` (`-lm` on non-Windows), `PIL._imagingmorph`.

- Feature/codec registry is build-time: `features.py`
  (`HAVE_*`/`*_version` read from the loaded extension attributes: raqm,
  fribidi, harfbuzz, libjpeg_turbo, mozjpeg, zlib_ng, libimagequant, xcb).
- `NATIVE_BINARY_PROVENANCE_PENDING=YES`: PyPI sdist sha256 and 90 wheel
  digests are recorded from the PyPI JSON for `pillow/12.3.0` (uploaded
  2026-07-01, not yanked), but no release attestation/SLSA provenance was
  verified in this task, and the GitHub release for tag `12.3.0` contains
  `assets=0`. A source audit cannot certify binary wheels.

## 10. DECOMPRESSION_BOMB_PROTECTION=ENFORCED_DEFAULT

- `MAX_IMAGE_PIXELS = 1024 * 1024 * 1024 // 4 // 3` →
  `MAX_IMAGE_PIXELS_DEFAULT=89478485`
  ([Image.py:86](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/Image.py#L86)).
- `DecompressionBombWarning` above 1×, `DecompressionBombError` above 2×
  ([Image.py:75-79](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/Image.py#L75),
  check at [Image.py:3564](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/Image.py#L3564)).
- Enforced inside `Image.open` after each format attempt
  ([Image.py:3678](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/Image.py#L3678))
  and from multiple plugins (GIF frame/dispose, TIFF tile, ICO, PCX, BMP, …).
- Setting `MAX_IMAGE_PIXELS = None` disables the guard entirely; PADIEM callers
  must never do this (restriction R4).

## 11. MULTIFRAME_RESOURCE_RISK=UNCAPPED_FRAME_COUNT

- GIF `n_frames` walks frames lazily
  ([GifImagePlugin.py:130](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/GifImagePlugin.py#L130));
  TIFF walks IFDs
  ([TiffImagePlugin.py:1204](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/TiffImagePlugin.py#L1204)).
- No global frame-count cap and no total-pixels-across-frames budget exist
  (negative grep across `src/PIL`). Per-pixel bomb checks apply per frame, so
  the residual risk is frame-count/time, not single-frame pixels
  (restriction R5).

## 12. MALFORMED_IMAGE_FAILURE=FAIL_CLOSED

- Unknown prefix → `UnidentifiedImageError`; per-format parse errors
  (`SyntaxError`/`IndexError`/`TypeError`/`struct.error`) fall through to the
  next candidate inside `_open_core`.
- Truncated data: `LOAD_TRUNCATED_IMAGES = False` by default
  ([ImageFile.py:64](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/ImageFile.py#L64));
  decoder error raises `OSError` unless explicitly overridden
  ([ImageFile.py:429](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/ImageFile.py#L429)).
- `_safe_read` bounds reads at `SAFEBLOCK = 1024 * 1024`
  ([ImageFile.py:62](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/ImageFile.py#L62),
  block loop at line 722-731).
- PNG text: `MAX_TEXT_CHUNK = SAFEBLOCK` (1 MiB) and
  `MAX_TEXT_MEMORY = 64 * MAX_TEXT_CHUNK` with decompress cap
  ([PngImagePlugin.py:96-102](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/PngImagePlugin.py#L96),
  line 147-149).
- EPS negative `BeginBinary` byte counts raise `ValueError`.

## 13. METADATA_BEHAVIOR=READ_WRITE_NO_AUTO_SANITIZATION

- `getexif()` ([Image.py:1619](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/Image.py#L1619)),
  GPS IFD via `exif.get_ifd(ExifTags.IFD.GPSInfo)`, `getxmp()`
  ([Image.py:1580](https://github.com/python-pillow/Pillow/blob/bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d/src/PIL/Image.py#L1580)
  — requires optional `defusedxml`, otherwise warns and returns `{}`),
  ICC profiles and PNG text chunks exposed through `info`.
- `save()` writes back exactly the metadata the caller passes (`exif=`,
  `xmp=`, `icc_profile=`, `pnginfo=`); there is no automatic GPS/PII stripping.
  Sanitation is a PADIEM-side duty per #2828 (restriction R7).

## 14. TRANSITIVE_RUNTIME_DEPENDENCIES=NONE_REQUIRED

- `pyproject.toml` `[project]` (line 11) declares no `dependencies` key;
  runtime extras are optional (`icc`, `xmp`, `webp`, `aatranslate`, …).
- `requires-python = ">=3.10"`. Build requirements (`pybind11`,
  `setuptools>=77`) are build-time only.
- `REQUIRED_RUNTIME_DEPENDENCIES=0`, `RUNTIME_DEPENDENCY_ADDED=0`.

## Binding restrictions (apply to any future adoption review)

- **R1** `.eps` decoding invokes external `gs` from PATH: PADIEM file intake must
  block `.eps` unless an explicit external-tool authority exists.
- **R2** `Image.show()` and `ImageGrab.*` are prohibited inside Skill/ingest
  contexts (they shell out to viewers/screenshot tools).
- **R3** `load_djpeg()` and `_save_netpbm` (djpeg/ppmtogif/ppmquant) remain
  prohibited even though they are opt-in/dead-by-default upstream.
- **R4** Never set `Image.MAX_IMAGE_PIXELS = None` or raise it above policy;
  keep bomb checks enabled.
- **R5** PADIEM callers must enforce their own frame-count/time budget
  (`n_frames` is uncapped upstream).
- **R6** Keep `LOAD_TRUNCATED_IMAGES = False` (fail closed).
- **R7** No EXIF/GPS/XMP/ICC pass-through to storage, logs, or Drive reports
  without #2828 sanitation.
- **R8** Deployment environment must be trusted for `PILLOW_*` variables and
  font/display environment variables listed in section 5.
- **R9** Native wheel provenance remains pending; `SOURCE_AUDIT_PASS*` does not
  accept binaries (`NATIVE_WHEEL_PROVENANCE_ACCEPTED` is a separate gate).

## Disposition

```text
SOURCE_BEHAVIOR_AUDIT_COMPLETE=YES
FINAL_SOURCE_DISPOSITION=SOURCE_AUDIT_PASS_WITH_RESTRICTIONS
NATIVE_BINARY_PROVENANCE_PENDING=YES
RUNTIME_ADOPTION=0
CENTRAL_RECONCILIATION_REQUIRED=YES
STOP=YES
DRAFT=YES READY=NO MERGE=NO
```

Boundaries / non-goals: no package install, no Pillow execution, no Skill
registration, no OSS intake matrix or gate edits, no live provider calls, no
readiness claim. Final adoption disposition and matrix reconciliation are
CENTRAL's decision.
