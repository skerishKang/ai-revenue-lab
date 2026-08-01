# Reference notes

Research date: 2026-07-29

Only patterns were studied. No official logo, agency interface, emergency-number branding, call-center script, proprietary form, map, or dispatcher screen is copied.

## Primary references

1. **National 911 Program — Calling 911**  
   https://www.911.gov/calling-911/  
   Adopted: prepare location, nature of the emergency, and concrete details; make clear that emergency assistance is not available through a reference website. Rejected: number branding, live-call framing, operator instructions and any appearance of placing a call.

2. **National 911 Program — Calling 911 FAQ**  
   https://www.911.gov/calling-911/frequently-asked-questions/  
   Adopted: location may need room/building detail; questions follow a sequence; stressful contexts require clear preparation. Rejected: dispatch protocol simulation and call-taker authority.

3. **U.S. Web Design System — Preferred language pattern**  
   https://designsystem.digital.gov/patterns/select-a-language/language-preferences/  
   Adopted: show the language in its native spelling, separate spoken/written preference, provide assistance explicitly, and never use flags or nationality as a language proxy. Rejected: claiming language support that the static reference cannot provide.

4. **CDC Clear Communication Index — Core items and examples**  
   https://www.cdc.gov/ccindex/tool/description-examples-parta.html  
   Adopted: one main message first, active voice, audience words, chunked headings, visible known/unknown distinction, and the most important information in the first section. Rejected: health or behavioral advice, scoring, or a communication-quality guarantee.

5. **W3C WAI — Cognitive and learning accessibility**  
   https://www.w3.org/WAI/people-use-web/abilities-barriers/cognitive/  
   Adopted: consistent labels, predictable navigation, short blocks, simple words, visible structure, no blinking or continuously changing content, and easy correction. Rejected: disability-based credibility, priority or urgency inference.

## Adopted patterns

- Preferred language shown before the report content.
- Native-language name (`Español`) with Korean interface and English support labels.
- One-question-at-a-time confirmation loop.
- User statement, observable synthetic fact and unknown information are visually separate.
- Landmark-based location description preserves exact uncertainty.
- Main message and official handoff boundary are front-loaded.
- Text labels duplicate every status; color alone is never authority.
- Plain-language sequence uses short phrases and consistent order.
- Reduced motion is immediately information-complete.

## Rejected patterns

- Functional call button, dial pad, phone number branding, active-call timer, connected indicator.
- Live microphone, waveform, speech recognition, live translation or accuracy guarantee.
- GPS map, live pin, transmitted location, route or dispatch vehicle.
- Urgency/threat scoring, triage color ladder, advice or response recommendation.
- Flags, nationality, accent or ethnicity as a language/credibility proxy.
- Immigration, identity or legal-status collection.
- Dense operator console, alarmist red alert, fake official seal or agency logo.

## Boundary comparisons

### Business 39 · 112 Real-Time Interpretation

Business 39 is an **operator-side bilingual meaning-preservation surface** for a synthetic call record. Business 41 is a **user-side reporting-preparation surface** before any official connection. It does not imitate a call center, operator workflow, machine transcript, certified interpretation or live relay.

### Business 40 · Emergency Urgency AI

Business 40 is a **professional review surface for urgency-support evidence**. Business 41 never ranks urgency, assigns response priority, predicts threat or recommends dispatch. It only organizes what the user can report and what remains unknown.

### Civic AI Navigator

Civic AI Navigator explains public procedures and next steps. Business 41 is narrower: it structures a single synthetic emergency report and ends at an explicit official emergency-service handoff boundary. It does not provide general public-service navigation.

### Live emergency-service UI

A live emergency-service interface may connect calls, receive location, guide a caller, allocate response resources or display operational status. This reference does none of those things. It is deliberately paper-like, static, synthetic, non-operational and preparation-only.
