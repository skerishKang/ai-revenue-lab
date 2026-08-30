# B64 AI Reward Router — Product Contract

## Identity

- **Business:** B64
- **Stable slug:** `ai-reward-router`
- **Lifecycle:** incubation
- **Product unit:** earning opportunity
- **Promise:** help a user find realistic, evidence-backed earning routes with the lowest-friction opportunities surfaced first.

## Current owner override — 2026-08-30

The launch sequence is **not** “show every earning category and rank them together.” The product must first finish the lowest-friction earning experience, then progressively unlock later categories.

Current consumer order:

1. **AD / CLICK / VISIT / LOW-FRICTION REWARD** — current P0
2. SURVEY / SHORT REWARD — hidden until later unlock
3. MICROTASK — hidden until later unlock
4. SHORT_GIG / SHORT_PROJECT — hidden until later unlock
5. EXTERNAL_JOB_SEARCH — hidden until later unlock; B64 searches/compares external listings and deep-links rather than owning general job inventory

Until CENTRAL accepts the AD_CLICK_FIRST gate, the default Home, Today Route, primary navigation and default recommendations must not expose the later tiers.

Account signup, publisher approval and production provider activation are **owner actions performed later**. Their absence must not block account-independent technical implementation and must not cause fake/placeholder earning supply. With no live-authorized provider account, the correct consumer state is zero real reward cards.

## Product boundary

B64 is an online-first global side-income and reward router. The first UX may prioritize Korean residents and Korean language, but country, language, currency, eligibility, skills, devices, identity, age, tax, payout, and provider constraints are modeled as data rather than Korea-only assumptions.

The product retains two routing concepts, but the launch view is progressively gated:

- **TODAY ROUTE:** during P0, only immediately actionable AD_CLICK opportunities that pass the fail-closed consumer-card contract. It does not fall back to survey/microtask/gig/job content.
- **INCOME PIPELINE:** preserved as a later product capability; it is not part of the default P0 consumer surface.

The opportunity model remains capable of representing rewards, surveys, research, user testing, AI/data work, translation, remote projects, affiliate/cashback, and future verified online-income categories. Preserving backend capability does not imply immediate consumer visibility.

## Current P0 safety rules

- Generic CPC advertising or a clickable destination is not rewarded-click authority.
- `CLICK` requires explicit evidence that the click itself is an approved incentivized action.
- Automatic clicking, automatic ad viewing, bot participation, impression fraud, click fraud and automated task completion are prohibited.
- Provider/source policy that is pending or unknown cannot activate supply.
- No real reward card is shown before live provider authorization and confirmed reward evidence.
- Client/browser completion is not cash settlement; provider confirmation and payout policy gates remain separate.
- B64 does not create a transferable consumer stored-value wallet or user cash custody for P0.
- Provider credentials and payout-provider access tokens remain server-side only and must never be committed or emitted in diagnostics.

## Trust and ranking rules

- User-value recommendation score and B64 monetization score are separate dimensions.
- Sponsored, affiliate, and partner relationships must be disclosed and must not silently lower user value.
- Unknown payout, availability, eligibility, qualification, confidence, or income values remain unknown; they are never fabricated to complete a card or ranking.
- Realized hourly yield is an evidence-backed outcome metric, not a guaranteed income claim.
- B64 does not promise guaranteed earnings without controlled supply and the required legal and operational controls.
- Acquisition permission is separate from product inclusion. No task authorizes private endpoint scraping, automated applications, automated task completion, or third-party account credential collection.

## Historical W0 foundation boundary

W0 originally did not implement live provider collection, consumer UI, production API, database schema, wallet/payment custody, automatic participation, or deployment. Those statements describe the W0 foundation stage only and must not override later accepted work or the current owner override above.

Current implementation has progressed beyond W0 into source policy, verified inventory, change detection, P0 AD_CLICK integration contracts, consumer P0 view-models, reward-state handling and external fulfillment readiness while keeping real provider activation fail-closed until owner-side account authority exists.
