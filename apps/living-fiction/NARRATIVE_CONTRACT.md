# Living Fiction Narrative Contract

- Status: Design approved for research; implementation deferred
- Date: 2026-07-20
- Related issue: #15

## 1. Product definition

Living Fiction is an AI-native serialized-story product with two simultaneous properties:

1. readers share a common canonical world and can discuss the same central work;
2. readers may receive optional branches, viewpoints, and personal editions that respond rapidly to their choices and feedback.

The product is not a generic prompt-to-story tool. It is a recurring publication system with continuity, declared canon, reader participation, editorial control, and measurable payment behavior.

```text
canonical world state
→ shared episode
→ reader choice, vote, or feedback
→ editorial interpretation
→ canonical continuation and/or optional branch
→ continuity validation
→ publication
```

## 2. First experiment

The first experiment is a short original speculative mystery season.

Working title: **The City That Loses an Hour**

The title, names, and setting are project-created placeholders and must not imitate an existing franchise or living author's distinctive style.

### Core premise

Every night at midnight, the city of Seorin loses exactly one hour from public memory and official records. Clocks advance, but residents cannot remember what happened. An archive clerk discovers handwritten records proving that some people remain conscious during the missing hour.

### First-season scale

- one shared opening;
- five canonical episodes;
- two explicit choice points;
- two optional branches per choice point;
- one character-viewpoint edition;
- one personal completed-edition offer;
- text only during the first experiment.

## 3. Target first reader

An adult serialized-fiction reader who:

- enjoys mystery, speculative fiction, or character-focused serials;
- is willing to read short frequent episodes;
- wants some influence without requiring total control;
- can distinguish official canon from optional branch content;
- is willing to comment, vote, or make explicit choices;
- may pay for faster episodes, branches, viewpoint editions, or a compiled personal edition.

## 4. Canon model

Canon is the shared factual layer of the fictional world.

Canonical records include:

- world rules;
- established history;
- character identities and fixed traits;
- confirmed relationships;
- locations;
- timeline events;
- discovered clues;
- unresolved questions;
- irreversible canonical events;
- episode sequence;
- official current state.

A canonical fact cannot be changed merely because a reader requests a preferred outcome.

### Canon levels

#### Core canon

World rules and major historical facts. Changes require an explicit editorial revision and version record.

#### Episode canon

Events published in the shared mainline episodes.

#### Provisional canon

Details introduced but not yet relied upon by later events. They may be clarified but not silently contradicted.

#### Non-canon branch

An explicitly labeled alternative path that does not change shared mainline history.

#### Personal edition state

Reader-specific preferences, branch selections, viewpoint choices, and presentation settings. It cannot rewrite the canonical database.

## 5. Reader input types

Reader participation is divided into distinct input classes.

### Explicit choice

The story presents a bounded decision such as:

- enter the archive alone;
- call a trusted colleague;
- hide the discovered ledger;
- report it to the city authority.

The selected choice may create a branch or determine a planned canonical vote.

### Community vote

Readers vote among editorially approved options. The winning option may affect a future canonical episode only when the choice is declared canonical before voting.

### Comment and reaction

Free-form responses communicate:

- confusion;
- emotional response;
- pacing preference;
- interest in a character or clue;
- continuity-error reports;
- prediction;
- request for more detail.

Comments are evidence for editorial decisions, not direct commands.

### Personal preference

A reader may ask for:

- more or less reflection;
- more of one character's viewpoint;
- shorter or longer episodes;
- lower or higher suspense within declared content limits;
- fewer romance elements;
- more investigation detail.

These preferences may affect personal editions without changing shared canon.

## 6. Editorial-control rule

The system must not blindly optimize for the loudest or largest group.

### Must be acted upon

- factual continuity errors;
- wrong names, dates, locations, or relationships;
- inaccessible or malformed text;
- content outside declared safety and age boundaries;
- accidental contradictions with canon.

### May influence future work

- pacing;
- viewpoint emphasis;
- amount of explanation;
- character curiosity;
- unresolved clues readers want explored;
- optional branch demand.

### Remains under authorial/editorial control

- theme;
- final canonical ending;
- central moral conflict;
- planned irreversible events;
- long-term clue structure;
- world rules;
- whether majority preference should be frustrated for narrative purpose.

Every feedback application record states whether the input was corrected, adopted, deferred, redirected to a branch, or rejected.

## 7. World-state records

Minimum structured records:

### StoryWorld

- world identifier and version;
- premise;
- genre and content limits;
- world rules;
- canonical timeline;
- current canonical episode;
- unresolved global questions.

### Character

- character identifier;
- canonical name and aliases;
- role;
- age category;
- established traits;
- goals;
- knowledge state;
- relationship edges;
- location and status;
- first and last canonical appearances.

### Location

- location identifier;
- physical properties;
- access rules;
- known history;
- connected locations;
- current canonical state.

### CanonEvent

- event identifier;
- episode and sequence;
- participants;
- location;
- preconditions;
- outcome;
- irreversible effects;
- clues introduced or resolved;
- supporting episode segments.

### StoryBranch

- branch identifier;
- parent canonical point;
- branch type: community, optional, or personal;
- triggering choice;
- divergence state;
- allowed canonical references;
- branch-only events;
- branch status and ending;
- explicit non-canon label when applicable.

### ReaderState

- anonymous or participant identifier;
- selected branches;
- preferred viewpoints;
- tone and length preferences;
- read episodes;
- submitted choices and feedback;
- personal-edition history.

ReaderState contains no inferred sensitive identity traits.

## 8. Episode generation contract

Every generated episode requires:

- episode identifier and type;
- canonical or branch status;
- predecessor state;
- allowed world-state records;
- required event or editorial objective;
- prohibited contradictions;
- target length and tone;
- content boundary;
- unresolved questions that may or may not advance;
- structured scene plan;
- continuity references;
- generated prose;
- post-episode state changes;
- next reader choice when applicable.

The model must not decide canon status. The editorial workflow supplies it.

## 9. Continuity validation

An episode is rejected when it:

- changes a core world rule without approved revision;
- revives a canonically dead character without an explicitly non-canon mechanism;
- gives a character knowledge they have not acquired;
- places one character in incompatible simultaneous locations;
- changes established relationships without an event;
- resolves a clue inconsistently with retained evidence;
- references a branch-only event in mainline canon;
- claims reader feedback was applied when no material change exists;
- copies or closely imitates protected characters, settings, or distinctive prose;
- contains undeclared sexual, violent, or other restricted content;
- produces raw HTML or executable material.

Deterministic rules validate identifiers, timeline order, status, knowledge, location, and branch ancestry. Model review may flag softer thematic or prose issues but cannot override deterministic failures.

## 10. Response-time model

AI may generate candidates in minutes. Publication timing is an editorial product decision.

### Shared canonical episodes

- planned release window: daily or several times per week;
- reader feedback cutoff is declared;
- canon validation and human review occur before publication;
- rapid generation allows late feedback to be considered without eliminating editorial review.

### Optional branches

- target availability: within 10 to 60 minutes after a bounded choice when the branch contract is prevalidated;
- still requires automated continuity gates;
- human review may be sampled only after quality evidence supports it.

### Personal editions

- target availability: immediate to next morning depending on product positioning;
- may alter viewpoint, emphasis, reflection, and branch path;
- cannot alter shared canon.

The experiment records whether faster delivery increases completion, return, and payment.

## 11. Prototype opening

The following is an original structural prototype rather than a finished commercial episode.

### Shared opening

At 12:59 a.m., archive clerk Mina Seo stamps the final municipal record of the day. The second hand crosses midnight. Every clock in the building jumps to 2:00 a.m.

Her coworkers continue packing as though nothing happened. Mina alone remembers hearing someone knock from inside the sealed basement archive during the missing hour.

On her desk is a ledger she did not retrieve. Its first page contains tomorrow's date and one sentence in her own handwriting:

> Do not let Director Han open Room Thirteen.

Established opening canon:

- the city loses one hour at midnight;
- most people do not remember it;
- Mina remembers at least part of it;
- a sealed basement archive exists;
- the ledger has tomorrow's date and resembles Mina's handwriting;
- Director Han and Room Thirteen exist;
- the origin and truth of the warning remain unresolved.

## 12. Canonical next episode prototype

Episode objective: Mina verifies that the ledger and Room Thirteen are real without resolving who wrote the warning.

Canonical events:

1. Mina checks the archive inventory and finds Room Thirteen absent from the current plan.
2. An older paper plan includes the room but marks it closed 21 years earlier.
3. Director Han requests the basement master key without explaining why.
4. Mina hides the ledger rather than confronting him.
5. Security footage contains a one-hour gap but one audio frame of Mina saying a name she does not recognize.

This becomes mainline canon regardless of optional reader branches.

## 13. Explicit reader-choice branches

At the end of the canonical episode, the reader chooses how Mina investigates before the next shared episode.

### Branch A — Enter alone

Mina uses the copied basement key before midnight. The branch emphasizes physical exploration, suspense, and her incomplete memory.

Branch-only events cannot be referenced by later canonical episodes unless editorially promoted through a declared canon decision.

### Branch B — Call colleague Jun

Mina tells records technician Jun only about the missing security audio. The branch emphasizes trust, dialogue, and analysis of the unidentified name.

Jun does not automatically learn about the ledger unless the branch explicitly includes that disclosure.

Both branches return to a compatible state before the next shared episode or remain clearly separate.

## 14. Character-viewpoint edition

Optional edition: Director Han's viewpoint during the same night.

It may reveal:

- that he expected the archive clock to jump;
- that he fears Room Thirteen;
- that he recognizes the ledger's binding.

It may not reveal the final origin of the missing hour unless the canonical story plan authorizes that revelation.

The edition is labeled as canonical viewpoint, non-canon possibility, or personal interpretation before publication.

## 15. Feedback-application example

Reader feedback:

> Jun is more interesting than the investigation. Show why Mina trusts him, but do not turn the story into romance.

Permitted response:

- the next personal edition includes a short prior-work memory explaining their professional trust;
- dialogue between Mina and Jun receives more space;
- romance remains excluded according to the reader preference;
- no existing relationship fact changes.

Applied-feedback record:

- request: deepen Jun and professional trust;
- action: add viewpoint and prior-work context;
- canonical effect: none unless separately approved;
- personal effect: increased Jun emphasis and reduced romance signals;
- visible evidence: identified sections.

## 16. Rejected-request example

Reader request:

> Reveal that Mina's dead sister is alive and secretly running the city.

Assume later canon has conclusively established the sister's death and its physical evidence.

Required response:

- reject the request as a canonical change;
- optionally offer a clearly labeled non-canon alternate-world branch;
- do not quietly retcon the death;
- explain that personal choice cannot overwrite established shared canon.

Other rejected inputs include requests for copyrighted-franchise characters, imitation of a living author's style, sexual content involving minors, hateful targeting, or content outside the declared audience boundary.

## 17. Authorship and disclosure

The service must disclose:

- that AI materially generated or transformed the text;
- the level of human editorial review;
- whether an episode is canon, community-selected, optional, or personal;
- whether reader input influenced the result;
- which organization owns the project-created world and text;
- how reader-submitted ideas may be used.

Reader submissions remain governed by explicit terms. The service must not imply that every commenter becomes a coauthor or receives ownership merely because feedback was considered.

The project must preserve prompt, model, review, and revision provenance for commercial outputs.

## 18. Intellectual-property boundaries

The first experiment uses only original project-created characters, settings, and story material.

Prohibited:

- continuing an existing copyrighted novel, film, game, comic, or franchise without authorization;
- using protected character names or distinctive worlds;
- requesting close imitation of a living author's style;
- training or publishing from unlawfully obtained full texts;
- presenting user-submitted copyrighted material as project-owned;
- concealing AI involvement where platform or consumer disclosure is required.

Similarity review must be part of the release process for titles, premises, characters, and major plot elements.

## 19. Revenue hypothesis

> Readers will pay for a high-frequency serialized world that combines shared discussion with rapid optional branches and personal editions.

Initial offers to test:

- shared five-episode season: first episode free, remaining season KRW 3,900;
- branch pass: KRW 1,900 for both optional choice paths;
- character-viewpoint pass: KRW 1,900;
- personal completed edition: KRW 4,900;
- community vote participation remains free during the first pilot.

The first test should select one primary paid offer rather than simultaneously optimizing all options.

## 20. Success metrics

Critical:

- at least one external reader makes a real payment;
- at least five readers finish the opening episode;
- at least three readers make an explicit choice;
- at least two readers return for three or more episodes;
- readers can correctly distinguish canon from branches;
- no accepted episode contains a critical continuity error;
- at least 90% of generation calls use free inference.

Supporting:

- episode completion above 60%;
- median branch turnaround below 30 minutes after an approved choice;
- average human correction below ten minutes per accepted short episode;
- at least one unsolicited request for another branch, viewpoint, or season;
- blind reviewers recognize material response to feedback;
- shared discussion remains possible despite personalization.

## 21. Failure conditions

- readers cannot understand what is canon;
- personalization fragments the audience so completely that shared discussion disappears;
- reader choices produce only superficial wording changes;
- continuity correction consumes more time than human drafting would;
- free models repeatedly invent or contradict world state;
- readers enjoy voting but will not pay for the story product;
- rapid publication reduces quality below an acceptable level;
- the premise or text is materially derivative of protected work.

Failure is classified as narrative, continuity, participation, packaging, pricing, production, or IP failure.

## 22. Benchmark tasks

Before implementation, candidate free models should be tested on:

1. extraction of world state from the opening;
2. generation of a valid scene plan;
3. canonical episode drafting;
4. two branch drafts with correct ancestry;
5. viewpoint transformation without unauthorized revelation;
6. feedback-responsive revision;
7. continuity-error detection;
8. repair from validator feedback;
9. refusal or redirection of prohibited requests.

Each task is scored separately. A model may be approved for drafting but not for continuity validation or canon decisions.

## 23. Implementation gate

No Living Fiction application should be built until:

- the narrative records and canon rules are reviewed;
- the opening and prototypes pass originality review;
- at least one free model passes limited narrative tasks;
- one primary payment offer is selected;
- continuity correction time is estimated;
- disclosure and reader-submission terms are defined;
- the Personal Edition feedback engine provides evidence about recurring personalized content.

The first implementation, when approved, should use a retained original story packet and deterministic world-state tests before any public community features.
