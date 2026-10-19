# COM2 B62 touch Chromium canary (Issue #5210)

The normal B62 Unified Browser QA remains GitHub-hosted. This opt-in canary is a separate trusted main workflow and does not alter required checks, running services or hosted fallback.

COM2 host bootstrap (trusted operator only): install `ops/com2-ci/padiem-ci-b62-touch-check` as `/usr/local/sbin/padiem-ci-b62-touch-check` with root:root mode 700, copy the already verified `run-mobile.sh` script to `/usr/local/share/padiem-ci/b62-touch-run.sh` as root:root mode 644, and allow the `padiem-ci` runner identity passwordless sudo **only** the exact check binary. Keep this installation outside any PR checkout. Image is the prebuilt trusted `padiem-b62-touch-ci:5210`, pinned by image ID.

Use workflow dispatch with open same-repo PR number and exact head SHA. PR content is checked out without persisted credentials and can only enter the container as read-only data. Network is disabled; process has no capabilities, no privilege gain, resource limits and tmpfs-only outputs. Hosted lanes are not removed until success/failure canary proofs are obtained. The root wrapper verifies input SHA and immutable image identity before invoking Docker.
