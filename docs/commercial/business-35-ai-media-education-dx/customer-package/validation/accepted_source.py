#!/usr/bin/env python3
"""Accepted Lane A source dependency for B35 Lane B regeneration.

Exact accepted source revision (CENTRAL G2, PR #1551)::

    ACCEPTED_SOURCE_REVISION = 63adbefcf24a91a5a064c6b8e13779e151ba7de7

Builders MUST NOT hardcode commercial truth independently. They must obtain
it through this module, which deterministically materializes the exact
accepted snapshot via ``git show <rev>:<path>`` and parses commercial facts
(prices, V3.1 six-stage journey, diagnostic Q1-Q5, proposal pages, pilot
weeks) out of that snapshot. Any parse mismatch fails the build closed.

Lane A files themselves are never modified by Lane B; they are only read
from the exact revision's Git object store.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ACCEPTED_SOURCE_REVISION = "63adbefcf24a91a5a064c6b8e13779e151ba7de7"
PRODUCT_AUTHORITY_REVISION = "05932da3af774220372f0e9f3716b07cd83511f9"
PRODUCT_CONTRACT_BLOB_SHA = "961ff2ae5390f6c6fc99f6969d5ef3b7665ea82f"

LANE_A_DIR = "docs/commercial/business-35-ai-media-education-dx"
ACCEPTED_SOURCE_FILES = [
    "CURRENT_PRODUCT_AUTHORITY.md",
    "README.md",
    "01-one-page-offer.md",
    "02-ten-page-proposal.md",
    "03-diagnostic-questionnaire.md",
    "04-six-week-pilot-plan.md",
    "05-statement-of-work-draft.md",
    "06-risk-and-data-annex.md",
    "07-kpi-measurement-framework.md",
    "08-customer-qualification-scorecard.md",
    "SOURCES.md",
]

CACHE_DIR = Path(__file__).resolve().parent / ".accepted_source" / ACCEPTED_SOURCE_REVISION


def find_repo_root(start: Path) -> Path:
    p = start
    for _ in range(12):
        if (p / ".git").exists():
            return p
        if p.parent == p:
            break
        p = p.parent
    raise RuntimeError("git repository root not found (Lane B must run inside the repo)")


def _git(args: list[str], repo: Path) -> str:
    out = subprocess.run(
        ["git"] + args, cwd=str(repo), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {out.stderr.strip()[:300]}")
    return out.stdout


def materialize(repo: Path | None = None) -> dict[str, str]:
    """Extract the exact accepted snapshot via ``git show`` (deterministic).

    Writes bytes verbatim to CACHE_DIR and returns {filename: text}.
    Fails closed when the revision or any file is missing.
    """
    repo = repo or find_repo_root(Path(__file__).resolve())
    kind = _git(["cat-file", "-t", ACCEPTED_SOURCE_REVISION], repo).strip()
    if kind != "commit":
        raise RuntimeError(
            f"ACCEPTED_SOURCE_REVISION {ACCEPTED_SOURCE_REVISION} is not a commit (got {kind})"
        )
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    snapshot: dict[str, str] = {}
    for name in ACCEPTED_SOURCE_FILES:
        gitpath = f"{LANE_A_DIR}/{name}"
        proc = subprocess.run(
            ["git", "show", f"{ACCEPTED_SOURCE_REVISION}:{gitpath}"],
            cwd=str(repo), capture_output=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"accepted source file missing at exact revision: {gitpath}")
        (CACHE_DIR / name).write_bytes(proc.stdout)
        snapshot[name] = proc.stdout.decode("utf-8")
    # Deterministic cache order check: every expected file present, nothing else.
    cached = sorted(p.name for p in CACHE_DIR.glob("*.md"))
    if cached != sorted(ACCEPTED_SOURCE_FILES):
        raise RuntimeError(f"accepted source cache mismatch: {cached}")
    return snapshot


def load() -> dict[str, str]:
    """Load the accepted snapshot (materialize on first use, verify always)."""
    if CACHE_DIR.is_dir() and sorted(p.name for p in CACHE_DIR.glob("*.md")) == sorted(
        ACCEPTED_SOURCE_FILES
    ):
        # Re-verify against the exact revision so a stale cache can never pass.
        repo = find_repo_root(Path(__file__).resolve())
        fresh = materialize(repo)
        for name in ACCEPTED_SOURCE_FILES:
            cached_text = (CACHE_DIR / name).read_text(encoding="utf-8")
            if cached_text != fresh[name]:
                raise RuntimeError(f"accepted source cache drift for {name}")
        return fresh
    return materialize()


def require_accepted_source() -> dict[str, str]:
    """Entry point for builders: materialize + verify + announce revision."""
    snapshot = load()
    print(f"accepted source consumed: SOURCE_REVISION={ACCEPTED_SOURCE_REVISION}")
    print(f"product authority: PRODUCT_AUTHORITY_REVISION={PRODUCT_AUTHORITY_REVISION}")
    return snapshot


# ---- Parsed commercial truth (all values come from the snapshot) ----

def _code_block_after(text: str, marker: str) -> str:
    idx = text.find(marker)
    if idx < 0:
        raise RuntimeError(f"accepted source marker not found: {marker!r}")
    seg = text[idx:]
    m = re.search(r"```text\s*\n(.*?)```", seg, re.DOTALL)
    if not m:
        raise RuntimeError(f"accepted source code block missing after: {marker!r}")
    return m.group(1)


def six_stage_journey(snapshot: dict[str, str]) -> list[str]:
    """V3.1 primary journey lines (6 stages) from CURRENT_PRODUCT_AUTHORITY.md."""
    block = _code_block_after(snapshot["CURRENT_PRODUCT_AUTHORITY.md"], "Current primary journey")
    lines = [ln.strip().lstrip("\u2192 ").strip() for ln in block.strip().splitlines()]
    stages = [ln for ln in lines if ln]
    if len(stages) != 6:
        raise RuntimeError(f"V3.1 journey must have 6 stages, got {len(stages)}: {stages}")
    required_tokens = [
        "병목",
        "조직·결과물·병목·팀 규모·AI 사용 상태",
        "조직별 진단",
        "운영체계 산출물",
        "진단 워크숍 또는 6주 파일럿",
        "전환 요약",
    ]
    joined = "\n".join(stages)
    for tok in required_tokens:
        if tok not in joined:
            raise RuntimeError(f"V3.1 journey missing required token: {tok}")
    return stages


def product_promise(snapshot: dict[str, str]) -> str:
    m = re.search(r"> (.+사람이 승인하는 운영체계로 바꾼다\.)", snapshot["CURRENT_PRODUCT_AUTHORITY.md"])
    if not m:
        raise RuntimeError("product promise not found in accepted CURRENT_PRODUCT_AUTHORITY.md")
    return m.group(1).strip()


def product_name(snapshot: dict[str, str]) -> str:
    if "파디엠 AI 미디어 업무전환 스튜디오" not in snapshot["CURRENT_PRODUCT_AUTHORITY.md"]:
        raise RuntimeError("product name missing in accepted source")
    return "파디엠 AI 미디어 업무전환 스튜디오"


def offer_price_tokens(snapshot: dict[str, str]) -> dict[str, str]:
    """Price hypothesis tokens parsed from 01-one-page-offer.md (도입 옵션)."""
    block = _code_block_after(snapshot["01-one-page-offer.md"], "## 도입 옵션")
    expected = ["300만–500만원", "500만–800만원", "1,000만–1,500만원",
                "1,500만–2,500만원", "월 300만–600만원", "300만–800만원"]
    for tok in expected:
        if tok not in block:
            raise RuntimeError(f"offer price token missing in accepted 01 source: {tok}")
    return {
        "A_INITIAL": "300만–500만원",
        "A_EXTENDED": "500만–800만원",
        "A_BROAD": "300만–800만원",
        "B1": "1,000만–1,500만원",
        "B2": "1,500만–2,500만원",
        "C": "월 300만–600만원",
    }


def user_journey_six(snapshot: dict[str, str]) -> list[str]:
    """The six user steps from 01 (사용자가 실제로 하는 일)."""
    block = _code_block_after(snapshot["01-one-page-offer.md"], "## 사용자가 실제로 하는 일")
    steps = [ln.strip() for ln in block.strip().splitlines() if ln.strip()]
    if len(steps) != 6:
        raise RuntimeError(f"01 user journey must have 6 steps, got {len(steps)}")
    if not any("조직·결과물·병목·팀 규모·AI 사용 상태" in s for s in steps):
        raise RuntimeError("01 user journey missing five-input step")
    return steps


def proposal_pages(snapshot: dict[str, str]) -> list[tuple[str, str]]:
    """Ten (page_no, title) pairs parsed from 02-ten-page-proposal.md."""
    found = re.findall(r"^## Page (\d+) — (.+)$", snapshot["02-ten-page-proposal.md"], re.MULTILINE)
    if len(found) != 10 or [f[0] for f in found] != [str(i) for i in range(1, 11)]:
        raise RuntimeError(f"02 source must define Pages 1-10, got: {found}")
    return found


def proposal_page_body(snapshot: dict[str, str], page_no: int) -> str:
    text = snapshot["02-ten-page-proposal.md"]
    m = re.search(
        rf"^## Page {page_no} — .+$(.*?)(?=^## Page |\Z)", text, re.MULTILINE | re.DOTALL
    )
    if not m:
        raise RuntimeError(f"02 source Page {page_no} body not found")
    return m.group(1)


def diagnostic_questions(snapshot: dict[str, str]) -> list[tuple[str, str, str]]:
    """All (number, title, body) questions parsed from 03 source sections."""
    text = snapshot["03-diagnostic-questionnaire.md"]
    parts = re.split(r"^## (\d+)\. (.+)$", text, flags=re.MULTILINE)
    # parts: [pre, num, title, body, num, title, body, ...]
    questions: list[tuple[str, str, str]] = []
    for i in range(1, len(parts), 3):
        questions.append((parts[i].strip(), parts[i + 1].strip(), parts[i + 2]))
    if len(questions) != 17:
        raise RuntimeError(f"03 source must define 17 questions, got {len(questions)}")
    return questions


def diagnostic_q1_q5(snapshot: dict[str, str]) -> list[tuple[str, str]]:
    """The five V3.1 input dimensions Q1-Q5 (fillable fields)."""
    questions = diagnostic_questions(snapshot)
    first_five = [(n, t) for n, t, _ in questions[:5]]
    expected = [("1", "조직 유형"), ("2", "결과물 유형"), ("3", "병목 지점"),
                ("4", "현재 팀 규모"), ("5", "AI 사용 상태")]
    if first_five != expected:
        raise RuntimeError(f"03 source Q1-Q5 mismatch: {first_five} != {expected}")
    return expected


def delivery_week_titles(snapshot: dict[str, str]) -> list[tuple[str, str]]:
    """Week 0-6 delivery detail titles from 04 (downstream only, not identity)."""
    found = re.findall(r"^## (Week \d+) — (.+)$", snapshot["04-six-week-pilot-plan.md"], re.MULTILINE)
    if len(found) != 7 or [f[0] for f in found] != [f"Week {i}" for i in range(7)]:
        raise RuntimeError(f"04 source must define Week 0-6, got: {found}")
    return found


def kpi_candidates(snapshot: dict[str, str]) -> None:
    if "재작업률" not in snapshot["07-kpi-measurement-framework.md"]:
        raise RuntimeError("07 KPI source missing expected content")
