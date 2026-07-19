# ADR-0001: Select Personal Edition Daily Letter as the First Revenue Experiment

- Status: Decided
- Date: 2026-07-20
- Related issue: #1

## 1. Decision

The first end-to-end revenue experiment will be **Personal Edition Daily Letter**.

A user provides an unstructured conversation, note, journal entry, voice transcript, or reaction to a previous edition. The system transforms that material into a polished personal publication and delivers it at a deliberate time, normally the next morning. The user's reaction changes the following edition.

This is not a generic chatbot and not a one-time summarizer. It is a recurring personalized publication loop:

```text
raw conversation or note
→ interpretation of intent and personal meaning
→ structured editorial plan
→ polished personal edition
→ delivery
→ explicit reader feedback
→ materially changed next edition
```

The first experiment is deliberately narrow. It tests whether abundant free AI production can create a market-of-one product for which a real user will pay.

## 2. Why this experiment is first

### 2.1 It tests the most advanced project thesis with the least infrastructure

The project thesis progressed through four levels:

1. AI replaces repetitive human work.
2. AI produces quantities humans cannot economically produce.
3. AI reacts while user interest is still active.
4. AI produces a different edition for every person.

Personal Edition tests all four levels without first requiring a global source collector, a large database, a recommendation system, or a community.

### 2.2 It distinguishes a product from a raw AI answer

The same underlying reasoning could be returned in a chat window immediately. The experiment instead tests whether editorial packaging creates additional value through:

- selection;
- structure;
- title and narrative flow;
- visual presentation;
- persistence and archiving;
- deliberate delivery time;
- continuity across editions;
- visible response to prior feedback.

The product metaphor is a letter or personal magazine, not a conversation transcript.

### 2.3 It provides the shortest feedback loop

One user can complete the entire loop quickly:

1. submit material;
2. receive an edition;
3. react;
4. receive a changed edition;
5. decide whether the experience is worth paying for.

No large audience is required to learn whether personalization is real and perceptible.

### 2.4 It creates reusable infrastructure

The same edition engine can later power:

- Living Travel letters;
- Personalized World Feed editions;
- founder strategy letters;
- family newspapers;
- personal memory books;
- fan magazines;
- adaptive learning publications.

The first experiment therefore validates a common product primitive rather than an isolated novelty.

## 3. Target first user

The initial target is an adult who already produces meaningful but unstructured material and values reflection, continuity, or presentation.

Representative early users include:

- founders developing an idea through conversation;
- travelers developing preferences over several days;
- people keeping irregular journals or voice notes;
- researchers or creators recording evolving thoughts;
- family members who want personal records turned into readable editions.

The project owner may be the first operational tester, but revenue validation must come from external users who are not paying themselves.

## 4. Exact MVP input

Each edition accepts:

- 500 to 5,000 words of Korean or English text;
- or a voice transcript of comparable length;
- optional previous-edition feedback;
- optional edition preferences such as tone, length, and recurring topic;
- prior edition metadata needed for continuity.

The MVP does not require direct access to private chat accounts, messaging services, microphones, or cloud drives. Users paste or upload approved text themselves.

## 5. Exact MVP output

Each edition is one polished, mobile-readable web document containing:

1. publication title;
2. edition date and sequence number;
3. an opening editorial paragraph;
4. two to four coherent sections;
5. the most important idea, event, or meaning identified from the input;
6. a short continuity section explaining what changed from the previous edition or feedback;
7. one optional question or choice for the next edition;
8. a clear statement that the edition was generated from the user's supplied material;
9. simple feedback controls.

Initial target length:

- approximately 700 to 1,400 Korean words; or
- an equivalent English length.

The output must not read like meeting minutes, a bullet-only summary, or an AI chat response.

## 6. Feedback mechanism

The reader can respond with both structured and free-form feedback.

Required structured controls:

- continue in this direction;
- make the next edition more practical;
- make the next edition more reflective;
- go deeper on a selected section;
- reduce or exclude a topic;
- change tone or length.

Required free-form field:

- "What should tomorrow's edition understand or change?"

The next edition must explicitly demonstrate at least one material response to the feedback. Merely mentioning that feedback was received is insufficient.

## 7. Delivery model

The model may generate the content within minutes, but the default product experience is scheduled editorial delivery.

Initial delivery rule:

- input and feedback are collected during the day;
- the next edition is delivered the following morning;
- a manual trigger is acceptable during the pilot;
- the generated edition is archived under the user's edition history.

The experiment tests whether delayed, polished delivery feels more valuable than an immediate raw answer.

## 8. Revenue hypothesis

The first economic hypothesis is:

> A user will pay for a recurring personal publication that remembers prior editions and visibly adapts to their feedback, even when generic AI chat is available for free.

Initial paid pilot offer:

- one sample edition may be free;
- seven subsequent daily editions cost KRW 4,900;
- payment may be collected manually during the experiment;
- no payment integration is required for the first pilot;
- the offer must describe the product, not access to an AI model.

The price is intentionally modest because the first objective is evidence of willingness to pay, not optimized revenue.

## 9. Success metrics

The first pilot is considered promising when all critical conditions and most supporting conditions are met.

### Critical conditions

- at least one external user makes a real payment;
- at least two users complete four or more editions;
- at least two users provide feedback on two or more occasions;
- the next edition shows a material and recognizable response to feedback;
- at least 80% of delivered editions are accepted without substantial human rewriting;
- at least 90% of runtime generation calls use free inference.

### Supporting targets

- invite at least 10 qualified prospective users;
- obtain at least 5 sample-edition users;
- convert at least 2 sample users to the paid pilot;
- maintain average human correction time below five minutes per delivered edition;
- achieve at least 60% edition open or confirmed-read rate;
- receive at least one unsolicited request to continue after the pilot;
- record AI calls, provider/model, correction time, and revenue for every edition.

## 10. Failure conditions

The experiment should be reconsidered or stopped when one or more of the following is observed:

- no one pays after 20 qualified external invitations and sample exposure;
- users consistently prefer the raw chat answer to the edited edition;
- readers cannot perceive that feedback changed the next edition;
- average human correction exceeds ten minutes per edition;
- continuity errors or invented personal facts occur repeatedly;
- free models cannot maintain acceptable quality after structured prompting and review;
- users read one edition but show no desire for recurrence.

Failure must be classified as production, quality, packaging, delivery, pricing, or demand failure.

## 11. Quality and privacy boundaries

The first experiment must:

- use only material intentionally supplied by the user;
- avoid inventing memories, relationships, facts, or emotional diagnoses;
- distinguish direct user statements from AI interpretation;
- allow deletion of the user's input and editions;
- exclude secrets, credentials, highly sensitive identifiers, and third-party private information from repository fixtures;
- use synthetic or explicitly approved samples for development and tests;
- record model/provider metadata without storing provider credentials.

The MVP is not intended for medical, legal, mental-health, financial, or crisis guidance.

## 12. Explicit non-goals

The first experiment will not initially build:

- the global information collector;
- live web search and source verification;
- travel booking or affiliate integration;
- a social feed or community;
- public user profiles;
- full authentication infrastructure unless needed for pilot privacy;
- automated recurring billing;
- native mobile applications;
- multiple simultaneous personal magazines per user;
- long-term autonomous personal memory;
- image generation or advanced magazine layout;
- a general multi-product platform.

## 13. Why the other candidates are deferred

### Personalized World Feed

This remains a flagship scale experiment because it demonstrates global coverage, translation, and mass personalization. It is deferred because the first useful version requires source acquisition, update detection, content deduplication, distribution, and a larger discovery surface. Those complexities would make it harder to isolate whether users value the personalized edition itself.

### Living Travel

Living Travel is the preferred second product application. It can reuse the Personal Edition loop while adding destination information, freshness, maps, and eventual affiliate revenue. It is deferred until the project proves that a reader notices and values feedback-responsive editions.

### Living Fiction

Living Fiction may provide the strongest direct-content monetization, but it introduces continuity, world-state, community, canon, reader-choice, and intellectual-property design problems. It should follow the establishment of a reliable feedback-to-next-edition engine.

## 14. Minimum implementation decomposition

The MVP should be split into small issues suitable for a free implementation worker:

1. define edition input, output, and feedback schemas;
2. create synthetic sample conversations and expected quality rubric;
3. benchmark HY3 on editorial-plan and edition-generation tasks;
4. implement a replaceable AI-provider adapter;
5. implement edition generation with deterministic validation;
6. render one responsive edition page;
7. capture structured and free-form feedback;
8. generate the next edition from prior edition plus feedback;
9. record experiment economics and human correction time;
10. document the manual pilot workflow.

## 15. Decision consequence

The project will not begin by building all planned applications. It will first prove one thin loop:

> conversation becomes a polished personal edition; reader feedback becomes a materially different next edition; an external user pays for recurrence.

If this loop succeeds, Living Travel should be the next product specialization and Personalized World Feed should remain the first large-scale information experiment.
