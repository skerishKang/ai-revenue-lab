# Business 14 Product Language Policy

Status: **Canonical product-wide policy**  
Applies to: **all Business 14 phases, applications, user surfaces, operator surfaces, APIs, and documentation**

## 1. Product-market basis

Business 14 is a Korea-first AI Provider platform for Korean developers, companies, public institutions, and other domestic users.

The product exists to make domestic and overseas AI models easier to discover, compare, connect, govern, and understand in a Korean operating context. The language policy is therefore a product-market decision, not a temporary convenience for a small or internal user group.

## 2. Canonical and default language

- Canonical product locale: Korean (`ko-KR`).
- Default UI locale: Korean.
- First visit must render Korean.
- Missing locale state must resolve to Korean.
- Invalid or unsupported locale state must resolve to Korean.
- Server-rendered error and fallback states must also default to Korean.

This rule applies equally to:

- Phase 0 API Provider Demo;
- Phase 1 BYOK Gateway;
- Phase 2 multi-provider routing;
- model catalog and Playground;
- User Workspace;
- Operator Console;
- onboarding, settings, help, validation, errors, privacy, security, cost, and billing guidance;
- future Business 14 phases and product extensions.

## 3. English support

English may be provided as an explicit secondary locale.

- English must not become the default merely because a browser or technical dependency uses English.
- A language switch may allow the user to select English.
- The selected locale may be stored in a browser cookie or local preference when implemented.
- Missing English translations fall back to Korean.
- Korean content must never be blocked while waiting for English localization.
- Full Korean/English parity is not a default feature-completion or merge requirement unless a separate issue explicitly requires it.

## 4. Korean-first delivery rule

New work is completed in this order:

1. Korean product terminology and information architecture;
2. Korean user and operator flows;
3. Korean validation, error, privacy, security, cost, and policy explanations;
4. Korean accessibility and browser verification;
5. optional English localization.

English copy may be added or improved later from the accepted Korean source of truth.

## 5. Technical-English boundary

The following may retain standard English identifiers when required:

- API paths and JSON field names;
- source code and command examples;
- HTTP and protocol terminology;
- Provider, company, and model proper names;
- environment-variable names;
- industry-standard abbreviations.

However:

- the explanation of those identifiers must be Korean by default;
- navigation, instructions, warnings, form labels, and result interpretation must be Korean by default;
- technical English must not make the primary product experience English-first.

## 6. Acceptance requirements

Every new Business 14 user-facing surface must verify:

- Korean is rendered on first visit;
- missing locale preference renders Korean;
- invalid locale preference renders Korean;
- English is used only after explicit selection when an English locale exists;
- untranslated English-locale strings fall back to Korean;
- user and operator error states remain understandable in Korean;
- mobile and desktop layouts support Korean text without clipping or horizontal overflow.

## 7. Documentation authority

This policy is referenced by and applies to:

- `README.md`;
- `API_PROVIDER_PHASE0_CHARTER.md`;
- `BUSINESS14_DECISION_LOG.md`;
- all Phase charters and runbooks;
- Issues #80, #105, #114, #127, and #131;
- later Business 14 issues and PRs.

A later issue may add stricter localization requirements, but it must not silently change the Business 14 default language away from Korean.
