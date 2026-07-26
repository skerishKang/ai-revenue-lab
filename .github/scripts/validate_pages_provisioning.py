#!/usr/bin/env python3
"""Fail-closed validation for approved Business Pages provisioning."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Mapping

BUSINESS_RE = re.compile(r"^[0-9]{2}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
POSITIVE_RE = re.compile(r"^[1-9][0-9]*$")
SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"


class ValidationError(RuntimeError):
    pass


def positive(value: Any, name: str) -> str:
    if isinstance(value, bool) or not POSITIVE_RE.fullmatch(str(value or "")):
        raise ValidationError(f"{name} must be a positive integer")
    return str(value)


def validate_target(business: str, project: str, source: str, branch: str) -> None:
    if not BUSINESS_RE.fullmatch(business) or business == "00":
        raise ValidationError("business_id must be two digits from 01 through 99")
    if len(project) > 63 or not re.fullmatch(
        rf"ai-revenue-business-{re.escape(business)}-{SLUG}", project
    ):
        raise ValidationError("project_name is not the dedicated project for this Business")
    if source.startswith(("/", "\\")) or ".." in source or "\\" in source:
        raise ValidationError("source_directory contains a forbidden path form")
    if any(ord(char) < 32 for char in source) or not re.fullmatch(
        rf"reference/business-{re.escape(business)}-{SLUG}/?", source
    ):
        raise ValidationError("source_directory is not isolated to this Business")
    if branch != "main":
        raise ValidationError("production_branch must be exactly main")


def validate_inputs(
    business_id: str,
    project_name: str,
    source_directory: str,
    approved_sha: str,
    approval_pr: str,
    production_branch: str,
) -> None:
    validate_target(business_id, project_name, source_directory, production_branch)
    if not SHA_RE.fullmatch(approved_sha):
        raise ValidationError("approved_sha must be a lowercase 40-character SHA")
    positive(approval_pr, "approval_pr")


def repository_metadata(payload: Mapping[str, Any], expected: str) -> dict[str, str]:
    try:
        expected_owner, expected_name = expected.split("/", 1)
    except ValueError as exc:
        raise ValidationError("GITHUB_REPOSITORY must be owner/name") from exc
    owner = payload.get("owner")
    if not isinstance(owner, Mapping):
        raise ValidationError("repository owner metadata is missing")
    result = {
        "repository_full_name": str(payload.get("full_name") or ""),
        "repository_id": positive(payload.get("id"), "repository ID"),
        "repository_name": str(payload.get("name") or ""),
        "repository_owner_login": str(owner.get("login") or ""),
        "repository_owner_id": positive(owner.get("id"), "repository owner ID"),
    }
    if result["repository_full_name"] != expected:
        raise ValidationError("repository full name mismatch")
    if result["repository_name"] != expected_name:
        raise ValidationError("repository name mismatch")
    if result["repository_owner_login"] != expected_owner:
        raise ValidationError("repository owner login mismatch")
    return result


def verify_pr(payload: Mapping[str, Any], repo: Mapping[str, str], sha: str) -> None:
    for side in ("base", "head"):
        candidate = ((payload.get(side) or {}).get("repo") or {})
        if candidate.get("full_name") != repo["repository_full_name"]:
            raise ValidationError(f"PR {side} repository name mismatch")
        if positive(candidate.get("id"), f"PR {side} repository ID") != repo["repository_id"]:
            raise ValidationError(f"PR {side} repository ID mismatch")
    if (payload.get("head") or {}).get("sha") != sha:
        raise ValidationError("PR head SHA mismatch")
    if payload.get("state") != "open" or payload.get("draft") is not True:
        raise ValidationError("approval PR must remain OPEN and Draft")
    if payload.get("merged") is not False:
        raise ValidationError("approval PR must remain unmerged")


def body_authorizes(body: str, sha: str) -> bool:
    status = any(line.strip() == "UI_APPROVED" for line in body.splitlines())
    exact_sha = re.search(rf"(?<![0-9a-f]){re.escape(sha)}(?![0-9a-f])", body)
    return status and exact_sha is not None


def owner_comment_authorizes(
    comment: Mapping[str, Any], sha: str, repo: Mapping[str, str]
) -> bool:
    if comment.get("pull_request_review_id") is not None or comment.get("in_reply_to_id") is not None:
        return False
    user = comment.get("user")
    if not isinstance(user, Mapping) or str(user.get("type") or "").lower() == "bot":
        return False
    if str(user.get("login") or "") != repo["repository_owner_login"]:
        return False
    try:
        user_id = positive(user.get("id"), "comment author ID")
    except ValidationError:
        return False
    if user_id != repo["repository_owner_id"]:
        return False
    if comment.get("author_association") != "OWNER":
        return False
    return body_authorizes(str(comment.get("body") or ""), sha)


def find_owner_approval(
    comments: Iterable[Mapping[str, Any]], sha: str, repo: Mapping[str, str]
) -> Mapping[str, Any] | None:
    return next((c for c in comments if owner_comment_authorizes(c, sha, repo)), None)


def request_json(url: str, token: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "approved-business-pages-provisioning",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise ValidationError(f"GitHub API returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ValidationError("GitHub API request failed") from exc


def issue_comments(api: str, repository: str, pr: str, token: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for page in range(1, 101):
        query = urllib.parse.urlencode({"per_page": 100, "page": page})
        payload = request_json(f"{api}/repos/{repository}/issues/{pr}/comments?{query}", token)
        if not isinstance(payload, list):
            raise ValidationError("Issue Comments API returned a non-list payload")
        result.extend(item for item in payload if isinstance(item, dict))
        if len(payload) < 100:
            return result
    raise ValidationError("Issue Comments pagination exceeded the safety bound")


def write_metadata(path: Path, values: Mapping[str, str]) -> None:
    path.write_text(json.dumps(dict(values), sort_keys=True) + "\n", encoding="utf-8")


def verify_authority(pr: str, sha: str, output: Path) -> dict[str, str]:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    if not repository or "/" not in repository or not token:
        raise ValidationError("trusted GitHub repository or token is unavailable")
    repository_payload = request_json(f"{api}/repos/{repository}", token)
    if not isinstance(repository_payload, Mapping):
        raise ValidationError("Repository API returned an invalid payload")
    metadata = repository_metadata(repository_payload, repository)
    pr_payload = request_json(f"{api}/repos/{repository}/pulls/{pr}", token)
    if not isinstance(pr_payload, Mapping):
        raise ValidationError("Pull Request API returned an invalid payload")
    verify_pr(pr_payload, metadata, sha)
    approval = find_owner_approval(issue_comments(api, repository, pr, token), sha, metadata)
    if approval is None:
        raise ValidationError("no repository-owner UI_APPROVED comment exists for the exact SHA")
    positive(approval.get("id"), "approval comment ID")
    write_metadata(output, metadata)
    return metadata


def project_payload(
    project: str, source: str, branch: str, repo: Mapping[str, str]
) -> dict[str, Any]:
    root = source.rstrip("/")
    return {
        "name": project,
        "production_branch": branch,
        "build_config": {"build_command": "", "destination_dir": ".", "root_dir": root},
        "source": {
            "type": "github",
            "config": {
                "owner": repo["repository_owner_login"],
                "owner_id": repo["repository_owner_id"],
                "repo_name": repo["repository_name"],
                "repo_id": repo["repository_id"],
                "production_branch": branch,
                "production_deployments_enabled": True,
                "preview_deployment_setting": "none",
                "pr_comments_enabled": False,
                "path_includes": [f"{root}/**"],
                "path_excludes": [],
            },
        },
    }


def verify_project(
    response: Mapping[str, Any], project: str, source: str, branch: str, repo: Mapping[str, str]
) -> None:
    if response.get("success") is not True or not isinstance(response.get("result"), Mapping):
        raise ValidationError("Cloudflare project API response is unsuccessful")
    actual = response["result"]
    expected = project_payload(project, source, branch, repo)
    if actual.get("name") != project or actual.get("production_branch") != branch:
        raise ValidationError("Cloudflare project identity or production branch mismatch")
    actual_source = actual.get("source")
    if not isinstance(actual_source, Mapping) or actual_source.get("type") != "github":
        raise ValidationError("existing Cloudflare project is Direct Upload or non-GitHub")
    config = actual_source.get("config")
    if not isinstance(config, Mapping):
        raise ValidationError("Cloudflare GitHub source config is missing")
    expected_config = expected["source"]["config"]
    for field in (
        "owner", "repo_name", "production_branch", "production_deployments_enabled",
        "preview_deployment_setting", "pr_comments_enabled", "path_includes", "path_excludes",
    ):
        if config.get(field) != expected_config[field]:
            raise ValidationError(f"Cloudflare source config mismatch: {field}")
    for field in ("owner_id", "repo_id"):
        if str(config.get(field) or "") != expected_config[field]:
            raise ValidationError(f"Cloudflare source config mismatch: {field}")
    build = actual.get("build_config")
    if not isinstance(build, Mapping):
        raise ValidationError("Cloudflare build config is missing")
    for field in ("build_command", "destination_dir", "root_dir"):
        if build.get(field) != expected["build_config"][field]:
            raise ValidationError(f"Cloudflare build config mismatch: {field}")


def load_object(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError("JSON file is unreadable") from exc
    if not isinstance(payload, Mapping):
        raise ValidationError("JSON payload must be an object")
    return payload


def verify_source(root: Path, source: str, sha: str) -> None:
    checked = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    if checked != sha:
        raise ValidationError("checked-out HEAD does not equal approved_sha")
    repository_root = root.resolve(strict=True)
    current = repository_root
    for part in Path(source.rstrip("/")).parts:
        current /= part
        if current.is_symlink():
            raise ValidationError("source path contains a symlink")
    source_root = current.resolve(strict=True)
    try:
        source_root.relative_to(repository_root)
    except ValueError as exc:
        raise ValidationError("source resolves outside repository") from exc
    if not (source_root / "index.html").is_file():
        raise ValidationError("source index.html is missing")
    for candidate in source_root.rglob("*"):
        if candidate.is_symlink():
            try:
                candidate.resolve(strict=True).relative_to(source_root)
            except (FileNotFoundError, ValueError) as exc:
                raise ValidationError(f"source symlink escapes or is broken: {candidate}") from exc


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    authority = commands.add_parser("authority")
    for name in ("business-id", "project-name", "source-directory", "approved-sha", "approval-pr", "production-branch"):
        authority.add_argument(f"--{name}", required=True)
    authority.add_argument("--repository-metadata-output", type=Path, required=True)
    source = commands.add_parser("source")
    source.add_argument("--repository-root", type=Path, required=True)
    source.add_argument("--source-directory", required=True)
    source.add_argument("--approved-sha", required=True)
    payload = commands.add_parser("cloudflare-payload")
    project = commands.add_parser("cloudflare-project")
    for item in (payload, project):
        item.add_argument("--repository-metadata-file", type=Path, required=True)
        item.add_argument("--project-name", required=True)
        item.add_argument("--source-directory", required=True)
        item.add_argument("--production-branch", required=True)
    payload.add_argument("--output", type=Path, required=True)
    project.add_argument("--response-file", type=Path, required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "authority":
            validate_inputs(args.business_id, args.project_name, args.source_directory,
                            args.approved_sha, args.approval_pr, args.production_branch)
            verify_authority(args.approval_pr, args.approved_sha,
                             args.repository_metadata_output)
        elif args.command == "source":
            if not SHA_RE.fullmatch(args.approved_sha):
                raise ValidationError("invalid approved_sha")
            verify_source(args.repository_root, args.source_directory, args.approved_sha)
        else:
            repo = load_object(args.repository_metadata_file)
            expected_keys = {
                "repository_full_name", "repository_id", "repository_name",
                "repository_owner_login", "repository_owner_id",
            }
            if set(repo) != expected_keys:
                raise ValidationError("repository metadata file contract mismatch")
            positive(repo["repository_id"], "repository ID")
            positive(repo["repository_owner_id"], "repository owner ID")
            owner, name = str(repo["repository_full_name"]).split("/", 1)
            if owner != repo["repository_owner_login"] or name != repo["repository_name"]:
                raise ValidationError("repository metadata file is internally inconsistent")
            if args.command == "cloudflare-payload":
                args.output.write_text(json.dumps(project_payload(
                    args.project_name, args.source_directory, args.production_branch, repo
                ), separators=(",", ":")), encoding="utf-8")
            elif args.command == "cloudflare-project":
                verify_project(load_object(args.response_file), args.project_name,
                               args.source_directory, args.production_branch, repo)
            else:
                raise ValidationError("unknown command")
    except (ValidationError, subprocess.CalledProcessError, FileNotFoundError, ValueError, KeyError) as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1
    print("validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
