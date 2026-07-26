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
from typing import Any, Iterable


BUSINESS_ID_RE = re.compile(r"^[0-9]{2}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
PR_RE = re.compile(r"^[1-9][0-9]*$")
PROJECT_SUFFIX_RE = r"[a-z0-9]+(?:-[a-z0-9]+)*"
SOURCE_SUFFIX_RE = r"[a-z0-9]+(?:-[a-z0-9]+)*"


class ValidationError(RuntimeError):
    """Raised when a provisioning guardrail fails."""


def validate_inputs(
    business_id: str,
    project_name: str,
    source_directory: str,
    approved_sha: str,
    approval_pr: str,
    production_branch: str,
) -> None:
    if not BUSINESS_ID_RE.fullmatch(business_id) or business_id == "00":
        raise ValidationError("business_id must be two decimal digits from 01 through 99")

    expected_project = re.compile(
        rf"^ai-revenue-business-{re.escape(business_id)}-{PROJECT_SUFFIX_RE}$"
    )
    if len(project_name) > 63 or not expected_project.fullmatch(project_name):
        raise ValidationError(
            "project_name must be a Cloudflare-safe dedicated name for the same Business"
        )

    if (
        source_directory.startswith(("/", "\\"))
        or ".." in source_directory
        or "\\" in source_directory
        or any(ord(character) < 32 for character in source_directory)
    ):
        raise ValidationError("source_directory contains a forbidden path form")

    expected_source = re.compile(
        rf"^reference/business-{re.escape(business_id)}-{SOURCE_SUFFIX_RE}/?$"
    )
    if not expected_source.fullmatch(source_directory):
        raise ValidationError(
            "source_directory must be an isolated reference path for the same Business"
        )

    if not SHA_RE.fullmatch(approved_sha):
        raise ValidationError("approved_sha must be a full lowercase 40-character SHA")

    if not PR_RE.fullmatch(approval_pr):
        raise ValidationError("approval_pr must be a positive integer")

    if production_branch != "main":
        raise ValidationError("production_branch must be exactly main")


def _positive_id(value: Any, field_name: str) -> str:
    if isinstance(value, bool):
        raise ValidationError(f"{field_name} must be a positive identifier")
    text = str(value or "")
    if not PR_RE.fullmatch(text):
        raise ValidationError(f"{field_name} must be a positive identifier")
    return text


def verify_repository_payload(
    payload: dict[str, Any], expected_repository: str
) -> dict[str, str]:
    try:
        expected_owner, expected_name = expected_repository.split("/", 1)
    except ValueError as exc:  # pragma: no cover - guarded by caller
        raise ValidationError("expected repository must use owner/name form") from exc

    owner = payload.get("owner") or {}
    owner_login = str(owner.get("login") or "")
    repository_name = str(payload.get("name") or "")
    full_name = str(payload.get("full_name") or "")

    if full_name != expected_repository:
        raise ValidationError("GitHub repository metadata full_name does not match")
    if owner_login != expected_owner:
        raise ValidationError("GitHub repository owner login does not match")
    if repository_name != expected_name:
        raise ValidationError("GitHub repository name does not match")

    return {
        "owner_login": owner_login,
        "owner_id": _positive_id(owner.get("id"), "repository owner ID"),
        "repository_name": repository_name,
        "repository_id": _positive_id(payload.get("id"), "repository ID"),
        "repository_full_name": full_name,
    }


def verify_pr_payload(payload: dict[str, Any], repository: str, approved_sha: str) -> None:
    base_repository = ((payload.get("base") or {}).get("repo") or {}).get("full_name")
    head_sha = (payload.get("head") or {}).get("sha")

    if base_repository != repository:
        raise ValidationError("approval PR does not belong to the current repository")
    if head_sha != approved_sha:
        raise ValidationError("approval PR head SHA does not match approved_sha")
    if payload.get("state") != "open":
        raise ValidationError("approval PR must remain open")
    if payload.get("draft") is not True:
        raise ValidationError("approval PR must remain Draft")
    if payload.get("merged") is not False:
        raise ValidationError("approval PR must remain unmerged")


def comment_authorizes(body: str, approved_sha: str) -> bool:
    has_exact_status = any(line.strip() == "UI_APPROVED" for line in body.splitlines())
    sha_pattern = re.compile(rf"(?<![0-9a-f]){re.escape(approved_sha)}(?![0-9a-f])")
    return has_exact_status and bool(sha_pattern.search(body))


def find_authorizing_comment(
    comments: Iterable[dict[str, Any]], approved_sha: str, repository_owner_login: str
) -> dict[str, Any] | None:
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        user = comment.get("user") or {}
        login = str(user.get("login") or "")
        user_type = str(user.get("type") or "")
        association = str(comment.get("author_association") or "")

        if comment.get("pull_request_review_id") is not None:
            continue
        if comment.get("in_reply_to_id") is not None:
            continue
        if user_type.lower() == "bot" or login.lower().endswith("[bot]"):
            continue
        if login != repository_owner_login:
            continue
        if association != "OWNER":
            continue
        if comment_authorizes(str(comment.get("body") or ""), approved_sha):
            return comment
    return None


def _request_json(url: str, token: str) -> tuple[Any, dict[str, str]]:
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
            return json.load(response), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        raise ValidationError(f"GitHub API request failed with HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ValidationError("GitHub API request failed") from exc


def _fetch_all_issue_comments(
    api_url: str, repository: str, pr_number: str, token: str
) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    page = 1
    while True:
        query = urllib.parse.urlencode({"per_page": 100, "page": page})
        url = f"{api_url}/repos/{repository}/issues/{pr_number}/comments?{query}"
        payload, _ = _request_json(url, token)
        if not isinstance(payload, list):
            raise ValidationError("GitHub comments API returned an unexpected payload")
        comments.extend(item for item in payload if isinstance(item, dict))
        if len(payload) < 100:
            break
        page += 1
        if page > 100:
            raise ValidationError("GitHub comments pagination exceeded the safety bound")
    return comments


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json_object(path: Path, description: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{description} is not readable JSON") from exc
    if not isinstance(payload, dict):
        raise ValidationError(f"{description} must be a JSON object")
    return payload


def verify_github_authority(
    approval_pr: str, approved_sha: str, repository_metadata_output: Path
) -> dict[str, str]:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")

    if not repository or "/" not in repository:
        raise ValidationError("GITHUB_REPOSITORY is unavailable")
    if not token:
        raise ValidationError("GITHUB_TOKEN is unavailable")

    repository_url = f"{api_url}/repos/{repository}"
    repository_payload, _ = _request_json(repository_url, token)
    if not isinstance(repository_payload, dict):
        raise ValidationError("GitHub repository API returned an unexpected payload")
    metadata = verify_repository_payload(repository_payload, repository)

    pr_url = f"{api_url}/repos/{repository}/pulls/{approval_pr}"
    pr_payload, _ = _request_json(pr_url, token)
    if not isinstance(pr_payload, dict):
        raise ValidationError("GitHub PR API returned an unexpected payload")
    verify_pr_payload(pr_payload, repository, approved_sha)

    comments = _fetch_all_issue_comments(api_url, repository, approval_pr, token)
    authority = find_authorizing_comment(comments, approved_sha, metadata["owner_login"])
    if authority is None:
        raise ValidationError(
            "no repository-owner top-level PR comment authorizes UI_APPROVED for the exact SHA"
        )

    _write_json(repository_metadata_output, metadata)
    comment_id = authority.get("id")
    print(
        "GitHub repository and owner approval authority verified: "
        f"{metadata['repository_full_name']} (repo {metadata['repository_id']}), "
        f"owner {metadata['owner_login']} ({metadata['owner_id']}), comment {comment_id}."
    )
    return metadata


def build_cloudflare_project_payload(
    project_name: str,
    source_directory: str,
    production_branch: str,
    repository_metadata: dict[str, Any],
) -> dict[str, Any]:
    source_root = source_directory.rstrip("/")
    return {
        "name": project_name,
        "production_branch": production_branch,
        "build_config": {
            "build_command": "",
            "destination_dir": ".",
            "root_dir": source_root,
        },
        "source": {
            "type": "github",
            "config": {
                "owner": str(repository_metadata["owner_login"]),
                "owner_id": str(repository_metadata["owner_id"]),
                "repo_name": str(repository_metadata["repository_name"]),
                "repo_id": str(repository_metadata["repository_id"]),
                "production_branch": production_branch,
                "production_deployments_enabled": True,
                "preview_deployment_setting": "none",
                "pr_comments_enabled": False,
                "path_includes": [f"{source_root}/**"],
            },
        },
    }


def verify_cloudflare_project_response(
    api_payload: dict[str, Any],
    project_name: str,
    source_directory: str,
    production_branch: str,
    repository_metadata: dict[str, Any],
) -> dict[str, Any]:
    if api_payload.get("success") is not True:
        raise ValidationError("Cloudflare project API did not report success")
    project = api_payload.get("result")
    if not isinstance(project, dict):
        raise ValidationError("Cloudflare project API result is not an object")

    if project.get("name") != project_name:
        raise ValidationError("Cloudflare Pages project name does not match")
    if project.get("production_branch") != production_branch:
        raise ValidationError("Cloudflare Pages production branch does not match")

    source = project.get("source")
    if not isinstance(source, dict) or source.get("type") != "github":
        raise ValidationError("Cloudflare Pages project is not GitHub-integrated")
    config = source.get("config")
    if not isinstance(config, dict):
        raise ValidationError("Cloudflare Pages GitHub source config is missing")

    expected_config = {
        "owner": str(repository_metadata["owner_login"]),
        "owner_id": str(repository_metadata["owner_id"]),
        "repo_name": str(repository_metadata["repository_name"]),
        "repo_id": str(repository_metadata["repository_id"]),
        "production_branch": production_branch,
        "production_deployments_enabled": True,
        "preview_deployment_setting": "none",
        "pr_comments_enabled": False,
        "path_includes": [f"{source_directory.rstrip('/')}/**"],
    }
    for field, expected in expected_config.items():
        actual = config.get(field)
        if field in {"owner_id", "repo_id"} and actual is not None:
            actual = str(actual)
        if actual != expected:
            raise ValidationError(f"Cloudflare Pages source config mismatch: {field}")

    build_config = project.get("build_config")
    if not isinstance(build_config, dict):
        raise ValidationError("Cloudflare Pages build_config is missing")
    expected_build = {
        "root_dir": source_directory.rstrip("/"),
        "destination_dir": ".",
        "build_command": "",
    }
    for field, expected in expected_build.items():
        if build_config.get(field) != expected:
            raise ValidationError(f"Cloudflare Pages build config mismatch: {field}")

    return project


def check_source_isolation(repository_root: Path, source_directory: str) -> None:
    repository_root = repository_root.resolve(strict=True)
    source_path = repository_root / source_directory.rstrip("/")

    current = repository_root
    for component in Path(source_directory.rstrip("/")).parts:
        current = current / component
        if current.is_symlink():
            raise ValidationError("source directory path contains a symlink")

    source_root = source_path.resolve(strict=True)
    try:
        source_root.relative_to(repository_root)
    except ValueError as exc:
        raise ValidationError("source directory resolves outside the repository") from exc

    index_path = source_root / "index.html"
    if not index_path.is_file():
        raise ValidationError("source directory must contain index.html")

    for candidate in source_root.rglob("*"):
        if not candidate.is_symlink():
            continue
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError as exc:
            raise ValidationError(f"broken symlink is not allowed: {candidate}") from exc
        try:
            resolved.relative_to(source_root)
        except ValueError as exc:
            raise ValidationError(f"symlink escapes source directory: {candidate}") from exc


def verify_checked_out_sha(repository_root: Path, approved_sha: str) -> None:
    result = subprocess.run(
        ["git", "-C", str(repository_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip() != approved_sha:
        raise ValidationError("checked-out repository HEAD does not match approved_sha")


def _add_project_contract_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repository-metadata-file", required=True, type=Path)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--source-directory", required=True)
    parser.add_argument("--production-branch", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    authority = subparsers.add_parser("authority")
    for name in (
        "business_id",
        "project_name",
        "source_directory",
        "approved_sha",
        "approval_pr",
        "production_branch",
    ):
        authority.add_argument(f"--{name.replace('_', '-')}", required=True)
    authority.add_argument("--repository-metadata-output", required=True, type=Path)

    source = subparsers.add_parser("source")
    source.add_argument("--repository-root", required=True, type=Path)
    source.add_argument("--source-directory", required=True)
    source.add_argument("--approved-sha", required=True)

    payload = subparsers.add_parser("cloudflare-payload")
    _add_project_contract_arguments(payload)
    payload.add_argument("--output", required=True, type=Path)

    project = subparsers.add_parser("cloudflare-project")
    _add_project_contract_arguments(project)
    project.add_argument("--response-file", required=True, type=Path)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "authority":
            validate_inputs(
                args.business_id,
                args.project_name,
                args.source_directory,
                args.approved_sha,
                args.approval_pr,
                args.production_branch,
            )
            verify_github_authority(
                args.approval_pr,
                args.approved_sha,
                args.repository_metadata_output,
            )
        elif args.command == "source":
            if not SHA_RE.fullmatch(args.approved_sha):
                raise ValidationError("approved_sha must be a full lowercase 40-character SHA")
            verify_checked_out_sha(args.repository_root, args.approved_sha)
            check_source_isolation(args.repository_root, args.source_directory)
        elif args.command == "cloudflare-payload":
            metadata = _read_json_object(
                args.repository_metadata_file, "repository metadata file"
            )
            payload = build_cloudflare_project_payload(
                args.project_name,
                args.source_directory,
                args.production_branch,
                metadata,
            )
            _write_json(args.output, payload)
        elif args.command == "cloudflare-project":
            metadata = _read_json_object(
                args.repository_metadata_file, "repository metadata file"
            )
            response = _read_json_object(args.response_file, "Cloudflare response file")
            verify_cloudflare_project_response(
                response,
                args.project_name,
                args.source_directory,
                args.production_branch,
                metadata,
            )
            print("Cloudflare GitHub-integrated Pages project contract verified.")
        else:  # pragma: no cover
            raise ValidationError("unknown command")
    except (ValidationError, subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1

    print("validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
