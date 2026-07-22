# AI Revenue Lab

AI Revenue Lab is a private product and research repository for proving a specific business hypothesis:

> AI can do more than reduce cost. Abundant free and high-volume AI inference can create new personalized digital products and generate direct revenue.

## Core thesis

Industrial production made one product cheap enough for millions of people. AI-native production can make millions of different editions, one for each person.

The project therefore focuses on four capabilities:

1. **Volume** — produce information and content at a scale that human teams cannot economically sustain.
2. **Speed** — react to events and user feedback within minutes or hours.
3. **Personalization** — turn common source material into a different edition for each user.
4. **Revenue evidence** — measure whether AI-produced outputs create traffic, subscriptions, purchases, or other direct revenue.

## Repository model

This repository is the portfolio-level workspace. Each revenue experiment has an independent product directory under `apps/`.

```text
apps/
├─ personal-edition/          # active first implementation
├─ living-travel/             # active product-design track
├─ world-feed/                # active information-research track
├─ living-fiction/            # active narrative-design track
└─ personal-video-archive/    # Business 13 incubation track
```

Product-specific code, tests, configuration, migrations, scripts, and fixtures must remain inside the corresponding workspace. Shared code is extracted only after at least two working products demonstrate the same requirement.

See:

- `apps/README.md`
- `docs/decisions/ADR-0002-product-workspaces.md`

## Initial product tracks

- **Personal Edition** — conversations and life records edited into recurring letters, magazines, and books. This is the first active revenue experiment.
- **Living Travel** — travel letters that adapt to the reader's daily feedback.
- **World Feed** — a personalized global-local information feed.
- **Living Fiction** — serialized stories whose optional branches react to reader choices and comments.
- **Personal Video Archive (Business 13)** — user-defined topic feeds for newly published YouTube videos, combined with private viewing reflections, plans, ratings, tags, and records.

## Operating model

- Product vision, architecture, issue decomposition, acceptance criteria, documentation, and final review are handled with the strongest available reasoning and review capability.
- Free and high-volume models are the default implementation workforce once tasks are precisely specified.
- Runtime content production should prefer replaceable free or low-cost models.
- Strong paid models may be used for exceptional design, diagnosis, or final audit, but the project must record where and why they were used.
- Models must remain replaceable through provider adapters rather than being embedded directly into product code.

## Current status

- portfolio and governance documents established;
- Personal Edition selected as the first revenue experiment;
- product-specific workspace structure established;
- Personal Edition implementation contract and HY3 benchmark established;
- implementation begins with GitHub Issue #3 under `apps/personal-edition/`;
- Personal Video Archive registered as Business 13 incubation under `apps/personal-video-archive/` with Issue #60;
- other product tracks continue in parallel through research and product contracts, not speculative code.

## Governance rule

Every experiment must record:

- cash infrastructure cost;
- paid AI cost;
- free-model usage;
- human work time;
- generated outputs;
- user engagement;
- direct or attributable revenue.

The goal is not to prove that one model is best. The goal is to determine whether abundant AI production can create economically valuable products that would not be viable with human production alone.
