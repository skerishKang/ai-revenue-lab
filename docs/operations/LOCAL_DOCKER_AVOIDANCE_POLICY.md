# Local Docker Avoidance Policy

- Status: **CANONICAL OPERATING CONSTRAINT**
- Effective: 2026-09-09
- Scope: repository-wide AI-assisted development and deployment work

## 1. Owner operating preference

The Product Owner does not want Docker Desktop or an equivalent local Docker daemon used as a normal development or deployment dependency.

This preference is an operating constraint, not a suggestion.

```text
LOCAL_DOCKER_DEFAULT = FORBIDDEN
DOCKER_DESKTOP_DEFAULT = DO_NOT_START
LOCAL_CONTAINER_BUILD_DEFAULT = DO_NOT_USE
```

## 2. Required default behavior

When a task appears to require container build or container deployment, agents must first inspect and reuse the repository's established remote path before proposing or starting a local Docker workflow.

Preferred order:

```text
EXISTING_REPOSITORY_WORKFLOW
→ GITHUB_ACTIONS_REMOTE_BUILD
→ CLOUDFLARE_BUILD / REMOTE_REGISTRY / OTHER_EXISTING_REMOTE_BUILD
→ ONLY_IF_NO_VALID_REMOTE_PATH: OWNER_DECISION
```

Do not invent a new local Docker path merely because a vendor tutorial or CLI supports it.

## 3. Cloudflare-specific rule

Cloudflare Workers/Containers work must prefer existing GitHub Actions, Cloudflare build infrastructure, remote registry, or other already-established repository deployment paths.

If Cloudflare Containers are technically required for runtime compatibility, that does **not** imply permission to start Docker Desktop on the owner's machine.

Container runtime choice and local build-tool choice are separate decisions.

## 4. Before asking for Docker

An agent must first verify:

- whether an existing GitHub Actions workflow already deploys to the same Cloudflare account;
- whether repository Cloudflare credentials are already wired through secrets;
- whether a remote build/registry path already exists;
- whether the same product family already uses a non-local-Docker deployment pattern;
- whether a non-container Cloudflare runtime can satisfy the actual runtime constraints without broad rewrite.

Only after those checks fail may Docker be raised as an exception candidate.

## 5. Exception rule

Local Docker may be used only when all of the following are true:

1. the current task cannot reasonably be completed through an established remote build/deploy path;
2. the reason is documented in the issue/work order;
3. the owner is explicitly told why local Docker is unavoidable;
4. the owner gives explicit approval for that specific task.

Silence, prior Docker installation, an available Docker Desktop binary, or a CLI message is not approval.

## 6. Worker reporting

If an implementation worker encounters Docker as a prerequisite, the worker must stop before starting Docker Desktop and report:

```text
LOCAL_DOCKER_REQUIRED = YES/NO
WHY = <technical reason>
EXISTING_REMOTE_PATH_CHECKED = <evidence>
REMOTE_ALTERNATIVES = <list>
OWNER_APPROVAL_REQUIRED = YES
```

## 7. B03 precedent

For B03 Living Fiction, the accepted direction is Cloudflare-based hosting while avoiding local Docker Desktop. If a Container runtime remains necessary because of FastAPI/psycopg compatibility, build and deployment should use the repository's existing remote Cloudflare/GitHub infrastructure rather than starting Docker Desktop locally.

This precedent should be reused for similar future migrations unless a later owner decision supersedes it.
