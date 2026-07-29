# Reference notes

Research date: 2026-07-30

The product is deliberately framed as an integration-fit and authority artifact, not as an API catalogue, chatbot builder or code playground.

## Comparable product references

### 1. Vercel AI SDK UI and tool calling

- Sources: https://ai-sdk.dev/docs/ai-sdk-ui/overview and https://ai-sdk.dev/docs/ai-sdk-core/tools-and-tool-calling
- Adopted: separate UI integration concerns from model-side tool declarations; make tool inputs, outputs and approval boundaries inspectable.
- Rejected: presenting a framework API reference, streaming playground or live provider connection.
- Decision: the capability state shows a bounded cartridge with typed synthetic input/output, while the package retains `MODEL / PROVIDER — NOT SELECTED`.

### 2. CopilotKit provider, headless UI and host-controlled MCP apps

- Sources: https://docs.copilotkit.ai/reference/components/CopilotKit and https://docs.copilotkit.ai/guides/mcp-apps
- Adopted: an embedded AI surface lives inside a host-controlled subtree and must respect host UX, permissions and workflow boundaries.
- Rejected: a universal copilot overlay, autonomous action surface or copied CopilotKit chrome.
- Decision: the host cutaway makes the proposed mount point subordinate to the unchanged host product.

### 3. Cloudflare Agents SDK client integration

- Sources: https://developers.cloudflare.com/agents/getting-started/adding-agents-to-existing-projects/ and https://developers.cloudflare.com/agents/api-reference/client-api/
- Adopted: distinguish host/client integration, transport events and typed contracts from the runtime that may later execute them.
- Rejected: WebSocket status, live agent state, durable storage or deployment claims.
- Decision: event rails are documentation-only and callbacks remain synthetic history.

### 4. shadcn registry

- Sources: https://ui.shadcn.com/docs/registry and https://ui.shadcn.com/docs/registry/getting-started
- Adopted: package integration material as inspectable code/config artifacts rather than a sealed black box.
- Rejected: install commands, package-manager affordances or a component marketplace.
- Decision: the final artifact is an installation-readiness binder, explicitly `NOT INSTALLED`.

## Editorial and design-system references

### GitHub Primer

- Sources: https://primer.style/product/components/ and https://primer.style/accessibility/foundations/accessibility-fundamentals/
- Adopted: compact labels, strong information hierarchy, semantic composite controls and visible keyboard focus.
- Rejected: GitHub branding, dark developer-console styling and repository-specific navigation.

### GOV.UK Design System

- Sources: https://design-system.service.gov.uk/components/ and https://design-system.service.gov.uk/accessibility/
- Adopted: explicit guidance and warnings around reusable components; accessible components do not remove the need for host-specific testing.
- Rejected: government-service branding, page templates or portal composition.

### Stripe Apps design guidance

- Sources: https://docs.stripe.com/stripe-apps/design and https://docs.stripe.com/stripe-apps/style
- Adopted: an embedded application should respect host-provided components, design tokens and constrained surfaces.
- Rejected: payments, commerce, Stripe shell patterns and proprietary visual identity.

### IBM Carbon accessibility guidance

- Source: https://carbondesignsystem.com/guidelines/accessibility/developers/
- Adopted: semantic structure, text alternatives, predictable behavior and accessibility review as an ongoing responsibility.
- Rejected: enterprise dashboard density and Carbon component styling.

## Visual decisions

- Product metaphor: a physical fit bench where an unchanged host frame receives a proposed, removable capability cartridge.
- Palette: graphite host frame, warm drafting paper, safety orange, inspection green and electric cyan measurement marks.
- Typography: Korean-first editorial headlines, compact engineering labels and monospaced contract values.
- Density: high-information workshop folios rather than generic cards.
- Motion: `Host-Surface-to-Approved-Embed-Contract`, ending only on the final binder animation.

## Product distinction

- Business 14 provides Korean-first model access and BYOK; Business 53 defines how a bounded capability fits inside an existing host.
- Business 32 creates reusable organizational skills; Business 53 packages a host integration contract.
- Business 48 owns reusable verification and approval mechanics; Business 53 records integration-specific authority and fallback boundaries.
- Businesses 49 and 50 connect data sources; Business 53 accepts only an explicit host context envelope.
- Business 51 distributes workflows; Business 53 is not a marketplace.
- Business 54 selects models; Business 53 leaves model/provider selection outside the embed contract.

## Explicit rejections

- generic API documentation or endpoint tables;
- chatbot or copilot dashboard;
- model-router topology;
- app-builder canvas;
- autonomous action state;
- live installation, model call, credential, telemetry or storage implication;
- copied product UI or third-party branding.
