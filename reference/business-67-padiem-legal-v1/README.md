# B67 — Padiem Legal (Claw-compatible evidence-grounded research review surface)

```text
LOCAL   = B67-LEGAL
BUSINESS= B67
ISSUE   = #3138  [B67] Padiem Legal — evidence-grounded legal research workspace
PHASE   = STATIC CLAW-COMPATIBLE UX FIRST
BRANCH  = feat/3138-b67-padiem-legal
BASE    = origin/main @ 6fffd5a0e30b7cc96519d42893920da4ad679b3c
```

> **This folder contains no live product.** It is a static, dependency-free
> review surface for a UX decision. Every document, case, quotation, page
> number, and date in it is invented. Nothing here searches, opens, or connects
> to anything.

---

## 1. What this is, and what it is not

Padiem Legal is a **legal vertical incubated on Padiem Claw**. It is not a
separate legal SaaS. The goal is that, once the contracts are validated, it is
absorbed into Padiem Claw as a **Legal workspace / Legal skill** with minimal
churn:

```text
B67 Padiem Legal prototype
        ↓
legal search / Drive / document / evidence contracts validated
        ↓
shared Claw capability components
        ↓
Padiem Claw
  └─ Legal workspace / Legal skill
```

This slice exists to answer one product question: *is the Claw interaction model
a good enough shell for a lawyer?* Everything below is in service of that.

---

## 2. The most important sentence in this product

```text
“AI가 말했기 때문에 믿는 것이 아니라,
 원문을 바로 열어 확인할 수 있기 때문에 쓴다.”
```

> "You don't use it because the AI said so. You use it because you can open the
> original and check."

The screen must communicate verifiability over fluency. Every material claim in
this surface carries a numbered evidence marker, and every evidence card shows
where the claim is anchored. When that anchor cannot be established, the product
**says so instead of answering**.

---

## 3. The layer split (this is the whole point)

The code is split so that deleting `legal/` leaves a fully working, generic,
grounded-research Claw surface with no Legal knowledge at all. That property is
what makes absorption cheap, and it is enforced by tests
(`test_shared_layers_contain_no_legal_domain_logic`).

```text
reference/business-67-padiem-legal-v1/
├── index.html                    shell markup
├── css/                          SHARED-LIKE  → moves to Claw unchanged
│   ├── claw-tokens.css             Claw/Chat design tokens, transcribed
│   ├── claw-shell.css              3-column shell, sidebar, composer, responsive
│   ├── claw-conversation.css       messages, scope chips, run status
│   └── claw-evidence-card.css      evidence card primitive + panel + drawer
├── js/                           SHARED-LIKE  → moves to Claw unchanged
│   ├── claw-shell.js               state store, focus traps, toggle groups
│   └── claw-evidence.js            evidence card renderer + decorator seam
├── legal/                        LEGAL VERTICAL → stays Legal
│   ├── legal-authority.css         authority rail, badge, provenance block
│   ├── legal-authority.js          scopes, authority ranking, fail-closed predicate
│   ├── legal-evidence-provenance.js  the decorator: authority + provenance
│   └── legal-demo.js               state machine binding the two halves
├── data/demo-corpus.js           MOCK DATA ONLY
└── tests/
```

The seam is one function. `ClawEvidence.createRenderer({ decorator })` — the
generic card knows how to draw a numbered, titled, meta-tagged, openable card.
It does **not** know what an authority class or a provenance record is; a
decorator supplies both, and `legal-evidence-provenance.js` is ours.

A non-legal Claw surface (a product-research surface, say) supplies a different
decorator and reuses every line of `claw-evidence.js`.

---

## 4. Honest capability matrix

This is the section that matters most. It is **pinned to a source audit of this
repo**, not to the roadmap. The last column says what the *UI actually shows*
in this static slice.

| Capability | Real state in this repo | Shown in this surface |
|---|---|---|
| Claw UI pattern (shell, composer, cards, responsive, a11y) | **EXISTS** — `apps/padiem-chat/static/*` | Reviewing live |
| Web / deep research runtime | **EXISTS** — `app/grounding.py`, `padiem_ai_core/grounding_runtime.py`; bounded, dedupes, numbers sources, **fail-closed at zero evidence** | NOT WIRED (scope chips only) |
| Claim → evidence graph | **EXISTS** — `evidence_graph.py`; `supports`/`contradicts`/`contextualizes` | NOT WIRED (UI shape only) |
| Independent verification | **EXISTS** — `evidence_verification.py`; VERIFIED/CONTRADICTED/INCONCLUSIVE, self-verification forbidden | NOT WIRED |
| Google Drive READ authority | **EXISTS** as a Core/Engine contract — `drive_capability.py` (`drive.readonly`, name+fullText, trash fails closed, shortcut escape forbidden) | MOCK (side bar is labelled `연결됨 — DEMO`) |
| Drive in Padiem Chat UI | **DOES NOT EXIST** — no chat surface reads Drive files; no Drive port is installed in production code | Not claimed |
| Drive per-case folder scope | **NOT IMPLEMENTED** — this is the Legal gap (#3138 follow-on) | Labelled as the gap |
| PDF native text | **EXISTS** — `document_normalization.py` | MOCK |
| PDF ingest in deployed chat | **FAILS CLOSED** — the production Worker has no installed isolated parser composition (`document_parser_isolation_unavailable`) | Shown as `Worker 격리 파서 미설치` |
| Scanned-PDF OCR | **IMPLEMENTED, NOT REACHABLE** — `kagent/pdf_ocr_fallback.py` is complete and tested (native-first, per-page fallback, original 1-based page numbers preserved) but has **no production call site** | Shown as `KAgent 구현됨 · 호출 지점 없음` |
| DOCX | **EXISTS** — same allow-list, same Worker caveat | MOCK |
| HWPX | **TEXT EXTRACTION ONLY** — `extract_hwpx_text` + `hwpx_skill.py`; the module itself pins `HWPX_FULL_SPEC_SUPPORT = "NO"` and 10 edit operations `NOT_CLAIMED` | Shown as `텍스트 추출만` |
| Legacy `.hwp` | **UNSUPPORTED** — deliberately excluded from the allow-list (OLE2 binary) | Shown as `미지원` |
| Korean official legal API (법령·판례) | **NOT IMPLEMENTED** | MOCK |
| Page/section provenance | **NOT IN THE EVIDENCE GRAPH** — `evidence_graph.py` has no `document_id`/`page`/`section`/`span` field. Locators exist only in the document-segment subsystem (`document_semantics.DocumentLocator`) | Every locator is rendered **marked `미검증`** |
| Durable evidence storage | **DOES NOT EXIST** — `document_evidence_projection.py` states an in-memory port only | Not claimed |

### Claims this surface deliberately does not make

- No live Drive connection, Drive search, or Drive file read.
- No live 법령 / 판례 API.
- No claim that legacy HWP is supported.
- No claim that OCR runs in the product.
- No claim that a page number is verified. It never is, in this slice.
- No output that reads as a legal opinion or legal advice.

---

## 5. The provenance design, and why it is honest

`#3138` asked for a page/section UI that does not look model-generated. The
source audit says something stronger: **the evidence graph cannot supply a page
number at all.** So the UI is built around that truth:

1. A page locator renders **with** its document, its retrieval time, its
   version, and an explicit `미검증` marker — in gold, never in the accent
   colour that marks confirmed citation.
2. Every demo record carries `provenance_verified: false`.
3. Field completeness and provenance verification are reported as **two
   different things**, because a record can be fully populated and still
   unverified.
4. The badge that says `DEMO` sits on the card itself, not only in a global
   banner, so a screenshot of a single card is still honest.

---

## 6. Authority: primary vs secondary

A lawyer must be able to sort trust at a glance. The class is carried by
**three independent signals** so it never depends on hue alone (WCAG 1.4.1):

| Class | Badge | Rail | Meaning |
|---|---|---|---|
| `primary` | **filled** `◆ 1차자료` | solid accent | 법령 · 판례 — the only class that may be cited as legal authority |
| `party` | outlined `▤ 당사자 문서` | solid gold | evidence produced inside the matter |
| `internal` | dashed `✎ 내부 산출물` | muted gold | firm work product — not an authority |
| `secondary` | dashed `◇ 2차자료` | dashed muted | commentary / news / web — reference only |

The panel footer states the rule in one line: **1차자료만 법적 근거로 인용하십시오.**

---

## 7. Fail-closed is the product

The most important screen in this surface is the one where nothing was found:

```text
검증 가능한 근거를 찾지 못했습니다.
현재 선택한 자료 범위에서는 질문을 뒷받침할 수 있는 근거를 확인하지 못했습니다.
[ 검색 범위 바꾸기 ]  [ 내 Drive 확인 ]
```

Design rules for it, all enforced by `verify_visual.py`:

- It is **calm**, never an alarm. The border is `rgba(255,255,255,.10)`; the
  danger palette is explicitly banned here.
- It is **actionable** — two recovery actions, both wired to real state changes.
- It is **honest** — zero evidence cards render alongside it. There is no
  confident answer anywhere near it.
- The system still "responds"; it just does not assert anything. The turn appears
  in the transcript so the history is truthful.

The underlying predicate is `B67Legal.shouldFailClosed()`, which restates the
canonical grounding runtime's zero-evidence rule so the static surface can
*demonstrate* the state. It does not replace the runtime rule.

---

## 8. Reviewable states

All nine states from `#3138` are reachable from the top-bar switcher:

| # | State | Switcher chip | Evidence cards |
|---|---|---|---|
| A | 새 조사 (home) | `새 조사` | 0 |
| B | 통합 검색 결과 | `통합` | 5 |
| C | 공식 법률자료 중심 | `공식` | 1 (official only) |
| D | 내 Drive 문서 검색 | `Drive` | 3 (Drive only) |
| E | PDF page provenance | `페이지` | 5 (all with locators) |
| F | 근거 없음 (fail-closed) | `근거 없음` | 0 |
| G | Drive 미연결 | `미연결` | 0 |
| H | Desktop evidence panel | width-driven, ≥ 921px | same list |
| I | Mobile evidence drawer | width-driven, ≤ 920px | same list |

H and I are not separate data: the **same** list is served by the same code two
ways, which is exactly the property that has to hold before absorption.

---

## 9. Run it

No build step, no dependencies, no network. Any static server works:

```bash
# Threaded server (the stdlib single-threaded one deadlocks a real browser
# opening parallel asset connections — see tests/serve.py header).
python reference/business-67-padiem-legal-v1/tests/serve.py 8899
# → http://127.0.0.1:8899/
```

## 10. Verify it

```bash
# 1. Static contracts (Claw continuity, domain separation, honesty).
#    34 tests, no browser required.
python -m pytest reference/business-67-padiem-legal-v1/tests/test_b67_legal_surface.py -q

# 2. Behaviour in a real browser at 1440x1000, 768x1024, 390x844.
#    Writes screenshots + browser-verification.json to docs/.
python reference/business-67-padiem-legal-v1/tests/verify_browser.py

# 3. Geometry + WCAG contrast audit against the composited background.
python reference/business-67-padiem-legal-v1/tests/verify_visual.py
```

(2) and (3) need the server from step 9 running. All three exit non-zero on
failure.

### What each suite proves

- **`test_b67_legal_surface.py`** — the surface keeps Claw's tokens, breakpoints
  (920/620), 44/48px touch floors, 16px input floor, per-layer reduced-motion,
  single live region, single h1; the shared layers stay free of Legal
  vocabulary; and the honesty claims (unverified locators, HWP unsupported, no
  second Drive/evidence/OCR implementation) cannot be quietly dropped.
- **`verify_browser.py`** — no console errors, no horizontal overflow, all touch
  targets ≥ 44px, every keyboard tab stop shows a focus ring, the evidence
  panel is present at desktop and *absent* at mobile (not squeezed), the drawer
  takes focus on open and returns it to the trigger on Escape, and the
  fail-closed state shows zero evidence cards.
- **`verify_visual.py`** — no clipped text, nothing trapped behind the fixed
  composer, the fixed composer never overlaps the evidence panel, the three
  desktop columns are balanced, and every measured text/background pair clears
  the WCAG floor (4.5:1, or 3.0:1 for large text) against its **composited**
  background.

Screenshots land in `docs/`: `desktop|tablet|mobile-B-unified.png`,
`state-a…g-*.png`, plus `browser-verification.json`.

---

## 11. Accessibility notes

- 44px floor on every touch target; 48px on primary actions; 16px on all text
  inputs (prevents iOS focus zoom).
- Exactly one `aria-live="polite"` region (`#runtimeNote`), never nested.
- The evidence sheet is a real `role="dialog" aria-modal="true"`, `inert` while
  closed, focus-trapped while open, and returns focus to its trigger on Escape.
- The mobile sidebar uses the canonical `inert` + `MutationObserver` pattern from
  `apps/padiem-chat/static/a11y.js` — with one deliberate correction, documented
  in `legal-demo.js`: `DOMTokenList.remove()` calls `setAttribute`, which fires a
  mutation record *even when the value is unchanged*, so an unconditional
  `remove()` inside a class observer deadlocks the renderer. The write is
  guarded and the sync is re-entrancy guarded.
- `prefers-reduced-motion` is honoured per layer, not just globally.
- The authority class is never signalled by colour alone.

---

## 12. Known gaps and follow-on work

Ordered by what blocks the next slice.

1. **Official Korean legal source connector** — new. Nothing exists.
2. **Drive folder-scope adapter** — a bounded per-case workspace boundary over
   the existing Drive READ authority. Must not become a second OAuth authority.
3. **Bridge the KAgent OCR composition** into the shared document path, and
   install an isolated parser composition so the deployed Worker stops failing
   closed on binary documents.
4. **Join `DocumentLocator` onto citations** — this is what would let a page
   number ever be shown as verified rather than as a target.
5. **Claim-to-evidence verifier wiring** — extend the shared Core contract with
   the Legal provenance fields instead of forking it.
6. **Durable evidence storage** — currently in-memory only.
7. **Mobile/PWA hardening** and a lawyer-authored benchmark set with gold
   sources.

## 13. What was explicitly not done

Per the slice boundary: no Production deploy, no DNS, no Cloudflare mutation, no
OAuth scope or credential change, no DB migration, no real Drive connection, no
real legal API, no new OCR engine, no new evidence graph, no new verifier, no
legacy HWP support claim, and no modification to `apps/padiem-chat/`,
`packages/`, or production config.
