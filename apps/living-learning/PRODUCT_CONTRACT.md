# Living Learning Product Contract

## Product Principle

Korean adult AI/Python beginners learn through recurring 10-minute sessions with:
1. First lesson delivery with comprehension tracking
2. Explicit learner feedback
3. Adapted second lesson based on feedback

## Core Flow

```
synthetic learner profile
→ first 10-minute lesson (LessonPlan + LessonContent + exercises)
→ comprehension response
→ explicit feedback
→ adapted second lesson
→ deterministic validation
→ pending_review
→ close
→ privacy-safe pilot evidence
```

## Initial Curriculum

| Concept | Korean | Prerequisites |
|---------|--------|---------------|
| variables | 변수 | None |
| values | 값 | None |
| conditionals | 간단한 조건문 | variables, values |
| python_example | Python 예제 | variables, values, conditionals |

## Feedback Directions

- `reduce_theory` - Request less theory, more examples
- `more_examples` - Request more practice examples
- `code_first` - Request code shown before explanation
- `slower_pace` - Request slower pacing
- `more_review` - Request more review questions
- `simplify_jargon` - Request simplified terminology

## Lesson States

- `input_received` - Initial state
- `generation_pending` - Provider call in progress
- `pending_review` - Generation complete, awaiting close
- `generation_failed` - Provider failed after retries

## Publication States

- `pending` - Not yet closed
- `published` - Available for review
- `closed` - Finalized, immutable

## Safety Requirements

All learner data is synthetic. No real learner identities, payment, or revenue data is used or stored.

## Adaptation Contract

The second lesson must demonstrate visible differences from the first lesson based on feedback:
- Explanation order changes
- Example density changes
- Difficulty adjustments
- Code-first structure when requested
- Exercise/review structure changes

Adaptation is rejected if requested changes are not demonstrably present.