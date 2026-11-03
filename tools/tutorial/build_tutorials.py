#!/usr/bin/env python3
"""#6724 2: build user tutorials from the QA scenario screenplays.

The screenplays in ``docs/qa/scenarios`` are the single source: each row is
"사용자 동작 → 기대 화면", a 확인 지표 column and a caption. This script turns
rows 01–05 into ``docs/help/tutorials``, translates developer vocabulary through
``TERM_RULES``, and marks the stages that need a prepared account instead of
inventing their screens. 06 is an operations runbook and stays out of the help.

The output is deterministic: the same screenplays produce byte-identical files,
with no run ids and no dates, so any diff means the source changed.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCENARIO_DIR = REPO / "docs" / "qa" / "scenarios"
OUTPUT_DIR = REPO / "docs" / "help" / "tutorials"

SCENARIOS = (
    ("01", "first-visit"),
    ("02", "pc-connection"),
    ("03", "document-work"),
    ("04", "bookai"),
    ("05", "account-deletion"),
)
EXCLUDED = {"06": "장애 복구는 운영 문서라 사용자 도움말에 넣지 않습니다."}

#: The session file a future test account will provide. Empty today: the guest
#: scenes are the only ones this pipeline has ever recorded.
ACCOUNT_ENV = "PADIEM_LIVE_STORAGE_STATE"
#: Media keys, not relative paths: the same text has to work when the files move
#: to R2 or the Worker's static assets.
MEDIA_KEY_ROOT = "chat-tutorial"
PLACEHOLDER = "[화면 준비 중 — 시험 계정 확정 후 촬영]"

#: Developer vocabulary → what a person sees. Longest phrases first: "GET 상태"
#: must not be reduced to "화면 열기 상태", and "세션 파일" must be handled
#: before the bare "세션" that would leave "로그인 상태 파일" behind.
TERM_RULES = (
    (r"GET\s*상태", "화면이 열렸는지"),
    (r"HTTP\s*상태", "응답 여부"),
    (r"상태\s*코드", "응답 여부"),
    (r"401\s*“([^”]+)”\s*안내", r"“\1” 안내"),
    (r"(?<![0-9])504(?![0-9])", "시간 초과"),
    (r"(?<![0-9])401(?![0-9])", "로그인 안내"),
    (r"(?<![0-9])200(?![0-9])", "정상 응답"),
    (r"authenticated\s*=\s*false", "로그인하지 않은 상태"),
    (r"authenticated\s*=\s*true", "로그인한 상태"),
    (r"storage[- ]state", "로그인 정보"),
    (r"세션\s*파일", "로그인 정보"),
    (r"준비된\s*세션으로", "로그인한 상태로"),
    (r"준비된\s*세션", "준비된 계정"),
    (r"세션", "로그인 상태"),
    (r"\bJSON\b", "결과 기록"),
    (r"\bAPI\b", "화면 주소"),
    (r"\bendpoint\b", "주소"),
    (r"\bPOST\b", "보내기"),
    (r"\bGET\b", "화면 열기"),
    (r"\bms\b", "걸린 시간"),
    (r"레인", "처리 경로"),
)

#: Where a tutorial and the existing help page talk about the same thing. The
#: quotes are checked against help.html by the tests, so this table cannot rot
#: into paraphrases the help page never says. ``None`` means the help page has
#: no such item yet.
HELP_COMPARISON = (
    (
        "컴퓨터 연결 설치 안내",
        "컴퓨터 연결 설치 안내",
        "같음 — 도움말의 같은 링크로 이어집니다.",
    ),
    (
        "이 PC 연결하기",
        "이 PC 연결하기",
        "같음 — 버튼 이름이 같습니다. 튜토리얼은 누르는 순서를 설명합니다.",
    ),
    (
        "북AI에서 읽기 기록을 남겨요.",
        "로그인하지 않아도 읽기 기록과 Memory가 이 기기에 저장돼요.",
        "같음 — 기기에 저장되는 범위가 같습니다.",
    ),
    (
        "로그인하면 다른 기기에서도 이어서 볼 수 있어요.",
        "파디엠 계정으로 로그인하면 계정에도 저장되어 다른 기기에서 이어져요.",
        "표현만 다름 — 도움말은 저장 위치까지, 튜토리얼은 결과만 적습니다.",
    ),
    (
        "로그인이 필요한 항목은 로그인 안내로 안전하게 막아요.",
        "되돌리기 어려운 동작으로 보일 때는 실행하기 전에 묻고",
        "다름 — 도움말은 실행 전 확인, 튜토리얼 장면은 목록 접근 차단입니다. 문구 통일은 후속 과제입니다.",
    ),
    (
        "계정 탈퇴",
        None,
        "다름 — help.html에 탈퇴 항목이 아직 없습니다.",
    ),
)


def user_words(text: str) -> str:
    """Translate developer vocabulary through TERM_RULES, in table order."""

    for pattern, replacement in TERM_RULES:
        text = re.sub(pattern, replacement, text)
    return text


def _field(lines, prefix: str) -> str:
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip()
    return ""


def _numbers(text: str) -> list[int]:
    found: list[int] = []
    for token in re.split(r"[,，]", text):
        token = token.strip()
        span = re.match(r"^(\d+)\s*[–\-~]\s*(\d+)$", token)
        if span:
            found.extend(range(int(span.group(1)), int(span.group(2)) + 1))
        elif token.isdigit():
            found.append(int(token))
    return sorted(set(found))


def _scope(text: str) -> tuple[list[int], list[int]]:
    guest: list[int] = []
    account: list[int] = []
    for part in text.split(";"):
        part = part.strip()
        if not part:
            continue
        label, _, rest = part.partition(" ")
        numbers = _numbers(rest)
        if label.startswith("게스트"):
            guest = numbers
        elif label.startswith("로그인"):
            account = numbers
    return guest, account


def _steps(lines) -> list[dict]:
    steps: list[dict] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) != 4 or not cells[0].isdigit():
            continue
        action, arrow, expected = cells[1].partition("→")
        steps.append(
            {
                "number": int(cells[0]),
                "action": user_words(action.strip()),
                "expected": user_words(expected.strip()) if arrow else user_words(cells[1].strip()),
                "checked": user_words(cells[2].strip()),
                "caption": cells[3].strip(),
            }
        )
    return steps


def _format_numbers(numbers: list[int]) -> str:
    if not numbers:
        return ""
    if numbers == list(range(numbers[0], numbers[-1] + 1)) and len(numbers) > 1:
        return f"{numbers[0]}–{numbers[-1]}"
    return ", ".join(str(number) for number in numbers)


def load_scenario(number: str, slug: str) -> dict:
    path = SCENARIO_DIR / f"{number}-{slug}.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    guest, account = _scope(_field(lines, "**튜토리얼 공개 범위:**"))
    steps = _steps(lines)
    if not steps:
        raise ValueError(f"scenario has no step table: {path}")
    missing = [step["number"] for step in steps if step["number"] not in guest + account]
    if missing:
        raise ValueError(f"step without a tutorial scope ({path.name}): {missing}")
    return {
        "number": number,
        "slug": slug,
        #: Stable media key: the screenplay number plus its name.
        "key": f"{number}-{slug}",
        "file": path.name,
        "title": next((line[2:].strip() for line in lines if line.startswith("# ")), slug),
        "purpose": _field(lines, "**목적:**"),
        "precondition": _field(lines, "**사전 조건:**"),
        "guest": guest,
        "account": account,
        "steps": steps,
    }


def load_scenarios() -> list[dict]:
    return [load_scenario(number, slug) for number, slug in SCENARIOS]


def _preparation(document: dict) -> str:
    guest = _format_numbers(document["guest"])
    account = _format_numbers(document["account"])
    if guest and account:
        return (
            f"로그인 없이 {guest}단계까지 볼 수 있어요. "
            f"{account}단계는 준비된 계정이 필요해 지금은 화면 자리를 비워 두었습니다."
        )
    if account:
        return (
            "계정이 필요합니다. 시험 계정이 확정되기 전까지는 화면 자리를 비워 두었습니다."
        )
    return "로그인 없이 볼 수 있어요."


def render(document: dict) -> str:
    lines = [
        f"# {document['title']}",
        "",
        (
            "> 이 문서는 시나리오 대본 `docs/qa/scenarios/"
            f"{document['file']}`에서 자동으로 만들어집니다. 화면 문구를 바꾸려면 대본을 고친 뒤 "
            "`python tools/tutorial/build_tutorials.py`를 다시 실행하세요."
        ),
        "",
        f"**이런 분께:** {document['purpose']}",
        "",
        f"**준비물:** {_preparation(document)}",
        "",
        "## 단계",
        "",
    ]
    for step in document["steps"]:
        guest = step["number"] in document["guest"]
        lines.extend([f"### {step['number']}단계 · {step['caption']}", ""])
        if not guest:
            lines.extend([f"> {PLACEHOLDER}", ""])
        lines.extend(
            [
                f"**이렇게 해요:** {step['action']}",
                "",
                f"**이렇게 보여요:** {step['expected']}",
                "",
            ]
        )
        if step["checked"]:
            lines.extend([f"**화면에서 확인하는 것:** {step['checked']}", ""])
        if guest:
            lines.extend(
                [
                    (
                        f"![{step['caption']}]"
                        f"(asset://{MEDIA_KEY_ROOT}/{document['key']}/step-{step['number']:02d}.png)"
                    ),
                    "",
                ]
            )

    lines.extend(["## 영상과 자막", ""])
    if document["guest"]:
        guest = _format_numbers(document["guest"])
        account = _format_numbers(document["account"])
        lines.extend(
            [
                f"- 영상: `asset://{MEDIA_KEY_ROOT}/{document['key']}/video.webm`",
                f"- 자막: `asset://{MEDIA_KEY_ROOT}/{document['key']}/captions.vtt`",
                f"- 촬영 범위: 게스트 {guest}단계.",
            ]
        )
        if account:
            lines.append(f"- 계정 {account}단계는 {PLACEHOLDER}로 두고 같은 키에 이어 찍습니다.")
        lines.append("")
    else:
        lines.extend(
            [
                "아직 촬영하지 않았습니다 — 이 시나리오는 계정 단계로만 이루어져 있습니다.",
                f"시험 계정이 확정되면 `asset://{MEDIA_KEY_ROOT}/{document['key']}/video.webm`과 "
                "`captions.vtt`로 촬영합니다.",
                "",
            ]
        )

    lines.extend(
        [
            "---",
            "",
            "다음 단계와 촬영 규칙은 `docs/operations/TUTORIAL_GENERATION_NEXT_STEPS.md`에 있습니다.",
            "",
        ]
    )
    return "\n".join(lines)


def render_readme(documents: list[dict]) -> str:
    lines = [
        "# 사용자 튜토리얼",
        "",
        (
            "`docs/qa/scenarios`의 시나리오 대본에서 자동으로 만든 사용자 안내입니다. "
            "대본을 고치고 `python tools/tutorial/build_tutorials.py`를 다시 실행하면 이 폴더가 바뀝니다. "
            "손으로 고친 내용은 다음 생성에서 사라집니다."
        ),
        "",
        "## 문서",
        "",
        "| 번호 | 문서 | 대상 | 게스트 단계 | 계정 단계 |",
        "|---|---|---|---|---|",
    ]
    for document in documents:
        lines.append(
            f"| {document['number']} | [{document['title']}]"
            f"({document['number']}-{document['slug']}.md) | {document['purpose'].rstrip('.')} | "
            f"{_format_numbers(document['guest']) or '없음'} | "
            f"{_format_numbers(document['account']) or '없음'} |"
        )
    lines.extend(
        [
            "",
            "06 장애 복구는 운영 문서라 여기서 만들지 않습니다.",
            "",
            "## 이미지·영상 키",
            "",
            "튜토리얼은 상대 경로 대신 키로 미디어를 가리킵니다. 파일이 R2나 정적 자산으로 옮겨져도 문서를 고칠 필요가 없습니다.",
            "",
            "| 종류 | 키 형식 | 예 |",
            "|---|---|---|",
            f"| 단계 화면 | `asset://{MEDIA_KEY_ROOT}/<문서>/step-NN.png` | "
            f"`asset://{MEDIA_KEY_ROOT}/01-first-visit/step-01.png` |",
            f"| 영상 | `asset://{MEDIA_KEY_ROOT}/<문서>/video.webm` | "
            f"`asset://{MEDIA_KEY_ROOT}/01-first-visit/video.webm` |",
            f"| 자막 | `asset://{MEDIA_KEY_ROOT}/<문서>/captions.vtt` | "
            f"`asset://{MEDIA_KEY_ROOT}/01-first-visit/captions.vtt` |",
            "",
            "촬영 원본은 저장소에 넣지 않습니다(`tools/tutorial/capture_guest_scenes.py --out <폴더>`).",
            "",
            "## 도움말 화면과의 관계",
            "",
            "기존 도움말(`apps/padiem-chat/static/help.html`)과 겹치거나 다른 표현입니다. 이번 단계에서는 화면 문구를 고치지 않았습니다.",
            "",
            "| 튜토리얼 문구 | 도움말 화면 문구 | 판정 |",
            "|---|---|---|",
        ]
    )
    for tutorial_phrase, help_quote, verdict in HELP_COMPARISON:
        quote = f"“{help_quote}”" if help_quote else "(항목 없음)"
        lines.append(f"| {tutorial_phrase} | {quote} | {verdict} |")
    lines.extend(
        [
            "",
            "## 다시 만들기",
            "",
            "```bash",
            "python tools/tutorial/build_tutorials.py           # 문서 생성",
            "python tools/tutorial/build_tutorials.py --check   # 문서가 최신인지 확인",
            "python -m unittest discover -s tools/tutorial/tests -t tools/tutorial",
            "python tools/tutorial/capture_guest_scenes.py --dry-run",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def build(output_dir: Path = OUTPUT_DIR) -> list[Path]:
    documents = load_scenarios()
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for document in documents:
        path = output_dir / f"{document['number']}-{document['slug']}.md"
        path.write_text(render(document), encoding="utf-8")
        written.append(path)
    readme = output_dir / "README.md"
    readme.write_text(render_readme(documents), encoding="utf-8")
    written.append(readme)
    return written


def check(output_dir: Path = OUTPUT_DIR) -> list[str]:
    """Files whose content differs from what the screenplays produce now."""

    documents = load_scenarios()
    stale: list[str] = []
    expected = {f"{document['number']}-{document['slug']}.md": render(document) for document in documents}
    expected["README.md"] = render_readme(documents)
    for name, text in expected.items():
        path = output_dir / name
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            stale.append(name)
    return stale


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        stale = check(args.output)
        if stale:
            print("tutorials_stale=" + ",".join(sorted(stale)))
            return 1
        print("tutorials_up_to_date")
        return 0
    written = build(args.output)
    print(f"tutorials_written={len(written)} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
