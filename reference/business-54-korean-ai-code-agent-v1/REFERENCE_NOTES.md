# Reference notes

Research date: 2026-08-02

Only official product documentation and the upstream repository were used for the initial product framing.

## 1. OpenCode

Sources:

- https://opencode.ai/docs
- https://github.com/anomalyco/opencode
- https://github.com/anomalyco/opencode/blob/dev/LICENSE

Observed patterns:

- terminal, desktop and IDE-extension surfaces;
- multi-provider configuration;
- agent modes and subagent concepts;
- repository-local tool access;
- open-source distribution under MIT.

Adopted:

- personal developer as the primary operator;
- explicit Plan and Build modes;
- provider-independent agent concept;
- compact workbench rather than a business dashboard.

Rejected:

- copying the upstream interface or product name;
- implying affiliation;
- reusing source code in this Phase;
- presenting local execution as sandboxed without an actual sandbox.

Reuse boundary:

No OpenCode source is copied in the Phase 1 demo. A later implementation decision must preserve MIT copyright and licence notices for any reused code and state non-affiliation when required.

## 2. Cursor agent and background-agent documentation

Sources:

- https://docs.cursor.com/ko/background-agents
- https://docs.cursor.com/background-agent

Observed patterns:

- visible foreground/background agent status;
- repository environment setup;
- ability to inspect status, send follow-up work and take over;
- stronger risk boundary for automatic command execution and remote environments.

Adopted:

- current step, failure and next action remain visible;
- user interruption and final acceptance are first-class;
- future background execution is treated as a separate security and infrastructure milestone.

Rejected:

- remote background execution in the initial demo;
- automatic terminal commands;
- AWS/remote-machine assumptions;
- enterprise-first information hierarchy.

## 3. OpenRouter

Sources:

- https://openrouter.ai/docs/quickstart
- https://openrouter.ai/docs/guides/routing/provider-selection

Observed patterns:

- one OpenAI-compatible API for many models;
- model and Provider routing through request preferences;
- ordered Provider selection and fallbacks;
- price, throughput and latency ordering;
- data-collection and zero-data-retention constraints;
- BYOK and account-level usage concepts.

Adopted through Business 14:

- one platform dependency rather than duplicated provider logic inside Business 54;
- manual and automatic routing;
- hard data/privacy constraints before soft cost or speed preferences;
- explicit fallback and no-safe-route states;
- visible route evidence.

Rejected:

- turning Business 54 into another model marketplace;
- provider-logo wall as the primary UI;
- silent fallback without user-visible policy;
- claiming real cost or performance from synthetic data.

## 4. Differentiation

```text
OpenCode/Cursor category strength
+ Korean-first personal task language
+ Business 14 unified model platform
+ local-first and external fallback control
+ plan/edit/test/diff evidence
+ user acceptance before application
```

The Phase 1 visual system uses an original Personal Agent Workbench composition. It does not copy a competitor screen, colour system, icon set, logo or layout.
