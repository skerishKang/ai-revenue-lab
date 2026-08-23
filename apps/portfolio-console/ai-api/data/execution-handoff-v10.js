window.B60_EXECUTION_HANDOFF = {
  authority: {
    business: 14,
    sourceMainSha: '41715f47864ec81650d233c30da98fb7aa1aeed8',
    sourcePaths: [
      'apps/korean-ai-platform/app/pilot/catalog.py',
      'apps/korean-ai-platform/app/pilot/router_core.py',
      'apps/korean-ai-platform/README.md'
    ],
    auditedAt: '2026-08-24',
    rule: 'Exact route identity only. Direct-provider discovery is never treated as equivalent to an OpenRouter-mediated B14 route unless the identifiers and access path match.'
  },
  mappings: {
    'openrouter-free-router': {
      state: 'CONNECTABLE',
      userState: 'ROUTER_MAPPED',
      b14ModelId: 'openrouter/free',
      b14RouteId: 'openrouter:openrouter/free',
      executionProvider: 'OpenRouter',
      credentialMode: 'BYOK_B14_OWNED',
      workspacePath: '/workspace',
      handoffBinding: 'CONTRACT_ONLY',
      targetUrl: null,
      notes: 'Business 14 has an exact openrouter/free manual route. B60 does not collect or persist the Provider key.'
    }
  }
};
