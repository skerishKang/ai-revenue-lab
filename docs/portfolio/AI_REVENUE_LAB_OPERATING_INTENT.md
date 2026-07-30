# AI Revenue Lab Operating Intent

- Status: canonical portfolio intent
- Owner: AI Revenue Lab portfolio governance
- Related: `README.md`, Issue #154, Issue #326

## 1. Why this repository exists

AI Revenue Lab exists to test a business hypothesis, not merely to accumulate prototypes:

> Abundant AI production can create personalized digital products that are economically impractical for human teams to produce, and those products can generate measurable direct or attributable revenue.

The repository is therefore both a product portfolio and an operating laboratory.

Its work must move toward real evidence:

```text
product hypothesis
→ bounded product implementation
→ working deployed service
→ user behavior and operating-cost evidence
→ revenue or attributable-value evidence
→ continue, revise, pause, or stop
```

A larger number of files, screens, prompts, agents, or deployments is not success by itself.

## 2. Capabilities under test

The portfolio tests whether AI changes the production economics of software and digital media through:

1. **Volume** — more useful outputs than a human team can economically sustain.
2. **Speed** — shorter time from decision to working product and from feedback to the next result.
3. **Concurrency** — multiple implementation, research, validation, and operations workers acting in parallel under clear contracts.
4. **Real-time reaction** — current events, operational state, and user feedback changing the next output quickly.
5. **Personalization** — the product itself or its next edition changes for each user, not merely the ranking of a fixed catalog.
6. **Revenue evidence** — cost, engagement, conversion, purchase, subscription, or other attributable business value is measured honestly.

## 3. Portfolio structure

AI Revenue Lab is one portfolio experience containing independently operated Businesses.

Each Business owns its:

- product boundary and user promise;
- code and tests;
- private-data boundary;
- product-local identity and authorization;
- database and retention contract;
- deployment and secrets;
- operating evidence;
- business decision to continue, revise, pause, or stop.

The future user-facing Portal provides shared identity, catalog, account, and launch behavior. It does not merge every Business into one database, one administrator role, or one generic interface.

Shared code is extracted only after implemented products prove a stable common requirement. Premature abstraction must not slow independent product experiments.

## 4. Execution principle

The default execution loop is:

```text
clear product decision
→ smallest useful scope
→ AI implementation and independent validation
→ exact-head approval
→ merge to main
→ dedicated Production deployment
→ immediate Production acceptance
→ retain or rollback
→ record product and business evidence
```

The system should reduce owner effort and repeated manual checking. A process that repeatedly asks the owner to copy status, click configuration screens, or re-audit facts that can be obtained through an authenticated API is operating incorrectly.

## 5. Purpose of governance and phase gates

Governance exists to keep experiments truthful and bounded. It is not intended to maximize ceremony or delay deployment.

UI, UX, backend, deployment, and business approval remain separate because one type of evidence must not be misrepresented as another:

- a polished UI is not a complete user journey;
- a complete UX is not backend authorization;
- a merged PR is not a human product verdict;
- a deployment is not proof of product quality or revenue;
- an authenticated account is not authorization for every Business.

Within an explicitly authorized scope, operators should proceed without repeated minor approval questions.

## 6. Deployment doctrine

After explicit deployment authorization, the default is direct deployment of the validated `main` SHA to the dedicated Business Production project.

```text
validated main
→ Production
→ smoke and acceptance checks
→ keep or rollback
```

Preview or staging is optional and must have a concrete reason, such as:

- destructive migration rehearsal;
- billing or payment risk;
- high-risk authorization changes;
- regulated or compliance-sensitive review;
- an external reviewer who must not access Production;
- an explicit owner request.

Preview infrastructure failure must not become a general blocker when Production has a safe direct-deploy and rollback path.

Before Production changes, record the known-good rollback authority. Roll back immediately when a critical availability, authorization, data-integrity, credential-leakage, or runtime gate fails.

## 7. Portfolio Console intent

Portfolio Console is the private owner and operator control tower for AI Revenue Lab. It is not the user-facing Portal and not merely a Business-number directory.

Its purpose is to let the owner determine, with minimal manual investigation:

- what Businesses exist and what each one promises;
- what is actually deployed and reachable;
- what is being built or reviewed now;
- what Issue, PR, exact SHA, CI result, and phase verdict are authoritative;
- what is blocked;
- what action should happen next;
- what products are producing engagement, cost, and revenue evidence.

The Console must combine two different kinds of information:

### Deliberate authority

Changed only through reviewed decisions:

- Business number and identity;
- product boundary;
- portfolio priority;
- human UI, UX, backend, deployment, and business verdicts.

### Automatically synchronized facts

Updated from approved read-only sources without manual copying:

- Issue and PR state;
- exact head and default-branch SHA;
- Draft and merge state;
- CI and check result;
- deployment and service health facts when connected;
- synchronization time, stale state, and source errors.

The Console must not invent product completion, priority, or approval from raw GitHub counts. Automation supplies facts; humans retain business judgment.

## 8. Console operating standard

A correct Console implementation should:

- render useful static authority data immediately;
- merge live facts when available;
- remain usable when GitHub or another source is unavailable;
- use bounded server-side caching rather than repeated browser calls;
- keep credentials and private infrastructure details outside browser responses;
- avoid periodic manual edits for volatile Issue, PR, CI, and SHA facts;
- point directly to the evidence needed for the next decision;
- eventually include cost, engagement, deployment, and revenue evidence rather than stopping at software-delivery metadata.

The Console is successful when it reduces operating work and shortens the time from portfolio fact to owner decision.

## 9. Owner interaction standard

Operators must prefer authenticated API or CLI execution over repeated owner Dashboard actions.

Before requesting an owner-only action:

1. verify that the API or existing connector cannot perform it;
2. inspect the actual current interface or authoritative contract;
3. group required actions into one bounded request;
4. never invent menu, button, or permission names;
5. never ask the owner to paste passwords, OTPs, cookies, private keys, or tokens into chat.

The owner should make product and risk decisions. The system should handle routine execution.

## 10. Evidence and business decisions

Every implemented Business should progressively record:

- cash infrastructure cost;
- paid AI cost;
- free or local model usage;
- human work time;
- generated outputs;
- deployment and reliability evidence;
- user engagement;
- direct or attributable revenue;
- the next continue, revise, pause, or stop decision.

The final purpose is not to prove that a particular model, framework, or deployment platform is best. It is to determine whether abundant AI production can create valuable products that would not otherwise be economically viable.
