"""#5895: staged Chat code rollout — upload, partial traffic, smoke, promote/rollback.

The deploy gate used to replace 100% of production traffic in one call and
prove the release only afterwards. This module changes the Chat gate to the
Cloudflare Workers gradual-deployment shape:

    versions upload            -> a new version id, traffic untouched
    versions deploy prev@90 new@10
    settle
    smokes with Cloudflare-Workers-Version-Key: <new>
        pass -> versions deploy new@100
        fail -> versions deploy prev@100   (immediate, before any promotion)

The percentage and the settle wait are deployment-procedure constants, not
work-volume limits (Owner decision 2026-10-28). Binding authority stays with
wrangler.toml and the existing readback steps; this script never edits
bindings, and it never prints a secret.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Callable, Protocol, Sequence

STAGED_TRAFFIC_PERCENT = 10
STAGED_SETTLE_SECONDS = 20
VERSION_HEADER = "Cloudflare-Workers-Version-Key"
_VERSION_ID_RE = re.compile(r"Version ID:\s*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")


class StagedRolloutError(RuntimeError):
    """A bounded refusal; never carries command output or secrets."""


class Result(Protocol):
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[..., Result]


def parse_version_id(output: str) -> str:
    match = _VERSION_ID_RE.search(output or "")
    if match is None:
        raise StagedRolloutError("STAGED_UPLOAD_VERSION_ID_MISSING")
    return match.group(1)


def default_runner(argv: Sequence[str], *, env: dict[str, str] | None = None) -> Result:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        list(argv), capture_output=True, text=True, env=env,
    )


def _last_lines(text: str, limit: int = 20) -> str:
    lines = [line for line in (text or "").splitlines() if line.strip()]
    return "\n".join(lines[-limit:])


def rollout(
    *,
    wrangler: Sequence[str],
    config: str,
    previous_version: str | None,
    percent: int = STAGED_TRAFFIC_PERCENT,
    settle_seconds: int = STAGED_SETTLE_SECONDS,
    smokes: Sequence[Sequence[str]] = (),
    runner: Runner = default_runner,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> str:
    """Upload, send `percent` traffic to the new version, smoke, then finish.

    Returns the promoted version id. On a failed smoke the previous version is
    restored to 100% and StagedRolloutError is raised; the new version is never
    promoted.
    """

    if not 1 <= percent < 100:
        raise StagedRolloutError("STAGED_PERCENT_INVALID")

    upload = runner([*wrangler, "versions", "upload", "--config", config])
    if upload.returncode != 0:
        log("COMMAND=versions_upload RESULT=FAILED")
        log(_last_lines(getattr(upload, "stderr", "")))
        raise StagedRolloutError("STAGED_UPLOAD_FAILED")
    version = parse_version_id(getattr(upload, "stdout", ""))
    log(f"STAGED_VERSION_ID={version}")

    staged: list[str] = [f"{version}@{percent}"]
    if previous_version:
        staged.insert(0, f"{previous_version}@{100 - percent}")
    deploy = runner([*wrangler, "versions", "deploy", *staged, "--yes", "--config", config])
    if deploy.returncode != 0:
        log("COMMAND=versions_deploy_staged RESULT=FAILED")
        log(_last_lines(getattr(deploy, "stderr", "")))
        raise StagedRolloutError("STAGED_DEPLOY_FAILED")
    log(f"STAGED_TRAFFIC_PERCENT={percent}")

    sleep(settle_seconds)

    smoke_env = dict(os.environ)
    smoke_env["B62_STAGED_VERSION_HEADER"] = VERSION_HEADER
    smoke_env["B62_STAGED_VERSION_ID"] = version
    failed = False
    for command in smokes:
        result = runner(list(command), env=smoke_env)
        if result.returncode != 0:
            failed = True
            log("STAGED_SMOKE=FAIL")
            log(_last_lines(getattr(result, "stdout", "")))
            # Both proofs write their own refusal marker to standard error - the
            # one thing a reader needs to tell "Chat is broken" from "this proof
            # could not run". They carry marker names only, no bodies.
            log(_last_lines(getattr(result, "stderr", "")))
            break
    if failed:
        if previous_version:
            rollback = runner([
                *wrangler, "versions", "deploy", f"{previous_version}@100",
                "--yes", "--config", config,
            ])
            if rollback.returncode != 0:
                log("COMMAND=versions_deploy_rollback RESULT=FAILED")
                raise StagedRolloutError("STAGED_ROLLBACK_FAILED")
            log("STAGED_ROLLED_BACK=YES")
        else:
            log("STAGED_ROLLED_BACK=NO_PREVIOUS_VERSION")
        log("STAGED_PROMOTED=NO")
        raise StagedRolloutError("STAGED_SMOKE_FAILED")
    log("STAGED_SMOKE=PASS")

    promote = runner([*wrangler, "versions", "deploy", f"{version}@100", "--yes", "--config", config])
    if promote.returncode != 0:
        log("COMMAND=versions_deploy_promote RESULT=FAILED")
        raise StagedRolloutError("STAGED_PROMOTE_FAILED")
    log("STAGED_PROMOTED=YES")
    log("STAGED_ROLLED_BACK=NO")
    log(f"DEPLOYED_VERSION_ID={version}")
    return version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="b62_staged_chat_rollout.py")
    parser.add_argument("--config", required=True)
    parser.add_argument("--previous-version", default="")
    parser.add_argument("--percent", type=int, default=STAGED_TRAFFIC_PERCENT)
    parser.add_argument("--settle-seconds", type=int, default=STAGED_SETTLE_SECONDS)
    parser.add_argument("--smoke", action="append", default=[])
    parser.add_argument("--wrangler", default="npx --yes wrangler@4")
    args = parser.parse_args(argv)

    try:
        version = rollout(
            wrangler=shlex.split(args.wrangler),
            config=args.config,
            previous_version=args.previous_version or None,
            percent=args.percent,
            settle_seconds=args.settle_seconds,
            smokes=[shlex.split(command) for command in args.smoke],
        )
    except StagedRolloutError as error:
        print(f"STAGED_ROLLOUT=FAIL:{error}", file=sys.stderr)
        return 1
    print("B62_PRODUCTION_CODE_DEPLOY=SUCCESS")
    print("PRODUCTION_MUTATION=1")
    with open(os.environ.get("GITHUB_STEP_SUMMARY", os.devnull), "a", encoding="utf-8") as summary:
        summary.write(f"- staged rollout version: `{version}` (promoted to 100%)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
