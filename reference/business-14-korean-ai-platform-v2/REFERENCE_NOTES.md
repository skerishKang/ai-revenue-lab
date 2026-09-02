# Reference Notes

## Existing Business 14 audit

### Preserve

- Korean-first product language;
- model and Provider distinction;
- BYOK security boundary;
- model catalog metadata;
- OpenAI-compatible endpoint story;
- live versus simulated truthfulness;
- current runtime implementation under `apps/korean-ai-platform/**`.

### Replace

- ten-item permanent sidebar;
- duplicated Home, Playground and Workspace primary journeys;
- warning and Phase labels in every shell region;
- generic dark operations-console styling;
- decorative metric cards;
- fake terminal empty state;
- emoji trust strip;
- mixed Korean/English customer copy;
- repeated rounded-card grids;
- mobile compression without hierarchy change.

## Chosen direction

Business 14 is not presented as an enterprise control plane first. It is a personal developer instrument with progressive complexity.

The start screen owns the first success:

```text
목적 입력
→ 직접 모델 또는 자동 선택
→ 필요한 Provider 키 확인
→ 요청
→ route result
→ code copy
```

The model explorer is list-led rather than card-led. Activity is request-led rather than metric-led. Technical metadata is progressively disclosed.

## Color and material

- background: warm paper neutral and graphite surfaces;
- primary text: ink-black rather than pure white-on-black everywhere;
- route accent: electric persimmon/orange-red used only for active path and primary action;
- status colors remain semantic and include text;
- borders are crisp with minimal shadow;
- radii stay low and nested.

## Typography

Use the system Korean sans stack for reliable local rendering. Headings are compact, not oversized marketing headlines. Monospace appears only for model IDs, endpoints, code and request IDs.

## Density

- Start: spacious, one focal action;
- Models: dense, searchable rows;
- Detail: balanced information and playground;
- Route evidence: diagram plus concise explanations;
- Activity: compact request history.

## Content realism

Synthetic fixtures include realistic Korean tasks, multiple Provider connection states, explicit evidence labels, failed eligibility reasons and request activity over several days.

## Mobile

Mobile is not a scaled sidebar. It uses a top product bar, bottom navigation, focused sheets and a sticky primary action. Model comparison becomes stacked comparison summaries.