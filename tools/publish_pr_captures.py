#!/usr/bin/env python3
"""Publish up to eight PR captures to a private companion repository."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
CAPTURE_LIMIT = 8
BLOCK_START = "<!-- padiem-captures:start -->"
BLOCK_END = "<!-- padiem-captures:end -->"


class PublishError(Exception):
    pass


class CommandError(PublishError):
    def __init__(self, code: str, returncode: int, stderr: str):
        super().__init__(code)
        self.returncode = returncode
        self.stderr = stderr


def run_command(argv: list[str], *, cwd: Path = ROOT, input_text: str | None = None) -> str:
    result = subprocess.run(
        argv,
        cwd=cwd,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode:
        raise CommandError("command_failed", result.returncode, result.stderr)
    return result.stdout.strip()


def run_git(*args: str) -> str:
    return run_command(["git", *args])


def run_gh(gh: str, *args: str, input_text: str | None = None) -> str:
    return run_command([gh, *args], input_text=input_text)


def repo_slug(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        raise PublishError("invalid_repository")
    return value


def sha_value(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", value.lower()):
        raise PublishError("invalid_head_sha")
    return value.lower()


def repository_path(value: str) -> tuple[Path, str]:
    original = Path(value)
    if original.is_symlink():
        raise PublishError("symlink_not_allowed")
    resolved = original.resolve()
    try:
        relative = resolved.relative_to(ROOT.resolve())
    except ValueError:
        raise PublishError("path_outside_repository") from None
    if len(relative.parts) < 3 or relative.parts[0] != "padiem-reports":
        raise PublishError("path_outside_padiem_reports")
    if any(ord(character) < 32 for character in relative.as_posix()):
        raise PublishError("control_character_in_path")
    return resolved, relative.as_posix()


def validate_summary(path: Path, relative: str, head: str) -> dict:
    if path.suffix.lower() != ".json":
        raise PublishError("summary_must_be_json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise PublishError("summary_unreadable") from None
    if not isinstance(payload, dict):
        raise PublishError("summary_must_be_object")
    try:
        run_git("cat-file", "-e", f"{head}:{relative}")
        tracked = run_git("rev-parse", f"{head}:{relative}")
        working = run_git("hash-object", str(path))
    except CommandError:
        raise PublishError("summary_not_tracked_at_head") from None
    if tracked != working:
        raise PublishError("summary_differs_from_head")
    return payload


def image_kind(data: bytes, suffix: str) -> bool:
    if suffix == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if suffix in {".jpg", ".jpeg"}:
        return data.startswith(b"\xff\xd8\xff")
    return len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP"


def validate_captures(values: list[str], summary_relative: str) -> list[dict]:
    if not 1 <= len(values) <= CAPTURE_LIMIT:
        raise PublishError("capture_count_out_of_range")
    captures = []
    seen = set()
    summary_parent = Path(summary_relative).parent
    for value in values:
        path, relative = repository_path(value)
        if Path(relative).parent != summary_parent:
            raise PublishError("capture_outside_summary_directory")
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            raise PublishError("capture_must_be_image")
        if path.is_symlink() or not path.is_file():
            raise PublishError("capture_not_regular_file")
        if relative in seen:
            raise PublishError("duplicate_capture")
        seen.add(relative)
        try:
            data = path.read_bytes()
        except OSError:
            raise PublishError("capture_unreadable") from None
        if not image_kind(data, path.suffix.lower()):
            raise PublishError("capture_signature_invalid")
        captures.append({"path": path, "relative": relative, "data": data})
    return captures


def git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def private_repository(gh: str, repository: str) -> dict:
    raw = run_gh(gh, "api", f"repos/{repository}")
    try:
        metadata = json.loads(raw)
    except json.JSONDecodeError:
        raise PublishError("private_repository_metadata_invalid") from None
    visibility = str(metadata.get("visibility", "")).upper()
    if metadata.get("private") is not True or visibility != "PRIVATE":
        raise PublishError("private_repository_required")
    branch = metadata.get("default_branch")
    if not isinstance(branch, str) or not branch:
        raise PublishError("private_repository_uninitialized")
    return {"branch": branch}


def content_endpoint(repository: str, relative: str) -> str:
    return f"repos/{repository}/contents/{quote(relative, safe='/')}"


def existing_blob(gh: str, repository: str, relative: str, branch: str) -> dict | None:
    try:
        raw = run_gh(
            gh,
            "api",
            "--method",
            "GET",
            content_endpoint(repository, relative),
            "-f",
            f"ref={branch}",
        )
    except CommandError as error:
        if error.returncode and "HTTP 404" in error.stderr:
            return None
        raise
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise PublishError("private_content_metadata_invalid") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("sha"), str):
        raise PublishError("private_content_metadata_invalid")
    return payload


def upload_capture(
    gh: str,
    repository: str,
    branch: str,
    capture: dict,
    pr: int,
    head: str,
) -> str | None:
    existing = existing_blob(gh, repository, capture["relative"], branch)
    if existing:
        if existing["sha"] == git_blob_sha(capture["data"]):
            return None
        raise PublishError("capture_content_conflict")
    payload = {
        "message": f"evidence: PR #{pr} at {head[:12]}",
        "content": base64.b64encode(capture["data"]).decode("ascii"),
        "branch": branch,
    }
    raw = run_gh(
        gh,
        "api",
        "--method",
        "PUT",
        content_endpoint(repository, capture["relative"]),
        "--input",
        "-",
        input_text=json.dumps(payload),
    )
    try:
        result = json.loads(raw)
        commit = result.get("commit", {}).get("sha")
    except (json.JSONDecodeError, AttributeError):
        raise PublishError("private_upload_response_invalid") from None
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise PublishError("private_upload_response_invalid")
    return commit


def latest_evidence_commit(gh: str, repository: str, branch: str, directory: str) -> str:
    raw = run_gh(
        gh,
        "api",
        "--method",
        "GET",
        f"repos/{repository}/commits",
        "-f",
        f"sha={branch}",
        "-f",
        f"path={directory}",
        "-f",
        "per_page=1",
    )
    try:
        commits = json.loads(raw)
        commit = commits[0]["sha"]
    except (json.JSONDecodeError, IndexError, KeyError, TypeError):
        raise PublishError("private_evidence_commit_missing") from None
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise PublishError("private_evidence_commit_missing")
    return commit


def capture_block(
    main_repo: str,
    private_repo: str,
    head: str,
    evidence_commit: str,
    summary_relative: str,
    captures: list[dict],
) -> str:
    lines = [
        "### 캡처 증거 (비공개)",
        "",
        f"- 검증 HEAD: `{head}`",
        f"- 비공개 증거 커밋: `{evidence_commit}`",
        f"- JSON 요약: [{summary_relative}](https://github.com/{main_repo}/blob/{head}/{quote(summary_relative, safe='/')})",
        f"- 캡처: {len(captures)}장 (최대 {CAPTURE_LIMIT}장)",
    ]
    for capture in captures:
        url = f"https://github.com/{private_repo}/blob/{evidence_commit}/{quote(capture['relative'], safe='/')}"
        label = (
            Path(capture["relative"]).name
            .replace("\\", "\\\\")
            .replace("[", "\\[")
            .replace("]", "\\]")
        )
        lines.append(f"- [{label}]({url})")
    return BLOCK_START + "\n" + "\n".join(lines) + "\n" + BLOCK_END


def upsert_block(body: str, block: str) -> str:
    starts = body.count(BLOCK_START)
    ends = body.count(BLOCK_END)
    if starts != ends or starts > 1:
        raise PublishError("capture_markers_invalid")
    if not starts:
        return body.rstrip() + "\n\n" + block + "\n"
    start = body.index(BLOCK_START)
    marker_end = body.index(BLOCK_END)
    if start >= marker_end:
        raise PublishError("capture_markers_invalid")
    end = marker_end + len(BLOCK_END)
    return body[:start] + block + body[end:]


def load_pull_request(gh: str, repository: str, pr: int, head: str) -> dict:
    raw = run_gh(
        gh,
        "pr",
        "view",
        str(pr),
        "--repo",
        repository,
        "--json",
        "body,headRefOid,state,url",
    )
    try:
        pull = json.loads(raw)
        current_head = pull["headRefOid"].lower()
        state = pull["state"]
        url = pull["url"]
    except (json.JSONDecodeError, KeyError, AttributeError):
        raise PublishError("pull_request_metadata_invalid") from None
    if state != "OPEN":
        raise PublishError("pull_request_not_open")
    if current_head != head:
        raise PublishError("pull_request_head_mismatch")
    return {"body": pull.get("body") or "", "url": url}


def linked_capture_paths(body: str, private_repo: str) -> set[str]:
    if BLOCK_START not in body and BLOCK_END not in body:
        return set()
    starts = body.count(BLOCK_START)
    ends = body.count(BLOCK_END)
    if starts != 1 or ends != 1:
        raise PublishError("capture_markers_invalid")
    start = body.index(BLOCK_START)
    end = body.index(BLOCK_END)
    if start >= end:
        raise PublishError("capture_markers_invalid")
    block = body[start + len(BLOCK_START):end]
    paths = set()
    for line in block.splitlines():
        if not line.startswith("- ["):
            continue
        match = re.fullmatch(r"- \[.*\]\((https://github\.com/[^)]+)\)", line)
        if not match:
            raise PublishError("capture_link_invalid")
        parsed = urlsplit(match.group(1))
        parts = parsed.path.split("/")
        if len(parts) < 6 or parts[1:3] != private_repo.split("/") or parts[3] != "blob":
            raise PublishError("capture_link_invalid")
        if not re.fullmatch(r"[0-9a-f]{40}", parts[4]):
            raise PublishError("capture_link_invalid")
        paths.add(unquote("/".join(parts[5:])))
    return paths


def ensure_capture_set(body: str, private_repo: str, captures: list[dict]) -> None:
    existing = linked_capture_paths(body, private_repo)
    requested = {capture["relative"] for capture in captures}
    if len(existing) > CAPTURE_LIMIT:
        raise PublishError("capture_limit_exceeded")
    if existing and existing != requested:
        raise PublishError("capture_set_conflict")


def update_pr_body(
    gh: str,
    repository: str,
    pr: int,
    pull: dict,
    block: str,
) -> str:
    body = upsert_block(pull["body"], block)
    run_gh(
        gh,
        "api",
        "--method",
        "PATCH",
        f"repos/{repository}/pulls/{pr}",
        "--input",
        "-",
        input_text=json.dumps({"body": body}),
    )
    return pull["url"]


def publish(args: argparse.Namespace, gh: str) -> dict:
    repository = repo_slug(args.repo)
    private_repo = repo_slug(args.private_repo)
    head = sha_value(args.head_sha)
    if args.pr <= 0:
        raise PublishError("invalid_pull_request")
    summary_path, summary_relative = repository_path(args.summary)
    validate_summary(summary_path, summary_relative, head)
    captures = validate_captures(args.capture, summary_relative)
    pull = load_pull_request(gh, repository, args.pr, head)
    ensure_capture_set(pull["body"], private_repo, captures)
    metadata = private_repository(gh, private_repo)
    evidence_commit = None
    for capture in captures:
        committed = upload_capture(
            gh,
            private_repo,
            metadata["branch"],
            capture,
            args.pr,
            head,
        )
        evidence_commit = committed or evidence_commit
    if evidence_commit is None:
        evidence_commit = latest_evidence_commit(
            gh,
            private_repo,
            metadata["branch"],
            Path(summary_relative).parent.as_posix(),
        )
    pull = load_pull_request(gh, repository, args.pr, head)
    ensure_capture_set(pull["body"], private_repo, captures)
    block = capture_block(
        repository,
        private_repo,
        head,
        evidence_commit,
        summary_relative,
        captures,
    )
    pr_url = update_pr_body(gh, repository, args.pr, pull, block)
    return {
        "pr": args.pr,
        "pr_url": pr_url,
        "head": head,
        "summary": summary_relative,
        "private_repo": private_repo,
        "evidence_commit": evidence_commit,
        "captures": [capture["relative"] for capture in captures],
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--pr", type=int, required=True)
    result.add_argument("--head-sha", required=True)
    result.add_argument("--summary", required=True)
    result.add_argument("--capture", action="append", required=True)
    result.add_argument("--repo", default="skerishKang/ai-revenue-lab")
    result.add_argument("--private-repo", required=True)
    result.add_argument("--gh", default=None)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    gh = args.gh or shutil.which("gh")
    if not gh and Path(r"C:\Program Files\GitHub CLI\gh.exe").is_file():
        gh = r"C:\Program Files\GitHub CLI\gh.exe"
    if not gh:
        print("PR_CAPTURE_PUBLISH=FAIL reason=gh_unavailable", file=sys.stderr)
        return 2
    try:
        report = publish(args, gh)
    except PublishError as error:
        print(f"PR_CAPTURE_PUBLISH=FAIL reason={error}", file=sys.stderr)
        return 2
    print("PR_CAPTURE_PUBLISH=PASS")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
