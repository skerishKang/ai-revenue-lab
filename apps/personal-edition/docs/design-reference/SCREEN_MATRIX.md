# Screen Matrix

## Participant flow

| # | Screen | Route | State |
|---|--------|-------|-------|
| 1 | Intro | / | Product introduction with hero CTA |
| 2 | Access | /preview/participant/access | Private access entry |
| 3 | Empty | /preview/participant/empty | No records yet |
| 4 | Input received | /preview/participant/input-received | Record accepted |
| 5 | Input form | /preview/participant/input | Write new record |
| 6 | Reviewing | /preview/participant/editing | AI draft under review |
| 7 | Published | /preview/participant/published | Edition published |
| 8 | Edition read | /preview/participant/editions/1 | Read published edition |
| 9 | Feedback form | /preview/participant/editions/1/feedback | Submit feedback |
| 10 | Feedback thanks | /preview/participant/editions/1/feedback/thanks | Feedback complete |
| 11 | History | /preview/participant/history | Past editions |
| 12 | Transformation | /preview/participant/transformation | Source to published |
| 13 | Feedback adaptation | /preview/participant/editions/1/adaptation | Next edition diff |

## Operator flow

| # | Screen | Route | State |
|---|--------|-------|-------|
| 1 | Operator access | /admin/access | Login entry |
| 2 | Queue | /admin/ | Pending editions |
| 3 | Participant context | /admin/participants/modal-preview-user | Source records |
| 4 | AI draft | /admin/review/modal-preview-edition | Draft content |
| 5 | Evidence | /admin/review/modal-preview-edition/evidence | Generation evidence |
| 6 | Content review | /admin/review/modal-preview-edition/content | Structured review |
| 7 | Publish decision | /admin/review/modal-preview-edition/publish | Publish or reject |
| 8 | Feedback history | /admin/participants/modal-preview-user/feedback | Past feedback |

## Clickable transitions

Each screen links to the next state in the flow.
Static preview uses synthetic data — no form submissions.
