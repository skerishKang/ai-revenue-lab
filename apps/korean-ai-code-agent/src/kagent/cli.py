from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

from .core import AgentBoundaryError, AgentSession, redact_secrets
from .draft_flow import DRAFT_DOC_TYPES, run_draft_command
from .p01_run_flow import run_p01_task
from .review_flow import run_review_command


def yes(prompt: str) -> bool:
    return input(f"{prompt} [y/N] ").strip().lower() in {"y", "yes", "예", "네"}


def print_header(session: AgentSession) -> None:
    print("KAgent · 한국형 AI 코드 에이전트")
    print(f"저장소: {session.root}")
    print(f"작업: {session.task}")
    print(f"모델 경로: {session.route}")
    print("권한 기본값: read=yes · write=ask · command=ask · network=off · git=off")
    git_state = session.git_worktree_status()
    print(
        "Git 상태: "
        f"{git_state['status']} · changed={git_state['changed_count']} · "
        "mutation=off"
    )


def allowed_test_command(raw: str) -> list[str]:
    normalized = raw.strip()
    allowed = {
        "python -m unittest": [sys.executable, "-m", "unittest"],
        "python -m unittest discover": [sys.executable, "-m", "unittest", "discover"],
        "python -m compileall .": [sys.executable, "-m", "compileall", "."],
    }
    if normalized not in allowed:
        raise AgentBoundaryError("Phase 1 allowlist 밖의 명령은 실행하지 않습니다.")
    return allowed[normalized]


def run_allowed_test(command: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    """Execute one pre-built allowlisted command with redacted captured output."""
    allowed_shapes = {
        (sys.executable, "-m", "unittest"),
        (sys.executable, "-m", "unittest", "discover"),
        (sys.executable, "-m", "compileall", "."),
    }
    if tuple(command) not in allowed_shapes:
        raise AgentBoundaryError("검증된 allowlist 명령만 실행할 수 있습니다.")
    result = subprocess.run(
        command,
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    return subprocess.CompletedProcess(
        args=result.args,
        returncode=result.returncode,
        stdout=redact_secrets(result.stdout or ""),
        stderr=redact_secrets(result.stderr or ""),
    )


def run_interactive(session: AgentSession) -> int:
    print_header(session)
    print("\n[B14 MOCK ADAPTER]")
    preview = session.business14_mock_response()
    print(
        f"adapter={preview['adapter']} route={preview['route']} "
        f"request_id={preview['request_id']} status={preview['status']} "
        f"network_called={preview['network_called']}"
    )

    print("\n[PLAN]")
    files = session.inspect()
    print("읽기 후보:", ", ".join(files[:8]) if files else "텍스트 파일 없음")
    for index, step in enumerate(session.plan(), 1):
        print(f" {index}. {step}")

    print("\n[BUILD PREVIEW]")
    print(session.prepare_demo_patch() or "변경 없음")
    if yes("이 bounded preview를 파일에 적용할까요?"):
        session.permissions.write = True
        path = session.apply()
        print(f"적용됨: {path.relative_to(session.root)}")
    else:
        session.reject()
        print("쓰기 거부: 파일 변경 없음")

    print("\n[TEST]")
    if yes("allowlist 테스트 명령을 실행할까요?"):
        raw = input("명령 [기본: python -m unittest discover]: ").strip() or "python -m unittest discover"
        command = allowed_test_command(raw)
        session.permissions.command = True
        result = run_allowed_test(command, session.root)
        print(result.stdout[-4000:])
        if result.stderr:
            print(result.stderr[-2000:], file=sys.stderr)
        print(f"exit={result.returncode}")
    else:
        print("명령 실행 거부: 실행 없음")

    print("\n[REVIEW]")
    contract = session.runtime_contract()
    print(f"Business 14 endpoint configured: {contract['business14_base_url_configured']}")
    print(f"Network enabled: {contract['network']} · Git mutation enabled: {contract['git_mutation']}")
    git_state = contract["git_worktree"]
    print(f"Git worktree: {git_state['status']} · changed={git_state['changed_count']}")
    print("최종 결정은 사용자에게 남습니다. 자동 commit/push/merge/deploy는 없습니다.")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kagent",
        description="한국어 개인 개발자를 위한 permission-gated coding-agent CLI vertical slice",
    )
    p.add_argument("repository", nargs="?", default=".", help="작업 저장소 경로")
    p.add_argument("--route", default="business14/auto", help="Business 14 route 또는 manual model marker")
    sub = p.add_subparsers(dest="mode")
    for name in ("plan", "run"):
        cmd = sub.add_parser(name)
        cmd.add_argument("task", help="한국어 작업 설명")
    p01 = sub.add_parser(
        "p01-run",
        help="P01 Engine 오케스트레이션으로 작업을 실행합니다 (설정 필수 · demo 폴백 없음)",
    )
    p01.add_argument("task", help="한국어 작업 설명")
    p01.add_argument("--run-id", dest="run_id", default=None, help="run_ 접두어의 실행 ID")
    review = sub.add_parser(
        "review",
        help="저장소 파일들을 P01 Engine으로 리뷰합니다 (설정 필수 · demo 폴백 없음)",
    )
    review.add_argument(
        "targets", nargs="+", help="리뷰 대상 파일 또는 glob 패턴"
    )
    review.add_argument(
        "--out", dest="out", default=None, help="마크다운 보고서를 기록할 파일 경로"
    )
    review.add_argument(
        "--run-id", dest="run_id", default=None, help="run_ 접두어의 실행 ID"
    )
    draft = sub.add_parser(
        "draft",
        help="입력 파일에서 거래 맥락을 추출해 견적서/발주서 초안을 생성합니다 "
        "(설정 필수 · demo 폴백 없음)",
    )
    draft.add_argument("input", help="거래 맥락이 담긴 입력 파일 경로")
    draft.add_argument(
        "--doc-type",
        dest="doc_type",
        required=True,
        choices=list(DRAFT_DOC_TYPES),
        help="생성할 문서 유형 (견적서 | 발주서)",
    )
    draft.add_argument(
        "--out", dest="out", default=None, help="마크다운 초안을 기록할 파일 경로"
    )
    draft.add_argument(
        "--run-id", dest="run_id", default=None, help="run_ 접두어의 실행 ID"
    )
    return p


def main(argv: list[str] | None = None, *, adapter=None) -> int:
    args = parser().parse_args(argv)
    if args.mode == "review":
        return run_review_command(
            Path(args.repository),
            args.targets,
            adapter=adapter,
            run_id=args.run_id,
            out_path=Path(args.out) if args.out else None,
        )
    if args.mode == "draft":
        return run_draft_command(
            Path(args.repository),
            args.input,
            args.doc_type,
            adapter=adapter,
            run_id=args.run_id,
            out_path=Path(args.out) if args.out else None,
        )
    task = getattr(args, "task", None)
    if not task:
        parser().print_help()
        return 0
    if args.mode == "p01-run":
        return run_p01_task(
            Path(args.repository), task, adapter=adapter, run_id=args.run_id
        )
    try:
        session = AgentSession.open(Path(args.repository), task, args.route)
        if args.mode == "plan":
            print_header(session)
            session.inspect()
            preview = session.business14_mock_response()
            print(
                f"B14 MOCK · route={preview['route']} · request_id={preview['request_id']} · "
                f"network_called={preview['network_called']}"
            )
            print("\n".join(f"- {step}" for step in session.plan()))
            print("PLAN MODE · no writes · no commands · no network · no git mutation")
            return 0
        return run_interactive(session)
    except AgentBoundaryError as exc:
        print(f"KAGENT_BOUNDARY: {redact_secrets(str(exc))}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())