# COM2 connector watch (#82)

Owner standard 4: **a stop is known within ten minutes.** The GitHub-side watch
(`.github/workflows/connector-lane-watch.yml`, #6140) reads the lane's status route and
Chat's health from one runner region. This unit watches the two things that exist only
on the executor's own machine, plus a **second vantage** on Chat:

| read | source | why it cannot come from GitHub |
|---|---|---|
| process alive / restarted | `systemctl show ActiveState,NRestarts,ExecMainStatus` | systemd state is host-local |
| watchdog restarts (#6099, exit 87) | the same properties | the exit code is host-local |
| `line_blocked_total` / `line_cleared_total` (#6106) | the executor's own journal line | the counters never leave the process |
| Chat health | `GET https://chat.padiem.net/health` from COM2 | a second region/network path |
| queue lane state | `POST http://127.0.0.1:8797/api/claw/connector/mesh-reads/lane-status` + `/health`, when `PC_QUEUE_BACKEND=com2` | the queue binds loopback, so only this host can read it |

After the cutover the queue is the live store. The host then asks it with the same
read-only secret the GitHub-side watch uses, and judges with the **same module**
(`connector_lane_watch.py`, installed beside this script by `install.sh`) so a rule
cannot drift between the two watchers.

Verdict: one `HOST_WATCH=<ok|unknown|stall> ... reasons=...` line in the journal, and a
notification **only when the state word changes**. The notifier reuses the names the
Chat worker already uses (`B66_ALERT_TELEGRAM_BOT_TOKEN` / `_CHAT_ID`,
`B66_ALERT_DISCORD_WEBHOOK_URL`). With none configured it prints and reports
`HOST_WATCH_NOTIFY=not_configured` — it never claims to have told anybody.

Alongside the verdict the watch prints one count line for the refused exchanges in the
same journal window:

```
HOST_WATCH_REFUSALS chat=0 queue=3 unattributed=0 window_minutes=5
```

`chat` and `queue` are the legs the executor named when it asked; `unattributed` is a
refusal printed without a leg, which is what an installed executor older than the field
produces — counted as unknown rather than guessed at, because guessing is how the
2026-10-30 cutover attempt read an edge bot block as a Worker failure. These are counts of
lines in text that was read, so `0` is a real zero, not `unknown`.

Facts that keep the verdict honest:
- `unknown` is not health: an unread counter, an unreadable systemd state, an absent
  health answer are all `unknown`, and `unknown` never becomes `ok`.
- a restart is a stall **only** when the last exit status is 87 (the #6099 watchdog).
  A deploy restart is reported and is not a stop.
- nothing here restarts, writes or claims anything in the lane.

## Install (on COM2, WSL2, as root)

```bash
# from a checkout of this repository
cd deploy/host-com2/connector-watch
./install.sh                 # creates the user, installs units, enables the timer
$EDITOR /opt/padiem/connector-watch/.env   # fill the notifier names
systemctl start padiem-connector-watch.service
journalctl -u padiem-connector-watch.service -n 20
```

The installer refuses while the unit is active, and it will not overwrite an existing
`.env`. First run prints `reason=restarts_N_first_observation`: that run sets the
baseline and does not raise a restart verdict.
