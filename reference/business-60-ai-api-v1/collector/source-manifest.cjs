'use strict';

module.exports = [
  {
    id: 'vercel-glm52-model', signalId: 'vercel-glm52', provider: 'Vercel AI Gateway', authority: 'PRIMARY_OFFICIAL',
    url: 'https://vercel.com/ai-gateway/models/glm-5.2',
    claims: [
      { field: 'model', pattern: 'zai\\/glm-5\\.2', flags: 'i', value: 'zai/glm-5.2', required: true },
      { field: 'context', pattern: '(?:1\\.0M|1M|1,000,000)', flags: 'i', value: '1M tokens' },
      { field: 'price', pattern: 'Route requests across multiple providers', flags: 'i', value: 'Varies by routed provider' },
      { field: 'freeLabel', pattern: '\\$5[\\s\\S]{0,160}(?:30 days|30-day)', flags: 'i', value: '$5 credits / 30 days' }
    ]
  },
  {
    id: 'google-gemini-pricing', signalId: 'google-gemini-free', provider: 'Google AI for Developers', authority: 'PRIMARY_OFFICIAL',
    url: 'https://ai.google.dev/gemini-api/docs/pricing',
    claims: [
      { field: 'freeLabel', pattern: 'free tier', flags: 'i', value: 'Free tier', required: true },
      { field: 'price', pattern: 'free tier', flags: 'i', value: 'Free tier available' }
    ]
  },
  {
    id: 'cloudflare-workers-ai-pricing', signalId: 'cloudflare-workers-ai-free', provider: 'Cloudflare', authority: 'PRIMARY_OFFICIAL',
    url: 'https://developers.cloudflare.com/workers-ai/platform/pricing/',
    claims: [
      { field: 'freeLabel', pattern: '10,?000[\\s\\S]{0,80}neurons[\\s\\S]{0,80}(?:day|daily)', flags: 'i', value: '10,000 neurons / day', required: true },
      { field: 'price', pattern: '\\$0\\.011[\\s\\S]{0,80}1,?000[\\s\\S]{0,40}neurons', flags: 'i', value: '10,000 neurons/day free; $0.011/1,000 above allocation' }
    ]
  },
  {
    id: 'groq-free-rate-limits', signalId: 'groq-free-plan', provider: 'Groq', authority: 'PRIMARY_OFFICIAL',
    url: 'https://console.groq.com/docs/rate-limits',
    claims: [{ field: 'freeLabel', pattern: 'free plan', flags: 'i', value: 'Free plan', required: true }]
  },
  {
    id: 'groq-billing-faq', signalId: 'groq-free-plan', provider: 'Groq', authority: 'PRIMARY_OFFICIAL',
    url: 'https://console.groq.com/docs/billing-faqs',
    claims: [{ field: 'dealType', pattern: '(?:developer tier|payment method|billing)', flags: 'i', value: 'PERMANENT_FREE' }]
  },
  {
    id: 'openrouter-pricing', signalId: 'openrouter-free-router', provider: 'OpenRouter', authority: 'PRIMARY_OFFICIAL',
    url: 'https://openrouter.ai/pricing',
    claims: [{ field: 'freeLabel', pattern: '50[\\s\\S]{0,40}requests[\\s\\S]{0,30}(?:day|daily)', flags: 'i', value: '50 requests / day', required: true }]
  },
  {
    id: 'openrouter-free-router', signalId: 'openrouter-free-router', provider: 'OpenRouter', authority: 'PRIMARY_OFFICIAL',
    url: 'https://openrouter.ai/openrouter/free/',
    claims: [
      { field: 'model', pattern: 'openrouter\\/free', flags: 'i', value: 'openrouter/free', required: true },
      { field: 'context', pattern: '200K|200,000', flags: 'i', value: '200K router context' },
      { field: 'price', pattern: '\\$0[\\s\\S]{0,80}(?:prompt|completion)', flags: 'i', value: '$0 prompt · $0 completion on free router' }
    ]
  }
];
