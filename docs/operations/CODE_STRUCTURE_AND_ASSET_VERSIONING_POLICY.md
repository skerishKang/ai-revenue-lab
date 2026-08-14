# Code Structure and Asset Versioning Policy

- Status: **CANONICAL**
- Effective: 2026-08-14
- Parent design authority: `PORTFOLIO_DESIGN_OPERATING_SYSTEM.md`

## 1. Purpose

Keep a product's current visual authority obvious in source. A redesign must converge toward a canonical system rather than accumulating generations of CSS, assets and emergency overrides.

## 2. One active visual authority

A user-facing product should have one identifiable current visual-system entrypoint or a small documented set of current modules.

The steady-state pattern below is prohibited:

```text
old-base.css
+ v2.css
+ v3.css
+ v4-fix.css
+ v5-authority.css
+ v6-completion.css
+ v7-polish.css
+ route-emergency.css
```

Historical files may remain in Git history or an explicitly non-loaded archive. They must not all remain load-bearing in the live cascade.

## 3. Redesign replacement rule

When a new system passes the anchor and archetype gates:

1. identify which old selectors/contracts still serve behavior;
2. migrate/re-express those contracts in the canonical current system;
3. remove superseded visual layers from the active load path;
4. retain only bounded compatibility hooks that do not control current appearance;
5. delete or archive redundant emergency overrides when safe;
6. run visual and regression QA after consolidation.

A redesign is not complete if its appearance depends on winning a cascade war against rejected generations.

## 4. Recommended frontend structure

Technology may vary, but substantial frontend work should separate concerns with discipline similar to the Business 06 reference:

```text
styles/
  tokens.*
  base.*
  typography.*
  layout.*
  components.*
  states/
  journeys/
scripts/
  state/
  navigation/
  interactions/
assets/
  images/
  icons/
  media/
ASSET_SOURCES.md
```

Small products may use fewer files. The requirement is clear authority and bounded responsibility, not file-count ceremony.

## 5. File-size and responsibility rule

Prefer authored/materially modified frontend files at or below roughly 500 physical lines. When a file materially exceeds that, split it by stable responsibility unless a documented reason makes a single file clearer.

Do not split only to satisfy a number; do not allow one giant `polish.css` to become the unreviewable authority for every route.

## 6. Tokens before overrides

Shared decisions belong in tokens or clearly named system rules:

- colors/materials;
- typography families and scales;
- spacing;
- radii;
- shadows/borders;
- motion durations/easing;
- container widths;
- z-index layers.

Route-specific composition may differ, but should consume the same system where appropriate.

## 7. `!important` policy

`!important` is allowed only for a documented bounded reason such as third-party/reset containment or a temporary migration boundary.

Repeated `!important` escalation between internal visual generations is a blocker for design-system completion. Consolidate specificity/source order instead.

## 8. Typography dependency policy

Do not claim deterministic typography by merely listing a preferred font family that may not exist on the user's machine.

For each product define:

- display family role;
- body/UI family role;
- reading serif role if any;
- actual delivery method or verified system fallback;
- Korean fallback behavior;
- weight availability;
- licensing/source basis for any shipped font asset.

Never commit or distribute unlicensed/private font binaries. Never source product fonts from an unrelated private runtime/container.

If the chosen family is not shipped, review the real fallback on target browsers rather than assuming the first family is rendered.

## 9. Asset source policy

Every material external or generated asset must have a source/usage record when applicable:

- source URL/tool/origin;
- author/provider when known;
- license/usage basis;
- transformation/crop notes;
- intended surface;
- whether attribution is required.

Repository-local status alone is not proof of rights or quality.

## 10. Asset quality and versions

Do not keep multiple nearly identical visual-generation assets active only because each redesign added another folder.

When an asset is superseded:

- update current references;
- remove it from the live build/load path;
- retain history through Git rather than runtime clutter unless a real product state needs both.

Version query strings should identify the current deployable bundle/cache revision, not encode an ever-growing list of abandoned art directions.

## 11. Compatibility and regression tests

Historical class names/test hooks may be retained when removing them would create unnecessary functional regression risk, but:

- mark them as compatibility hooks;
- do not let them dictate current composition;
- update stale visual assertions to the current canonical contract rather than hiding old visuals in live markup;
- do not weaken behavioral/security assertions to make a redesign pass.

## 12. Visual cascade audit before full-surface pass

For a substantial redesign record:

- active CSS/style entrypoints in load order;
- obsolete visual generations removed or still active with reason;
- duplicate/conflicting typography definitions;
- duplicate component authorities;
- significant `!important` hotspots;
- external font/image dependencies;
- current asset-source manifest.

`FULL_SURFACE_VISUAL_PASS` should not be granted while obvious generation-cascade debt is responsible for visible inconsistencies.

## 13. Build/deploy integrity

Production builders must package only intended current assets/styles and must preserve route/runtime contracts. Preview/debug chrome must not leak into Production.

Cache-busting/versioning must not create a different visual source tree from the exact reviewed revision.

## 14. B01 remediation implication

Business 01 currently demonstrates why this policy exists: multiple historical V3/V4/V5/V6/V7 styles are loaded in the participant path, and the successful Entry required a later route-specific authority layer.

The next B01 system-recovery implementation should treat consolidation as part of the archetype/system work. The goal is not to add V8; it is to make the accepted B01 direction the canonical active system and retire superseded visual control from the live cascade.
