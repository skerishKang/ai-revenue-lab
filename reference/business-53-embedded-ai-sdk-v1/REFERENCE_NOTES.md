# Reference notes

Research date: 2026-07-30

## Comparable and adjacent products

### 1. Vercel AI SDK

- Reference: https://ai-sdk.dev/docs/introduction
- Adopted: provider-independent concepts, structured outputs and clear separation between core capability and UI integration.
- Rejected: documentation-site composition, code-first presentation and any implication that Business 53 publishes a usable package.
- Decision: show a versioned integration contract without code samples or provider activation.

### 2. Microsoft Copilot Studio web/native integration

- Reference: https://learn.microsoft.com/en-us/microsoft-copilot-studio/publication-integrate-web-or-native-app-m365-agents-sdk
- Adopted: host application remains authoritative; integration requires explicit security, permissions and host-side decisions.
- Rejected: chatbot canvas, connection strings, authentication setup and live channel publication.
- Decision: make the insertion point and permission-not-granted state visible while keeping installation withheld.

### 3. Google Genkit

- Reference: https://firebase.google.com/docs/genkit
- Adopted: one bounded capability can be described through typed input, structured output and provider-independent application logic.
- Rejected: full-stack framework claims, deployment flows and model-provider unification as a Business 53 responsibility.
- Decision: visualize one small host capability contract, not a general AI application framework.

### 4. Google Gen AI SDK

- Reference: https://cloud.google.com/vertex-ai/generative-ai/docs/sdks/overview
- Adopted: version and host-compatibility metadata are part of integration readiness.
- Rejected: API keys, credentials, endpoint selection and model migration.
- Decision: version labels remain synthetic and compatibility remains limited rather than guaranteed.

### 5. Amazon Bedrock AgentCore Gateway

- Reference: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html
- Adopted: governed boundaries, request/response interception and policy outside the embedded capability.
- Rejected: gateway topology, observability dashboard and model/tool routing.
- Decision: express fail-closed behavior and host non-mutation without becoming Business 54 or a gateway product.

## Editorial and information-design references

### IBM Design Language — 2x Grid

- Reference: https://www.ibm.com/design/language/2x-grid/
- Adopted: visible engineered grid, repeated measurements and strong spatial rhythm.
- Rejected: IBM branding, logo, typeface dependency and direct visual imitation.

### IBM Design Language — Technical diagrams

- Reference: https://www.ibm.com/design/language/infographics/technical-diagrams/design/
- Adopted: concise nodes, explicit connectors, restrained color coding and diagram labels outside crowded shapes.
- Rejected: library components or proprietary pictograms.

### IBM Design Language — Layout overview

- Reference: https://www.ibm.com/design/language/layout/overview/
- Adopted: asymmetry balanced by rigorous alignment, visible scaffolding and engineered geometry.
- Rejected: a generic enterprise dashboard shell.

### IBM Data Visualization principles

- Reference: https://www.ibm.com/design/language/data-visualization/overview/
- Adopted: understandable, essential and contextual information with no gratuitous metrics.
- Rejected: charts that imply measured runtime performance or production evidence.

## Final visual decisions

- Product metaphor: an integration desk where a host blueprint, insertion slot, contract sheet, permission cut-line and release sign-off are physically reviewed.
- Palette: blueprint navy, drafting paper, inspection orange, permission red, review brass and restrained mint for preserved host state.
- Typography: system sans plus monospace for contracts and version labels; no remote fonts.
- Density: document-dense but not dashboard-dense; labels remain readable within 30–90 seconds.
- Mobile: a single 390px brief rather than shrinking the full desktop desk.
- Motion: the capability crosses review stations but never crosses the permission/install boundary; the final seal appears only after the actual last animation.

## Product distinctions

- Business 14 owns model access; Business 53 keeps model/provider not connected.
- Business 48 owns independent verification; Business 53 shows human release authority but performs no independent validation.
- Business 50 owns private-data connection; Business 53 accepts only one selected synthetic notice and grants no permission.
- Business 54 owns model routing; Business 53 has no provider selection or routing surface.
