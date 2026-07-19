# Product Workspaces

Each directory under `apps/` is an independent revenue experiment with its own implementation, tests, configuration, and evidence.

| Workspace | Status | Primary hypothesis |
|---|---|---|
| `personal-edition` | Active implementation | A user will pay for a recurring polished publication that visibly adapts to prior feedback. |
| `living-travel` | Active design | Travel content becomes more valuable when each edition adapts to the reader's latest interests and situation. |
| `world-feed` | Active research | Abundant free AI can turn global-local information into a different personal world edition for each user. |
| `living-fiction` | Active design | Shared fictional worlds can support rapid feedback-responsive and optionally personal narrative branches. |

## Boundary

A product may not place implementation files in the repository root. Product-specific code belongs inside its own workspace.

Common code is not extracted until at least two working products demonstrate the same requirement and an architecture decision approves the extraction.
