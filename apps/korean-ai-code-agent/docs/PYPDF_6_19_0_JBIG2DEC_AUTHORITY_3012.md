# pypdf 6.19.0 jbig2dec subprocess/environment authority bound (#3012)

Refs #3012. Parent #2823. Program parent #2821. Predecessors #2925, #2930, #2990.

This is a source-only, fail-closed decision/evidence slice. It does not install or import
pypdf, execute `jbig2dec`, register a Skill, call a provider, or mutate Production. It
reuses the canonical OSS intake gate, file intake safety boundary, parser isolation boundary,
and evidence contracts; it does not create a second authority.

## Current-main basis

```text
UPSTREAM_REPOSITORY=https://github.com/py-pdf/pypdf
UPSTREAM_TAG=6.19.0
UPSTREAM_TAG_OBJECT=51f9c303af50fa0f55df7640f38e3df0239e8060
UPSTREAM_COMMIT=d62cb58d3988b291b0435eddfd118c4f8f6b6a46
PYPDF_WHEEL_SHA256=7e5d6e730e7dae87d560a2cee218b852f6498c8be61966f3cd02ead971e48d14
PYPDF_SDIST_SHA256=bbc43aca292369ccc6cbc8a921991ecf2538a3587ab5a116eff06c321d647155
SOURCE_AUDIT=#2930
RECONCILIATION=#2990
CURRENT_MAIN_AT_FRESH_READ=d873ded5b25653cc8cbe88d6d3a8b76a2364f769
FLOATING_REF_USED=NO
```

The accepted source audit establishes the only package-source subprocess path at this pin:
the conditional `/JBIG2Decode` path in `pypdf/filters.py`. It uses an argv list, no
`shell=True`, a call-scoped temporary directory, and raises `DependencyError` when the
binary is absent. The child is nevertheless launched from a `shutil.which` PATH lookup
and receives `os.environ.copy()` plus `LC_ALL=C`.

## Decision

```text
JBIG2DEC_DEFAULT_ENABLED=NO
JBIG2DEC_REQUIRED_FOR_COMMON_PDF=NO
SUBPROCESS_ENV_INHERITS_HOST=YES_IN_PINNED_UPSTREAM_PATH
SUBPROCESS_PATH_TRUST_BOUNDARY=HOST_PATH_LOOKUP_BY_PINNED_UPSTREAM
RAW_SECRET_INHERITANCE_RISK=YES
NETWORK_AUTHORITY_GAINED=NO
SAFE_DISABLE_POSSIBLE=YES
BOUNDED_WRAPPER_POSSIBLE=YES
```

`JBIG2DEC_DEFAULT_ENABLED=NO` is the only approved PADIEM default for this slice. Common
PDF extraction must not require the external decoder. A later wrapper may be considered
only after the binary is independently identified and pinned for the selected platform.

The minimum later-wrapper contract is:

```text
EXECUTABLE_ORIGIN=REVIEWED_AND_IMMUTABLE
CHILD_ENVIRONMENT=ALLOWLISTED_ENV_ONLY
RAW_HOST_ENV_INHERITANCE=NO
SHELL_EXECUTION=NO
UNBOUNDED_SUBPROCESS=NO
FLOATING_BINARY=NO
NETWORK_ESCALATION=NO
FAIL_CLOSED_WHEN_BINARY_ABSENT_OR_UNAPPROVED=YES
```

The wrapper must use an argv-list invocation, explicit timeout/resource bounds, an
immutable binary path or a platform-specific provenance receipt, and a child environment
containing only the minimum required variables. It must not resolve a caller-provided
executable, accept a caller-provided `PATH`, inherit the host environment, or use a shell.
A missing, mismatched, unapproved, or hash-inconsistent binary must fail closed before
process creation.

## Negative cases

The later contract must reject, before process creation:

```text
UNEXPECTED_EXECUTABLE=REJECT
UNEXPECTED_PATH=REJECT
SECRET_LIKE_ENV_INHERITANCE=REJECT
UNPINNED_VERSION=REJECT
UNSUPPORTED_BINARY_ORIGIN=REJECT
HASH_OR_PROVENANCE_MISMATCH=REJECT
```

These are not claims that pypdf currently implements the later wrapper. They are the
minimum negative evidence that must pass before any runtime adoption review. In particular,
this slice does not monkey-patch or otherwise modify the pinned upstream package.

## Reused authority and non-equivalence

```text
CANONICAL_OSS_INTAKE_GATE=REUSED
FILE_INTAKE_SAFETY_GATE=REUSED
PARSER_ISOLATION_BOUNDARY=REUSED
SECOND_SKILL_REGISTRY=0
SECOND_FILE_SAFETY_GATE=0
SECOND_PROVENANCE_AUTHORITY=0
PADIEM_FILE_INTAKE_GATE_SUBSTITUTION=NO
SOURCE_AUDIT_PASS_WITH_RESTRICTIONS=RUNTIME_ADOPTION?NO
```

The existing production Worker parser boundary remains fail-closed when no reviewed isolated
parser authority is composed. This child does not arm that boundary, change the local
reviewed parser, or change the #2925 matrix disposition.

## Safety counters

```text
RUNTIME_ADOPTION=0
RUNTIME_SKILL_REGISTRATION=0
THIRD_PARTY_SKILL_EXECUTION=0
PIP_INSTALL=0
PACKAGE_IMPORT=0
JBIG2DEC_EXECUTION=0
PROVIDER_CALL=0
NETWORK_PROVIDER_CALL=0
SECRET_VALUE_READ=0
SECRET_MUTATION=0
PRODUCTION_DEPLOY=0
PRODUCTION_MUTATION=0
GATE_WEAKENED=NO
```

## Acceptance

```text
SELECTED_BLOCKER=PYPDF_JBIG2DEC
SOURCE_ADVANCE_JUSTIFIED=YES
NEXT_ROOT_BLOCKER=JBIG2DEC_BINARY_PROVENANCE_AND_CHILD_ENV_AUTHORITY
NEXT_CHILD_TITLE=Bound pypdf jbig2dec subprocess/environment authority
DEFAULT_DISABLED=YES
NEGATIVE_CASES_RECORDED=YES
RUNTIME_ADOPTION=0
PRODUCTION_MUTATION=0
CENTRAL_REVIEW_REQUIRED=YES
STOP=YES
```

This artifact is evidence and a fail-closed decision record only. It does not approve
pypdf runtime adoption, optional dependency enablement, or any binary execution.
