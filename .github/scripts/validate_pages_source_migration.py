#!/usr/bin/env python3
"""Offline guards for approved Cloudflare Pages source-directory migration."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

VERIFY_ONLY = "verify-only"
MIGRATE_SOURCE = "migrate-source"
APPROVAL_MARKER = "SOURCE_MIGRATION_APPROVED"
BUSINESS_ID_RE = re.compile(r"^[0-9]{2}$")
PROJECT_SUFFIX_RE = r"[a-z0-9]+(?:-[a-z0-9]+)*"
SOURCE_SUFFIX_RE = r"[a-z0-9]+(?:-[a-z0-9]+)*"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
PR_RE = re.compile(r"^[1-9][0-9]*$")


class ValidationError(RuntimeError):
    """Raised when a source-migration guardrail fails."""


def validate_source_path(business_id: str, source_directory: str) -> str:
    if not BUSINESS_ID_RE.fullmatch(business_id) or business_id == "00":
        raise ValidationError("business_id must be two decimal digits from 01 through 99")
    if (
        source_directory.startswith(("/", "\\"))
        or ".." in source_directory
        or "\\" in source_directory
        or any(ord(character) < 32 for character in source_directory)
    ):
        raise ValidationError("source_directory contains a forbidden path form")
    expected = re.compile(
        rf"^reference/business-{re.escape(business_id)}-{SOURCE_SUFFIX_RE}/?$"
    )
    if not expected.fullmatch(source_directory):
        raise ValidationError(
            "source_directory must be an isolated reference path for the same Business"
        )
    return source_directory.rstrip("/")


def validate_contract(
    action: str,
    business_id: str,
    project_name: str,
    source_directory: str,
    expected_old_source_directory: str,
    approved_sha: str,
    approval_pr: str,
    production_branch: str,
) -> tuple[str | None, str]:
    if action not in {VERIFY_ONLY, MIGRATE_SOURCE}:
        raise ValidationError(
            "existing_project_action must be exactly verify-only or migrate-source"
        )

    expected_project = re.compile(
        rf"^ai-revenue-business-{re.escape(business_id)}-{PROJECT_SUFFIX_RE}$"
    )
    if len(project_name) > 63 or not expected_project.fullmatch(project_name):
        raise ValidationError(
            "project_name must be a dedicated Pages name for the same Business"
        )
    if not SHA_RE.fullmatch(approved_sha):
        raise ValidationError("approved_sha must be a full lowercase 40-character SHA")
    if not PR_RE.fullmatch(approval_pr):
        raise ValidationError("approval_pr must be a positive integer")
    if production_branch != "main":
        raise ValidationError("production_branch must be exactly main")

    new_source = validate_source_path(business_id, source_directory)
    if action == VERIFY_ONLY:
        if expected_old_source_directory:
            raise ValidationError(
                "expected_old_source_directory must be empty in verify-only mode"
            )
        return None, new_source

    if not expected_old_source_directory:
        raise ValidationError("migrate-source requires expected_old_source_directory")
    old_source = validate_source_path(business_id, expected_old_source_directory)
    if old_source == new_source:
        raise ValidationError(
            "migrate-source requires different old and new source directories"
        )
    return old_source, new_source


def _exact_field(body: str, name: str) -> str | None:
    prefix = f"{name}:"
    matches: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if line.startswith(prefix):
            matches.append(line[len(prefix) :].strip().strip("`"))
    return matches[0] if len(matches) == 1 else None


def comment_authorizes(
    body: str,
    project_name: str,
    old_source: str,
    new_source: str,
    approved_sha: str,
) -> bool:
    if sum(1 for line in body.splitlines() if line.strip() == APPROVAL_MARKER) != 1:
        return False
    expected = {
        "project_name": project_name,
        "old_source_directory": old_source,
        "new_source_directory": new_source,
        "approved_sha": approved_sha,
    }
    return all(_exact_field(body, field) == value for field, value in expected.items())


def find_authorizing_comment(
    comments: Iterable[dict[str, Any]],
    owner_login: str,
    project_name: str,
    old_source: str,
    new_source: str,
    approved_sha: str,
) -> dict[str, Any] | None:
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        user = comment.get("user") or {}
        login = str(user.get("login") or "")
        user_type = str(user.get("type") or "")
        if comment.get("pull_request_review_id") is not None:
            continue
        if comment.get("in_reply_to_id") is not None:
            continue
        if user_type.lower() == "bot" or login.lower().endswith("[bot]"):
            continue
        if login != owner_login or str(comment.get("author_association") or "") != "OWNER":
            continue
        if comment_authorizes(
            str(comment.get("body") or ""),
            project_name,
            old_source,
            new_source,
            approved_sha,
        ):
            return comment
    return None


def verify_comments_file(
    comments_file: Path,
    repository_metadata_file: Path,
    project_name: str,
    old_source: str,
    new_source: str,
    approved_sha: str,
) -> dict[str, Any]:
    metadata = json.loads(repository_metadata_file.read_text(encoding="utf-8"))
    comments = json.loads(comments_file.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise ValidationError("repository metadata must be a JSON object")
    if not isinstance(comments, list):
        raise ValidationError("comments payload must be a JSON array")
    owner_login = str(metadata.get("owner_login") or "")
    if not owner_login:
        raise ValidationError("repository owner metadata is missing")
    authority = find_authorizing_comment(
        comments,
        owner_login,
        project_name,
        old_source,
        new_source,
        approved_sha,
    )
    if authority is None:
        raise ValidationError(
            "no repository-owner top-level comment authorizes the exact source migration"
        )
    return authority


def build_patch_payload(source_directory: str) -> dict[str, Any]:
    source_root = source_directory.rstrip("/")
    return {
        "build_config": {"root_dir": source_root},
        "source": {
            "type": "github",
            "config": {"path_includes": [f"{source_root}/**"]},
        },
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    contract = subparsers.add_parser("contract")
    for name in (
        "existing_project_action",
        "business_id",
        "project_name",
        "source_directory",
        "approved_sha",
        "approval_pr",
        "production_branch",
    ):
        contract.add_argument(f"--{name.replace('_', '-')}", required=True)
    contract.add_argument("--expected-old-source-directory", default="")

    authority = subparsers.add_parser("authority")
    authority.add_argument("--comments-file", required=True, type=Path)
    authority.add_argument("--repository-metadata-file", required=True, type=Path)
    authority.add_argument("--project-name", required=True)
    authority.add_argument("--old-source-directory", required=True)
    authority.add_argument("--new-source-directory", required=True)
    authority.add_argument("--approved-sha", required=True)

    payload = subparsers.add_parser("patch-payload")
    payload.add_argument("--source-directory", required=True)
    payload.add_argument("--output", required=True, type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "contract":
            validate_contract(
                args.existing_project_action,
                args.business_id,
                args.project_name,
                args.source_directory,
                args.expected_old_source_directory,
                args.approved_sha,
                args.approval_pr,
                args.production_branch,
            )
        elif args.command == "authority":
            authority = verify_comments_file(
                args.comments_file,
                args.repository_metadata_file,
                args.project_name,
                args.old_source_directory.rstrip("/"),
                args.new_source_directory.rstrip("/"),
                args.approved_sha,
            )
            print(f"source migration owner authority verified: comment {authority.get('id')}")
        elif args.command == "patch-payload":
            write_json(args.output, build_patch_payload(args.source_directory))
        else:  # pragma: no cover
            raise ValidationError("unknown command")
    except (ValidationError, OSError, json.JSONDecodeError) as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1
    print("validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
