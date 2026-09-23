# pypdf 6.19.0 source-behavior audit (#2930)

Refs #2930. Parent #2823 (OSS intake gate, PR #2921). Predecessor #2925 matrix
(PR #2928; pypdf disposition `DEFERRED_SOURCE_AUDIT` there is intentionally not
edited — CENTRAL reconciles candidate status after this review).

This artifact is static source/provenance analysis only:

```text
PACKAGE_INSTALL=0
CANDIDATE_EXECUTION=0
THIRD_PARTY_SOURCE_COPY=0
UNREVIEWED_CODE_EXECUTION=0
RUNTIME_DEPENDENCY_ADDED=0
RUNTIME_ADOPTION=0
SKILL_REGISTRATION=0
LIVE_PROVIDER_CALLS=0
SECRET_READS=0
PRODUCTION_MUTATION=0
```

No `pip install`, no candidate import/execution, no third-party source is
vendored into this repository. Upstream source was read from a detached clone
of the immutable tag in a temporary workspace outside the repository.

Method: full-text scan of all 59 package `.py` files under `pypdf/` (tests and
docs excluded from absence claims unless stated), plus manual reading of every
positive hit and of configuration/dependency metadata
(`pyproject.toml`, `_version.py`, `LICENSE`, `_crypt_providers/__init__.py`).

## 1. Immutable source identity

```text
UPSTREAM_REPOSITORY=https://github.com/py-pdf/pypdf
UPSTREAM_TAG=6.19.0
UPSTREAM_TAG_OBJECT=51f9c303af50fa0f55df7640f38e3df0239e8060   (annotated tag)
UPSTREAM_COMMIT=d62cb58d3988b291b0435eddfd118c4f8f6b6a46
COMMIT_SUBJECT=REL: 6.19.0
COMMIT_DATE=2026-09-16T09:10:42Z (committer +02:00)
TAGGER_DATE=2026-09-16T09:31:15Z
IMMUTABLE_SOURCE_VERIFIED=YES
FLOATING_REF_USED=NO   (main/master/latest never used as audit basis)
```

Cross-verification (three independent channels):

1. `git ls-remote https://github.com/py-pdf/pypdf.git refs/tags/6.19.0` → tag
   object `51f9c303…`, dereferenced commit `d62cb58d…`.
2. GitHub API `git/ref/tags/6.19.0` + `git/tags/51f9c303…` → same tag object
   and same target commit; GitHub release `6.19.0` published
   `2026-09-16T09:31:55Z` (release `targetCommitish` is the floating branch
   name `main`, so the release pointer alone is not the pin — the annotated
   tag is).
3. Detached clone checked out at that commit reports
   `git rev-parse HEAD = d62cb58d…`, `git tag --points-at HEAD = 6.19.0`,
   and `pypdf/_version.py` reads `__version__ = "6.19.0"` (`pyproject.toml`
   declares `dynamic = ["version"]`, so the package version is this file).

PyPI 6.19.0 release artifact digests (metadata read only; artifacts not
downloaded or executed):

```text
pypdf-6.19.0-py3-none-any.whl  sha256=7e5d6e730e7dae87d560a2cee218b852f6498c8be61966f3cd02ead971e48d14  size=395480
pypdf-6.19.0.tar.gz            sha256=bbc43aca292369ccc6cbc8a921991ecf2538a3587ab5a116eff06c321d647155  size=7033266
```

License at the audited commit: BSD-3-Clause (`LICENSE` header + `pyproject.toml`
`license = "BSD-3-Clause"`), consistent with the #2925 matrix license row.

## 2. Transitive runtime dependency truth

From `pyproject.toml` at the audited commit, confirmed against PyPI
`requires_dist` for 6.19.0:

```text
required runtime (py>=3.11): NONE
required runtime (py<3.11):  typing_extensions>=4.0 (conditional only)
build-system (build-time only): flit_core>=3.11,<5
optional extras (not installed by default):
  crypto     = cryptography>3.0
  cryptodome = PyCryptodome
  fonts      = fonttools
  image      = Pillow>=8.0.0
  rtl_text   = arabic-reshaper, python-bidi
  full       = arabic-reshaper, cryptography>3.0, fonttools, Pillow>=8.0.0, python-bidi
  dev/docs   = development and documentation only (non-runtime)
```

PADIEM runs Python >= 3.11, so the baseline wheel has **zero required
runtime dependencies**. Optional extras are not installed by default. This
audit establishes only how pypdf invokes them; it does **not** establish the
transitive network, shell, process, filesystem, credential, or native-code
authority of those third-party packages. Any enabled extra needs its own
source/provenance review (section 8).

## 3. Network behavior

Scan patterns across all 59 package `.py` files:
`urllib`, `requests`, `httpx`, `socket`, `urlopen`, `urlretrieve`,
`http.client`, `aiohttp`, `socketserver` → **zero matches** (rg exit 1).

```text
NETWORK_BEHAVIOR=ABSENT_IN_PACKAGE_SOURCE
```

URI handling is parse/store only: `/URI` appears as PDF name constants
(`constants.py:52`), annotation dictionaries written by
`annotations/_non_markup_annotations.py:63-65`, and the writer helper
`_writer.add_uri` (`_writer.py:2287`, `2332-2333`). None of these dereference
the URI. Parsing or emitting a URI annotation string is not a fetch.

```text
EXTERNAL_URI_FETCH=NO
```

No `/Launch` action class or handler exists anywhere in the package (including
tests); Launch-style actions, if present in a hostile PDF, are inert generic
dictionaries to this library.

## 4. Filesystem behavior

Reads:

- `_reader.py:172` — `open(stream, "rb")` when `PdfReader` is given a path
  (caller-supplied path).
- `_writer.py:252` — `open(fileobj, "rb")` incremental mode (caller-supplied
  path).
- `generic/_image_xobject.py` — `Image.open(BytesIO(...))` in-memory only
  (optional Pillow extra).

Writes:

- `filters.py:755-769` — JBIG2 decode creates a `TemporaryDirectory`, writes
  `image.jbig2` / `globals.jbig2` via `Path.write_bytes`, runs the external
  decoder, and the context manager removes the directory. Temp-file scope is
  bounded to the decode call.
- `_writer.write(stream)` — writes output to the stream/path the caller
  provides; no implicit target.
- `_utils.mark_location` (`_utils.py:427-436`) — writes fixed filename
  `pypdf_pdfLocation.txt` into the process CWD. Sole caller is upstream's own
  `tests/test_utils.py`; it is not reachable from `PdfReader`/`PdfWriter`
  normal paths, but the helper exists in the shipped package.
- `_page.py:2136` and `_text_extraction/_layout_mode/_fixed_width_page.py`
  `285,351,354` — debug JSON writes occur only when the caller explicitly
  passes `debug_path` to layout-mode text extraction (default `None`).
- Attachment APIs return/embed bytes in memory only (section 9); the library
  does not extract embedded files to disk by itself.

```text
FILESYSTEM_BEHAVIOR=READS_CALLER_PATHS; WRITES_TEMP_JBIG2_AND_CALLER_TARGETS; NO_IMPLICIT_HOST_PATHS
```

No `os.remove`/`shutil.rmtree` of caller data; `shutil` is used only for
`shutil.which`.

## 5. Shell / subprocess behavior

Shell scan (`os.system`, `os.popen`, `shell=True`, `os.exec*`, `os.spawn*`) →
**zero matches**.

```text
SHELL_BEHAVIOR=ABSENT
```

Subprocess is **present but conditional**, solely in `filters.py`:

- `filters.py:43` `import subprocess`; `filters.py:774` and `filters.py:804`
  `subprocess.run([...])` with an argv **list** (never `shell=True`),
  `capture_output=True`.
- Target executable: `Configuration.jbig2dec_binary`, resolved once via
  `shutil.which("jbig2dec")` (`_configuration.py:19`, module-level deprecated
  alias `filters.py:741`).
- Reachability: `decode_stream_data` dispatches `/JBIG2Decode` →
  `JBIG2Decode.decode` (`filters.py` filter chain). If the binary is absent,
  `DependencyError("jbig2dec binary is not available.")` is raised — no
  process starts. `_is_binary_compatible` probes `jbig2dec --version`.
- argv is fixed apart from paths inside the private TemporaryDirectory and
  the configured `-M` memory limit; no PDF-controlled string becomes an
  executable or shell token.

```text
SUBPROCESS_BEHAVIOR=PRESENT_CONDITIONAL_JBIG2DEC   (argv list, no shell, PATH-resolved binary)
```

## 6. Environment / credential reads

Environment:

- `filters.py:772-784` — `os.environ.copy()` then `environment["LC_ALL"]="C"`
  passed as the child env for the JBIG2 subprocess. This is a general
  environment copy on the conditional JBIG2 path, not a named-variable read.
- `shutil.which("jbig2dec")` (`_configuration.py:19`, `filters.py:741`) —
  PATH-based executable discovery (implicit PATH use).
- No other `os.environ` / `os.getenv` usage in the package. The
  `_configuration.py` module reads no environment variables; limits are a
  frozen dataclass + ContextVar, overridden programmatically only.

```text
ENVIRONMENT_READS=PRESENT_CONDITIONAL (child-env copy + PATH lookup on JBIG2 path); no named env vars
```

Credentials:

- Zero matches for API token names, cloud credential conventions, `HOME`
  reads, config-file discovery, or secret file opens.
- All `password` occurrences are PDF standard-security document passwords
  (caller-supplied bytes/str for `PdfReader.decrypt` / `PdfWriter.encrypt`
  per PDF spec algorithms), never host credentials.
- `import secrets` (`_encryption.py`, crypt providers) is the stdlib CSPRNG
  for encryption salts/IVs — generation, not read.
- `hashlib` md5/sha-256/384/512 usages implement the PDF spec key schedule
  (`_encryption.py`) and object hashing (`_base.py`, `_writer.py`) — not
  credential verification against any store.

```text
CREDENTIAL_READS=ABSENT
CONFIG_DISCOVERY=ABSENT  (no user/system config file discovery; PATH executable lookup only)
```

## 7. Dynamic loading / plugin behavior

Scan: `importlib`, `__import__`, `eval(`, `exec(`, `entry_point`,
`pkg_resources`, `plugin` in package source → **zero matches**. All imports
are static (a few function-local `from ..filters import …` with literal module
paths).

```text
DYNAMIC_LOADING=ABSENT
PLUGIN_AUTHORITY=ABSENT
```

## 8. Optional dependency authority

Crypt provider selection (`_crypt_providers/__init__.py`): try
`cryptography` → `ImportError` → try `PyCryptodome` → `ImportError` →
pure-Python `_fallback`. From pypdf's own call sites these providers are
invoked through Python APIs rather than an explicit crypto subprocess.
However, this audit does not independently establish the internal or wheel
authority of `cryptography` or `PyCryptodome`.

Other optional extras are likewise only characterized at the pypdf integration
boundary: Pillow is passed in-memory image data, fonttools is used for font
handling, and rtl extras are used for text shaping. Their own network,
filesystem, process, credential, native-code, or external-tool behavior is
outside this pypdf-only audit and must be reviewed separately before enabling
an extra. Pillow 12.3.0 is tracked separately by #2931.

Within **pypdf package source itself** at this pin, the only explicit
subprocess path found is the optional `jbig2dec` path described in section 5.
That finding must not be generalized to the internals of optional third-party
dependencies.

```text
OPTIONAL_DEPENDENCY_AUTHORITY=DEFERRED_TRANSITIVE_AUDIT (pypdf call sites bounded; optional dependency internals not established here)
```

## 9. PDF-specific risks (feature vs execution authority)

Embedded JavaScript:

- `actions/_actions.py:203-217` — `JavaScript` action **constructs** `/S
  /JavaScript` + `/JS` strings (write-side API).
- `_writer.add_js` (`_writer.py:783-799`, deprecated in favor of
  `add_open_action` for 7.0.0) embeds a JS string into the output PDF.
- Reader side: `/OpenAction` is parsed only as a destination
  (`_doc_common.py:891-910` returns `Destination`); the JS name tree is data.
- There is **no JavaScript interpreter, engine, or eval of PDF content**
  anywhere in the package (section 7 scan covers `eval`/`exec`).

```text
JAVASCRIPT_EXECUTION=NO   (read/store/create of JS strings; zero execution authority)
PDF_EMBEDDED_JAVASCRIPT_HANDLING=DATA_ONLY
```

External URI / OpenAction: section 3. `OpenAction` is exposed as a
destination accessor, not an execution hook.

Attachments / embedded files:

- Read: `PdfReader.attachments` / `attachment_list`
  (`_doc_common.py:1588-1610`) yields `EmbeddedFile` objects whose `.data`
  is bytes **in memory** (`generic/_files.py` `.get_data()`).
- Write: `PdfWriter.add_attachment` (`_writer.py:818`) and
  `EmbeddedFile._create_new` embed content into the writer name tree.
- No API writes an embedded file to a host path automatically; disk write of
  extracted bytes is explicitly a caller action (docstrings say so).

```text
EMBEDDED_FILE_BEHAVIOR=IN_MEMORY_ONLY; NO_AUTO_EXTRACTION; NO_HOST_PATH_DERIVATION
```

Crypto paths: section 8 + `_encryption.py` standard handlers (RC4 revisions,
AES-128 V4, AES-256 V5) implemented in-process; ruff per-file-ignores
acknowledge RC4/AES-ECB as required by the PDF spec. No external `openssl`
process, no network crypto.

```text
PYPDF_CRYPTO_CALL_PATHS=IN_PROCESS; OPTIONAL_PROVIDER_INTERNAL_AUTHORITY=OUT_OF_SCOPE; PURE_PYTHON_FALLBACK_AVAILABLE=YES
```

Parser resource risks (bounds are real and read from source):

```text
zlib_maximum_output_length        = 75_000_000
zlib_maximum_recovery_input_length =  5_000_000
lzw/runlength/jbig2 maximum       = 75_000_000 each
array_based_stream_maximum_output = 75_000_000
maximum_declared_stream_length    = 75_000_000
image_maximum_buffer_size         = 75_000_000
xmp_maximum_input_length          =  5_000_000
xmp_maximum_element_count         =    100_000
outline entries/depth             =    100_000 / 100
page_tree entries/depth           =    100_000 / 100
xform invocations per extraction  =      5_000
IndirectObject._MAXIMUM_PART_LENGTH = 64
recursion: RecursionError → PdfReadError("Maximum recursion depth reached.")
alphabetical page-label size limited (6.19.0 security fix #4096)
```

All limits live in `_configuration.py` (frozen dataclass + ContextVar) and
are checked in `filters.py` / `_reader.py` / `_doc_common.py`. Object streams
are read whole into memory before parsing — memory exhaustion risk is bounded
by the caps above but not eliminated. Untrusted-PDF handling remains a
caller responsibility.

```text
PARSER_RESOURCE_RISKS=BOUNDED_BY_CONFIGURATION_LIMITS; INHERENT_UNTRUSTED_PARSE_RISK_REMAINS
```

## 10. CANDIDATE_INTERNAL_GUARDS vs PADIEM_FILE_INTAKE_GATE

```text
CANDIDATE_INTERNAL_GUARDS (properties OF pypdf itself at this pin):
  network=absent, shell=absent, credentials=absent, dynamic loading=absent,
  JS execution=absent, attachment auto-extract=absent,
  decompression/recursion/page-tree limits present,
  subprocess=conditional jbig2dec only (fail-closed when binary missing)

PADIEM_FILE_INTAKE_GATE (#2824):
  the mandatory host-side admission control for any file entering PADIEM
  common file intake — independent of which parser is chosen.
```

pypdf's internal limits and this audit's absence findings **do not
substitute for, weaken, or replace** the #2824 gate. No claim in this
document may be read as candidate-level guards satisfying
`PADIEM_FILE_INTAKE_GATE`. The canonical OSS gate (`oss_skill_intake.py`)
is likewise untouched (`GATE_WEAKENED=NO`).

## 11. Disposition

```text
FINAL_SOURCE_DISPOSITION=SOURCE_AUDIT_PASS_WITH_RESTRICTIONS
SOURCE_BEHAVIOR_AUDIT_COMPLETE=YES
ADOPTION_ELIGIBILITY_REVIEW_READY=YES
```

Restrictions (must travel with the finding):

1. `SUBPROCESS_BEHAVIOR=PRESENT_CONDITIONAL_JBIG2DEC` — any later adoption
   review must decide whether the `jbig2dec` PATH lookup/subprocess is
   permitted in the PADIEM worker environment or must be disabled
   (binary absent → library raises `DependencyError`, which is the safe
   default).
2. CWD debug helper `mark_location` and opt-in `debug_path` writers exist in
   the shipped package; callers must not invoke them in production paths.
3. #2824 file intake gate remains fully mandatory (section 10).
4. Optional crypto extras are not adopted by this decision; their own source,
   native/wheel provenance, and transitive authority are not established by
   this pypdf-only audit. The pure-Python fallback remains available.
5. Any optional extra (including Pillow/fonttools/rtl packages) requires its
   own source/provenance review before it can be enabled in a PADIEM runtime.
6. This is **not** `RUNTIME_ADOPTION_APPROVED`. Maximum expression:

```text
RUNTIME_ADOPTION=0
SKILL_REGISTRATION=0
```

Unknown/deferred at this pin:

```text
FUTURE_RELEASES=Beyond 6.19.0 are unaudited (new tag requires new audit).
UPSTREAM_ISSUE_TRIAGE=Live GitHub issue triage state not re-derived here.
SAMPLE_FILES_SUBMODULE=https://github.com/py-pdf/sample-files is dev data only (not package code).
```

CENTRAL review of the #2925 matrix reconciliation is required before any
candidate disposition change lands in `OSS_CANDIDATE_INTAKE_MATRIX_2925.md`.
