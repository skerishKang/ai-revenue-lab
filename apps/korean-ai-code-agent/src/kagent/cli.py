from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

from .core import AgentBoundaryError, AgentSession


def yes(prompt: str) -> bool:
    return input(f"{prompt} [y/N] ").strip().lower() in {"y", "yes", "예", "네"}


def print_header(session: AgentSession) -> None:
    print("KAgent · 한국형 AI 코드 에이전트")
    print(f"저장소: {session.root}")
    print(f"작업: {session.task}")
    print(f"모델 경로: {session.route}")
    print("권한 기본값: read=yes · write=ask · command=ask · network=off · git=off")


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


def run_interactive(session: AgentSession) -> int:
    print_header(session)
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
        result = subprocess.run(command, cwd=session.root, text=True, capture_output=True, check=False)
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
    print("최종 결정은 사용자에게 남습니다. 자동 commit/push/merge/deploy는 없습니다.")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kagent", description="한국어 개인 개발자를 위한 permission-gated coding-agent CLI vertical slice")
    p.add_argument("repository", nargs="?", default=".", help="작업 저장소 경로")
    p.add_argument("--route", default="business14/auto", help="Business 14 route 또는 manual model marker")
    sub = p.add_subparsers(dest="mode")
    for name in ("plan", "run"):
        cmd = sub.add_parser(name)
        cmd.add_argument("task", help="한국어 작업 설명")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    task = getattr(args, "task", None)
    if not task:
        parser().print_help()
        return 0
    try:
        session = AgentSession.open(Path(args.repository), task, args.route)
        if args.mode == "plan":
            print_header(session)
            session.inspect()
            print("\n".join(f"- {step}" for step in session.plan()))
            print("PLAN MODE · no writes · no commands · no network · no git mutation")
            return 0
        return run_interactive(session)
    except AgentBoundaryError as exc:
        print(f"KAGENT_BOUNDARY: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
