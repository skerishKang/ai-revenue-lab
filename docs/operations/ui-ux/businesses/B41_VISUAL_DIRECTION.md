# B41 — Foreign Emergency Assistant Visual Direction

Status: `DIRECTION_FROZEN` · Verdict: `REDESIGN`

Fresh systems audit: run `31422952294`, artifact `9076111540`, canonical `https://41-foreign-emergency-assistant.pages.dev/`. Current generic card shell does not differentiate language-first emergency preparation.

`OWNER_UI_APPROVED=false` remains unchanged.

## Product thesis

A foreign-language user organizes essential emergency facts, reviews a translated statement and confirms what can be handed to a human emergency operator. The prototype does not itself connect or dispatch emergency services.

```text
LANGUAGE → FACTS → TRANSLATION DRAFT → CONFIRM → HANDOFF
```

Core object: **the speakable bilingual emergency statement built from structured facts**.

## Reserved territory — Language-First Emergency Phrase Builder

- language choice visible early
- fact tiles for place/person/event/time/need
- assembled source statement + translated statement paired
- missing fact/uncertainty marker
- clear handoff/confirmation boundary

Avoid generic translation chat, map dashboard, automated emergency dispatch button and B39 live-call console duplication.

## Acceptance criteria

1. structured facts visibly build the final statement;
2. source and translated statement remain paired;
3. missing/uncertain information stays visible;
4. handoff is clearly not a real emergency connection in the prototype;
5. Mobile supports fast language/fact entry;
6. current safety and no-dispatch boundaries remain intact.
