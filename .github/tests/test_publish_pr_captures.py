from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_module():
    script = Path(__file__).resolve().parents[1] / ".." / "tools" / "publish_pr_captures.py"
    spec = importlib.util.spec_from_file_location("publish_pr_captures", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


module = _load_module()
HEAD = "1" * 40


def _png(seed: int = 1) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + f"capture-{seed}".encode()


def _fixture(tmp_path, monkeypatch, count=2):
    bundle = tmp_path / "padiem-reports" / "2026-11-26" / "7811-example"
    bundle.mkdir(parents=True)
    summary = bundle / "manifest.json"
    summary.write_text(json.dumps({"issue": "7811"}), encoding="utf-8")
    captures = []
    for index in range(count):
        path = bundle / f"capture-{index}.png"
        path.write_bytes(_png(index))
        captures.append(str(path))
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "run_git", lambda *args: "")
    args = SimpleNamespace(
        pr=9001,
        head_sha=HEAD,
        summary=str(summary),
        capture=captures,
        repo="skerishKang/ai-revenue-lab",
        private_repo="skerishKang/ai-revenue-lab-sc",
    )
    return args, summary, captures


class FakeGH:
    def __init__(self):
        self.private = True
        self.state = "OPEN"
        self.pr_head = HEAD
        self.body = "# Existing PR body\n"
        self.files = {}
        self.commit = "a" * 40
        self.patches = []
        self.calls = []

    def __call__(self, gh, *args, input_text=None):
        self.calls.append((args, input_text))
        if args == ("api", "repos/skerishKang/ai-revenue-lab-sc"):
            return json.dumps({
                "private": self.private,
                "visibility": "private" if self.private else "public",
                "default_branch": "main",
            })
        if args[:3] == ("api", "--method", "GET") and "/contents/" in args[3]:
            relative = args[3].split("/contents/", 1)[1]
            if relative not in self.files:
                raise module.CommandError("command_failed", 1, "gh: Not Found (HTTP 404)")
            return json.dumps({"sha": module.git_blob_sha(self.files[relative])})
        if args[:3] == ("api", "--method", "PUT") and "/contents/" in args[3]:
            relative = args[3].split("/contents/", 1)[1]
            payload = json.loads(input_text)
            self.files[relative] = base64.b64decode(payload["content"])
            self.commit = f"{len(self.calls):040x}"
            return json.dumps({"commit": {"sha": self.commit}})
        if args[:3] == ("api", "--method", "GET") and args[3].endswith("/commits"):
            return json.dumps([{"sha": self.commit}])
        if args[:2] == ("pr", "view"):
            return json.dumps({
                "body": self.body,
                "headRefOid": self.pr_head,
                "state": self.state,
                "url": "https://github.com/skerishKang/ai-revenue-lab/pull/9001",
            })
        if args[:3] == ("api", "--method", "PATCH") and args[3].endswith("/pulls/9001"):
            payload = json.loads(input_text)
            self.body = payload["body"]
            self.patches.append(payload)
            return "{}"
        raise AssertionError(f"unexpected gh call: {args}")


def test_publish_uploads_only_captures_and_updates_body_idempotently(tmp_path, monkeypatch):
    args, summary, captures = _fixture(tmp_path, monkeypatch)
    fake = FakeGH()
    monkeypatch.setattr(module, "run_gh", fake)

    first = module.publish(args, "gh")
    first_body = fake.body
    second = module.publish(args, "gh")

    assert first["captures"] == [Path(path).relative_to(tmp_path).as_posix() for path in captures]
    assert second == first
    assert fake.body == first_body
    assert fake.body.count(module.BLOCK_START) == 1
    assert fake.body.startswith("# Existing PR body")
    assert summary.relative_to(tmp_path).as_posix() in fake.body
    assert "검증 HEAD: `" + HEAD + "`" in fake.body
    assert "캡처: 2장 (최대 8장)" in fake.body
    assert all(path.endswith(".png") for path in fake.files)
    assert not any("manifest.json" in path for path in fake.files)
    assert base64.b64encode(_png(0)).decode() not in fake.body
    assert len(fake.patches) == 2


def test_public_companion_repository_is_rejected_before_upload(tmp_path, monkeypatch):
    args, _, _ = _fixture(tmp_path, monkeypatch)
    fake = FakeGH()
    fake.private = False
    monkeypatch.setattr(module, "run_gh", fake)

    with pytest.raises(module.PublishError, match="private_repository_required"):
        module.publish(args, "gh")

    assert fake.files == {}
    assert fake.patches == []


def test_stale_pr_head_is_rejected_before_body_update(tmp_path, monkeypatch):
    args, _, _ = _fixture(tmp_path, monkeypatch)
    fake = FakeGH()
    fake.pr_head = "2" * 40
    monkeypatch.setattr(module, "run_gh", fake)

    with pytest.raises(module.PublishError, match="pull_request_head_mismatch"):
        module.publish(args, "gh")

    assert fake.files == {}
    assert fake.patches == []


def test_closed_pr_is_rejected_before_upload(tmp_path, monkeypatch):
    args, _, _ = _fixture(tmp_path, monkeypatch, count=1)
    fake = FakeGH()
    fake.state = "CLOSED"
    monkeypatch.setattr(module, "run_gh", fake)

    with pytest.raises(module.PublishError, match="pull_request_not_open"):
        module.publish(args, "gh")

    assert fake.files == {}
    assert fake.patches == []


def test_second_capture_set_for_same_pr_is_rejected_before_upload(tmp_path, monkeypatch):
    args, _, _ = _fixture(tmp_path, monkeypatch, count=1)
    fake = FakeGH()
    monkeypatch.setattr(module, "run_gh", fake)
    module.publish(args, "gh")

    replacement = Path(args.capture[0]).with_name("replacement.png")
    replacement.write_bytes(_png(99))
    args.capture = [str(replacement)]
    with pytest.raises(module.PublishError, match="capture_set_conflict"):
        module.publish(args, "gh")

    assert not any(path.endswith("replacement.png") for path in fake.files)
    assert len(fake.patches) == 1


def test_existing_capture_bytes_are_never_overwritten(tmp_path, monkeypatch):
    args, _, captures = _fixture(tmp_path, monkeypatch, count=1)
    fake = FakeGH()
    relative = Path(captures[0]).relative_to(tmp_path).as_posix()
    fake.files[relative] = b"different existing evidence"
    fake.commit = "b" * 40
    monkeypatch.setattr(module, "run_gh", fake)

    with pytest.raises(module.PublishError, match="capture_content_conflict"):
        module.publish(args, "gh")

    assert fake.files[relative] == b"different existing evidence"
    assert fake.patches == []


def test_eight_captures_pass_and_ninth_is_rejected(tmp_path, monkeypatch):
    args, _, _ = _fixture(tmp_path, monkeypatch, count=9)
    captures = module.validate_captures(args.capture[:8], "padiem-reports/2026-11-26/7811-example/manifest.json")
    assert len(captures) == 8
    with pytest.raises(module.PublishError, match="capture_count_out_of_range"):
        module.validate_captures(args.capture, "padiem-reports/2026-11-26/7811-example/manifest.json")


def test_summary_must_be_tracked_at_exact_head(tmp_path, monkeypatch):
    args, summary, _ = _fixture(tmp_path, monkeypatch, count=1)

    def missing(*argv):
        raise module.CommandError("command_failed", 128, "not found")

    monkeypatch.setattr(module, "run_git", missing)
    with pytest.raises(module.PublishError, match="summary_not_tracked_at_head"):
        module.validate_summary(summary, summary.relative_to(tmp_path).as_posix(), HEAD)


def test_dirty_summary_is_rejected(tmp_path, monkeypatch):
    args, summary, _ = _fixture(tmp_path, monkeypatch, count=1)

    def different_blob(*argv):
        if argv[0] == "rev-parse":
            return "a" * 40
        if argv[0] == "hash-object":
            return "b" * 40
        return ""

    monkeypatch.setattr(module, "run_git", different_blob)
    with pytest.raises(module.PublishError, match="summary_differs_from_head"):
        module.validate_summary(summary, summary.relative_to(tmp_path).as_posix(), HEAD)


def test_invalid_image_signature_is_rejected(tmp_path, monkeypatch):
    args, _, captures = _fixture(tmp_path, monkeypatch, count=1)
    Path(captures[0]).write_bytes(b"not an image")
    with pytest.raises(module.PublishError, match="capture_signature_invalid"):
        module.validate_captures(captures, "padiem-reports/2026-11-26/7811-example/manifest.json")


def test_upsert_replaces_one_block_without_duplicating_it():
    block = module.BLOCK_START + "\nnew\n" + module.BLOCK_END
    body = "before\n" + module.BLOCK_START + "\nold\n" + module.BLOCK_END + "\nafter"
    assert module.upsert_block(body, block) == "before\n" + block + "\nafter"
    assert module.upsert_block(module.upsert_block(body, block), block) == "before\n" + block + "\nafter"


def test_duplicate_markers_are_rejected():
    block = module.BLOCK_START + "\n" + module.BLOCK_END
    with pytest.raises(module.PublishError, match="capture_markers_invalid"):
        module.upsert_block(block + "\n" + block, block)


def test_reversed_markers_are_rejected():
    block = module.BLOCK_START + "\n" + module.BLOCK_END
    reversed_body = module.BLOCK_END + "\n" + module.BLOCK_START
    with pytest.raises(module.PublishError, match="capture_markers_invalid"):
        module.upsert_block(reversed_body, block)
