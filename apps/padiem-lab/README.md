# Padiem Lab

Public, customer-facing portfolio frontdoor for Padiem / AI Revenue Lab.

## Product boundary

`apps/padiem-lab/` and `apps/portfolio-console/` serve different audiences and must remain separate.

```text
Padiem Lab              = public product / experiment discovery
Portfolio Console       = private operator / GitHub / phase console
```

Do not remove Cloudflare Access from the existing Portfolio Console merely to make a public portfolio. The public Lab intentionally does not load the private console manifest, GitHub live status, Issue/PR/CI facts, backend phase state, or work queue.

## Public manifest

`public-businesses.js` is a curated publication manifest, not a mirror of `apps/portfolio-console/business-manifest.js`.

Allowed public fields:

- `number`
- `slug`
- `title`
- `koreanTitle`
- `summary`
- `publicStatus`
- `routeKind`
- `targetPath`
- `currentPublicUrl` when the surface is intentionally public
- `sourcePath` only for repository-public static source

A Business is not added merely because it exists in the internal registry.

## Route classes

```text
LOCAL_STATIC       repository-public static HTML/CSS/JS candidate for /bXX/
EXTERNAL_RUNTIME   independent Worker/app/runtime; Lab links or hands off
PRIVATE_PREVIEW    review-only/private surface; never promoted by default
NOT_PUBLIC         internal, unresolved, or not suitable for public discovery
```

Current Stage 0 deliberately includes only a small selected set. B61 StoryMemory is absent because its source/review boundary is private. B14 and B62 remain independent runtime products. B60 is the first confirmed repository-local static canary candidate.

## Target URL model

Preferred future public hostname:

```text
https://lab.padiem.net/
```

Static candidates eventually converge on:

```text
https://lab.padiem.net/b01/
https://lab.padiem.net/b02/
...
https://lab.padiem.net/b60/
```

Independent runtimes keep their own deployment identity. A `/bXX/` entry may later become a thin customer-facing handoff, but the Lab must not copy backend/auth/runtime code merely to reduce the number of Cloudflare projects.

## Migration sequence

1. Public Lab shell and curated manifest.
2. Verify each existing public URL and customer-first entry.
3. Audit relative/absolute asset paths for one static canary.
4. Copy/package that exact static candidate beneath `/bXX/` in a deploy artifact.
5. Compare the old URL and Lab route in desktop/mobile browsers.
6. Migrate additional static candidates only after the canary passes.
7. Mark redundant Pages projects for decommission only after public parity is proven.
8. Configure the final custom domain and Access boundary separately.

Existing Pages projects are not deleted during the early migration stages.

## Cloudflare boundary

Stage 0 performs no Cloudflare mutation.

Later, the intended split is:

```text
lab.padiem.net                    public / no Portfolio Console Access gate
private operations hostname      private / Cloudflare Access retained
```

The exact private hostname, custom-domain attachment, DNS records, and Access application changes require a separately verified deployment step. Never change the existing Portfolio Console Access policy as a shortcut.

## Source-truth rule

Before adding a Business as `LOCAL_STATIC`, verify that the stated `sourcePath` exists on the exact current `main` and has a customer-facing entry. A stale path in the internal manifest is not enough.

This rule already prevented a stale Business 29 workspace pointer from being copied into the public manifest during Stage 0.
