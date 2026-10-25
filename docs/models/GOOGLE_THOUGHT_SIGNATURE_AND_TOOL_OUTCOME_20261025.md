# Google thought signatures on every part, and the executor's own outcome (2026-10-25, #4727)

PR #5818 replayed a tool call's `thoughtSignature` and the `functionResponse` that
answered it. Two facts about the native wire stayed outside that shape, and this
slice closes both. It is stacked on #5818's branch, not a second implementation:
the same translator, the same stream event, the same contract fields.

No live provider call was made here either. Every outbound request below is a
synthetic MockTransport exchange, so this is static/mock evidence. The live echo
remains a post-freeze step with the existing credential and route.

## 1. A signature can belong to the answer text, not only to a call

Provider evidence read 2026-10-25:
`https://ai.google.dev/gemini-api/docs/thinking` — a thought signature "is
metadata that can be attached to any part", and `docs/generate-content/thought-signatures`
requires a follow-up to return the signatures it received.

The channel therefore carries two different tokens, each tied to the part it came from:

| Token | Arrives on | B14 field | Relay |
|---|---|---|---|
| call token | `functionCall` part | `tool_calls[i].signature` | `tool_call` event (unchanged) |
| turn token | the turn's own answer text part | `signature` on the chunk / on the assistant message | same `data:` chunk, new optional key |

- `_GoogleToolStream` reads `thoughtSignature` from a text part as well as from a
  call part. A malformed token is refused the same way in both cases.
- A thinking part (`thought: true`) is still **not** relayed as answer text, so its
  token has no part to travel with. That is a deliberate choice, pinned by
  `test_a_thinking_part_is_still_not_relayed_as_answer_text`: reasoning text stays
  out of the product answer, and the token is not forged onto a different part.
- On a follow-up the turn token returns as `thoughtSignature` on the `text` part it
  signed, and the call token on its own `functionCall` part. A turn with no answer
  text cannot carry a turn token, and is refused before dispatch.
- The merge rule for a turn is the **last token actually seen**, not the last
  frame: an unsigned continuation chunk does not clear a signed one.
- The compatible (completed) lane maps the same value to
  `extra_content.google.thought_signature` at the message level, and canonicalizes
  it back on the way in. Any other provider receives the message it received
  before this field existed, with the field stripped.
- A chunk with no token is byte-identical to the chunk this lane always sent.

## 2. A tool result is not always a completion

`role: tool` carried text only, so a user's refusal, an executor failure, a
cancellation and a permission denial all reached the model in the same shape as a
real result. A result can now carry the executor's own event:

```python
ToolResult.from_execution(
    tool_call_id=call.id, name=call.name, content=text,
    event=the_run.tool_event,   # contracts.ToolEvent, already the P01 record
)
```

The outcome vocabulary is unchanged — `contracts.RunStatus` for the status,
`contracts.ErrorClass` and the bounded `#5015` stage code beside it. No second enum
is created. The five states the product needs:

| Situation | Reported as |
|---|---|
| ran normally | `status: completed` |
| user refused approval | `status: rejected`, `error_code: approval_denied` |
| executor failed | `status: failed`, `error_code: <handler stage code>` |
| run cancelled | `status: failed`, `error_code: cancelled` |
| permission denied | `status: policy_blocked`, `error_class: policy_blocked`, `error_code: <gate>` |

Rules that make the distinction real rather than decorative:

- A non-completion must name its cause. `{"status": "failed"}` alone is refused, so
  four different failures stay four different facts.
- On the native wire a completion answers with `response.result`. Anything else
  answers with `status`, its cause and `detail`, and **never** with `result`, so no
  reader of the part can mistake it for the output the call produced.
- A refusal does not have to invent prose: empty text is accepted when the result
  reports its own failure. A completion still owes the model its text.
- A completed result keeps the exact message it always produced; the outcome block
  appears only on a non-completion.
- The OpenAI-compatible tool message has no outcome field, so on those lanes the
  block is stripped rather than invented. The native wire is the lane that carries it.
- B14 still never executes a tool and still does not decide anything about approval.
  The server's own authentication, permission, approval and idempotency checks are
  unchanged; this only stops a non-completion from being *described* as a completion.

## Consumer connection this slice does not make

`apps/padiem-chat/app/b14_client.py` and `chat_pc_drive.py` are being edited on
open PR #5709, and `pc_query_adapter.py` plus
`apps/padiem-ai-engine/app/claw_pc_query_step_driver.py` are being edited on open
PR #5833 — both #5573 work. The producer and consumer wiring is therefore left to
that owner; the contract it needs is already in place:

1. relay `event.signature` from the stream event onto the assistant turn it stores
   (`ChatToolCall`-shaped projection for the turn's own text),
2. pass that value back as `signature` on the assistant message,
3. build a tool result with `ToolResult.from_execution(..., event=<the ToolEvent the
   runtime already returns>)` instead of flattening the outcome into prose, or pass the
   same projection as `execution` on the result mapping.

Nothing in this slice requires a new gate, a new credential or a storage change.

## Verification

- `apps/korean-ai-platform/tests/test_4727_signature_and_outcome_contract.py` (29):
  both works over the real route and the real translator, including the five
  outcomes as five different provider bodies and the byte-identical unsigned frame.
- `apps/korean-ai-platform/tests/test_4727_google_native_roundtrip.py`,
  `test_4727_b14_native_tool_calling.py`, `test_streaming_gateway.py`,
  `test_5318_b14_call_ledger.py`: unchanged and still green.
- `packages/padiem-ai-core/tests/test_tool_channel.py`, `test_b14_streaming.py`:
  the contract fields, the merge rule and the executor event.
- Reverting the source while keeping the tests fails 20 of the 29 B14 cases and 15
  Core cases, so the assertions are load-bearing rather than descriptive.
- Chat's own streaming suites could not be executed on this machine: their modules
  import `kagent` and `padiem_ai_engine_client`, which are not installed in the
  local B14 virtualenv. `test_core_text_execution_boundary.py` did run (6 passed).
  The Chat suites are CI's to execute.
