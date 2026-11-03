#!/usr/bin/env python3
"""#6724 2: build user tutorials from the QA scenario screenplays.

The screenplays in ``docs/qa/scenarios`` are the single source: each row is
"사용자 동작 → 기대 화면", a 확인 지표 column and a caption. This script turns
rows 01–05 into ``docs/help/tutorials``, translates developer vocabulary through
``TERM_RULES``, and marks the stages that need a prepared account instead of
inventing their screens. 06 is an operations runbook and stays out of the help.

The output is deterministic: the same screenplays produce byte-identical files,
with no run ids and no dates, so any diff means the source changed.

The same screenplays also produce the static pages that sit next to help.html
(``apps/padiem-chat/static/help-tutorials``) and the step images shrunk from the
recordings, so the help screen and the tutorials cannot describe different
steps.
"""
from __future__ import annotations

import argparse
import io
import re
import sys
from html import escape
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCENARIO_DIR = REPO / "docs" / "qa" / "scenarios"
OUTPUT_DIR = REPO / "docs" / "help" / "tutorials"
#: The pages live next to help.html, so they inherit its stylesheets and the
#: same static-asset deployment. Nothing new is served from a second origin.
PAGE_DIR = REPO / "apps" / "padiem-chat" / "static" / "help-tutorials"
#: Recording output (outside the repository, see capture_guest_scenes.py).
DEFAULT_SHOTS = REPO.parent / "out"
#: One phone-sized step image must stay small enough to send without a CDN
#: transform; the recorder's PNGs are ~1 MB each.
MAX_IMAGE_BYTES = 150 * 1024
#: The videos and captions are not in the repository. The pages name the base
#: URL variable they will read, and nothing else.
VIDEO_KEY_ENV = "PADIEM_TUTORIAL_MEDIA_BASE_URL"

SCENARIOS = (
    ("01", "first-visit"),
    ("02", "pc-connection"),
    ("03", "document-work"),
    ("04", "bookai"),
    ("05", "account-deletion"),
    # 06 is the disaster-recovery runbook; the external-AI connection keeps the
    # screenplay numbering instead of renumbering the operations document.
    ("07", "external-ai-connect"),
)
EXCLUDED = {"06": "장애 복구는 운영 문서라 사용자 도움말에 넣지 않습니다."}

#: The session file a future test account will provide. Empty today: the guest
#: scenes are the only ones this pipeline has ever recorded.
ACCOUNT_ENV = "PADIEM_LIVE_STORAGE_STATE"
#: Media keys, not relative paths: the same text has to work when the files move
#: to R2 or the Worker's static assets.
MEDIA_KEY_ROOT = "chat-tutorial"
PLACEHOLDER = "[화면 준비 중 — 시험 계정 확정 후 촬영]"
#: help.html carries this marker as an HTML comment until the real connector
#: flow has been exercised on the deployed host. The unit test ties the two
#: files together so neither side can drop it alone.
PENDING_MARK = "[실제 연결 확인 전]"

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
        "로그인이 필요한 화면은 열기 전에 로그인 안내로 막습니다.",
        "같음 — 도움말이 로그인 차단과 실행 전 확인을 함께 말합니다.",
    ),
    (
        "계정 탈퇴",
        "입력이 계정 이메일과 다르면 아무것도 지워지지 않습니다.",
        "같음 — 도움말 #account 절이 이메일 재입력 확인과 같은 범위를 적습니다.",
    ),
)

#: Tutorials that describe the same screen as a help page section. The page links
#: to it; the Markdown copy names it without link syntax so the account-only
#: documents stay free of media paths.
HELP_ANCHORS = {
    "05": ("account", "계정 탈퇴"),
    "07": ("external-ai", "외부 AI에 연결하기"),
}

#: Applied in this branch: the help page now says what the code does. The rows
#: stay so the next copy change finds the evidence beside the wording.
HELP_COPY_PROPOSALS = (
    (
        "help.html · 권한 안내(#policyTitle) 둘째 문단",
        "되돌리기 어려운 동작으로 보일 때는 실행하기 전에 묻고,",
        "로그인이 필요한 화면은 열기 전에 로그인 안내로 막습니다. "
        "로그인·결제·게시·발송처럼 되돌리기 어려운 동작은 실행하기 전에 묻습니다.",
        "반영됨 — 비로그인 요청은 401 로그인 안내(시나리오 01 3단계), 되돌리기 어려운 동작은 실행 전 확인.",
    ),
    (
        "help.html · 목차와 새 절(#account)",
        "(항목 없음)",
        "설정 > 계정 > 계정 탈퇴 → 이메일을 다시 입력해 영구 탈퇴 버튼이 켜질 때만 실행. "
        "지워지는 것: 대화·프로젝트 파일·첨부·일정·PC 연결 설정. "
        "남는 것: 공통 로그인 계정·외부 백업·PC 백업 폴더.",
        "반영됨 — POST /api/account/delete의 정확한 이메일 대조, locale.js account-delete-*, "
        "ACCOUNT_DELETION_20261103.md 표.",
    ),
)

#: Layout only. Colour, type, the 44px floor and the light theme come from
#: styles.css + help.css, so these pages look like the help page they sit beside.
TUTORIAL_CSS = """/* #6724 2 — tutorial pages. Layout only: colour, type and the 44px floor come
   from styles.css and help.css, so the help page's theme reaches these too. */

.chat-help-nav { display: flex; gap: 8px; flex-wrap: wrap; }

.tutorial-shot { margin: 14px 0 0; }
.tutorial-shot img {
  display: block;
  width: 100%;
  max-width: 100%;
  height: auto;
  border: 1px solid var(--line, #e3e3e9);
  border-radius: 12px;
  background: var(--panel, #fff);
}
.tutorial-shot figcaption { margin-top: 6px; color: var(--muted, #6f7079); font-size: 14px; }

.chat-help-video-slot {
  margin: 0;
  padding: 12px 14px;
  border: 1px dashed var(--line, #e3e3e9);
  border-radius: 12px;
  color: var(--muted, #6f7079);
}

.tutorial-index { margin: 0; padding: 0; list-style: none; }
.tutorial-index li { margin: 0 0 14px; }
.tutorial-index a {
  display: inline-flex;
  align-items: center;
  min-height: 44px;
  font-weight: 650;
  color: var(--accent-strong, #5546d6);
}
.tutorial-index p { margin: 4px 0 0; color: var(--muted, #6f7079); }
"""


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
    #: Steps that were actually recorded with the owner's signed-in session.
    #: Their images are committed; every other account step keeps the placeholder.
    captured = _numbers(_field(lines, "**촬영한 단계:**"))
    outside = [number for number in captured if number not in guest + account]
    if outside:
        raise ValueError(f"captured step outside the screenplay ({path.name}): {outside}")
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
        "captured": captured,
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
    ]
    anchor = HELP_ANCHORS.get(document["number"])
    if anchor:
        slug, title = anchor
        lines.extend(
            [
                f"**도움말 함께 보기:** 사용 안내(help.html)의 {title} 절(#{slug})과 같은 내용입니다.",
                "",
            ]
        )
    lines.extend(["## 단계", ""])
    for step in document["steps"]:
        shown = step["number"] in document["guest"] or step["number"] in document["captured"]
        lines.extend([f"### {step['number']}단계 · {step['caption']}", ""])
        if not shown:
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
        if shown:
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
            (
                f"⑦ 외부 AI 연결은 대본만 있고, ``help.html``에 {PENDING_MARK} 표시가 남아 있는 동안은 "
                "화면을 촬영하지 않습니다."
            ),
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
            "## 화면 페이지",
            "",
            f"``apps/padiem-chat/static/help-tutorials``에 같은 대본으로 6장(목차 1장 + 튜토리얼 5장)을 만듭니다. "
            "도움말 화면과 같은 ``styles.css``·``help.css``를 쓰고, 단계 화면은 ``assets/<문서>/step-NN.webp``로 "
            f"저장소에 넣었습니다(장당 {MAX_IMAGE_BYTES // 1024}KB 이하). 사용 안내(``help.html``) 목차에서 "
            "``./help-tutorials/index.html``로 이어집니다.",
            "",
            f"영상과 자막은 저장소에 넣지 않습니다. 페이지에는 \"영상 준비 중\" 자리만 두고, 나중에 고정 주소를 "
            f"넣을 설정 키는 ``{VIDEO_KEY_ENV}``입니다(예: ``{VIDEO_KEY_ENV}/<문서>/video.webm``).",
            "",
            "## 도움말 문안 대조(반영됨)",
            "",
            "``apps/padiem-chat/static/help.html``에 아래 두 문안을 반영했습니다. 다음에 문구를 바꿀 때 "
            "근거를 볼 수 있게 표로 남깁니다.",
            "",
            "| 위치 | 이전 문구 | 지금 문구 | 근거 |",
            "|---|---|---|---|",
        ]
    )
    for where, current, proposal, why in HELP_COPY_PROPOSALS:
        lines.append(f"| {where} | “{current}” | {proposal} | {why} |")
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


def _step_section(document: dict, step: dict) -> list[str]:
    guest = (
        step["number"] in document["guest"] or step["number"] in document["captured"]
    )
    anchor = f"step-{step['number']}"
    lines = [
        f'      <section class="chat-help-section" id="{anchor}" aria-labelledby="{anchor}Title">',
        (
            f'        <h2 id="{anchor}Title">{step["number"]}단계 · '
            f'{escape(step["caption"])}</h2>'
        ),
    ]
    if not guest:
        lines.append(f'        <p class="chat-help-caution">{escape(PLACEHOLDER)}</p>')
    lines.extend(
        [
            f'        <p class="chat-help-desc"><strong>이렇게 해요:</strong> {escape(step["action"])}</p>',
            (
                '        <p class="chat-help-desc"><strong>이렇게 보여요:</strong> '
                f'{escape(step["expected"])}</p>'
            ),
        ]
    )
    if step["checked"]:
        lines.append(
            '        <p class="chat-help-detail"><strong>화면에서 확인하는 것:</strong> '
            f'{escape(step["checked"])}</p>'
        )
    if guest:
        image = f"./assets/{document['key']}/step-{step['number']:02d}.webp"
        lines.extend(
            [
                '        <figure class="tutorial-shot">',
                (
                    f'          <img src="{image}" alt="{escape(step["caption"])} 화면"'
                    ' width="1280" height="900" decoding="async" />'
                ),
                f'          <figcaption>{escape(step["caption"])}</figcaption>',
                '        </figure>',
            ]
        )
    lines.append('      </section>')
    return lines


def _anchor_link(document: dict) -> str:
    """A link to the matching help page section, or an empty line when none."""

    anchor = HELP_ANCHORS.get(document["number"])
    if not anchor:
        return ""
    slug, title = anchor
    return (
        '    <p class="chat-help-detail"><strong>도움말 함께 보기:</strong> '
        f'<a href="../help.html#{slug}">{escape(title)}</a></p>'
    )


def render_page(document: dict) -> str:
    """One tutorial as a static page beside help.html."""

    lines = [
        '<!doctype html>',
        '<html lang="ko">',
        '<head>',
        '  <meta charset="utf-8" />',
        '  <meta name="viewport" content="width=device-width, initial-scale=1" />',
        '  <meta name="color-scheme" content="light" />',
        '  <meta name="robots" content="noindex" />',
        f'  <title>{escape(document["title"])} — Padiem Chat 튜토리얼</title>',
        '  <link rel="icon" href="data:," />',
        '  <link rel="stylesheet" href="../styles.css" />',
        '  <link rel="stylesheet" href="../help.css" />',
        '  <link rel="stylesheet" href="./tutorial.css" />',
        '  <!-- tools/tutorial/build_tutorials.py가 docs/qa/scenarios/',
        f'{document["file"]}에서 만든 페이지입니다. 대본을 고치고 다시 생성하세요.',
        f'       영상·자막 주소는 {VIDEO_KEY_ENV}/',
        f'{MEDIA_KEY_ROOT}/{document["key"]}/video.webm 로 나중에 붙입니다. -->',
        '</head>',
        '<body class="chat-help-body">',
        '  <a class="chat-help-skip" href="#tutorialMain">본문으로 건너뛰기</a>',
        '  <header class="chat-help-header">',
        '    <div class="chat-help-brand">',
        '      <span class="chat-help-brand-mark" aria-hidden="true">P</span>',
        f'      <span class="chat-help-brand-name">{escape(document["title"])}</span>',
        '    </div>',
        '    <nav class="chat-help-nav" aria-label="이동">',
        '      <a class="chat-help-back" href="./index.html">튜토리얼 목록</a>',
        '      <a class="chat-help-back" href="../help.html">사용 안내</a>',
        '    </nav>',
        '  </header>',
        '  <main id="tutorialMain" class="chat-help-main">',
        f'    <h1>{escape(document["title"])}</h1>',
        f'    <p class="chat-help-lede">{escape(document["purpose"])}</p>',
        f'    <p class="chat-help-detail"><strong>준비물:</strong> {escape(_preparation(document))}</p>',
        _anchor_link(document),
        '    <nav class="chat-help-toc" aria-label="이 튜토리얼의 단계">',
        '      <ul>',
    ]
    for step in document["steps"]:
        lines.append(
            f'        <li><a href="#step-{step["number"]}">'
            f'{step["number"]}단계 · {escape(step["caption"])}</a></li>'
        )
    lines.extend(['      </ul>', '    </nav>'])
    for step in document["steps"]:
        lines.extend(_step_section(document, step))

    lines.extend(
        [
            '      <section class="chat-help-section" id="media" aria-labelledby="mediaTitle">',
            '        <h2 id="mediaTitle">영상과 자막</h2>',
            (
                '        <p class="chat-help-video-slot">영상 준비 중 — 녹화와 자막은 아직 '
                '이 화면에 올리지 않았습니다.</p>'
            ),
        ]
    )
    if document["guest"]:
        lines.append(
            f'        <p class="chat-help-detail">촬영 범위: 게스트 '
            f'{_format_numbers(document["guest"])}단계.</p>'
        )
        if document["account"]:
            lines.append(
                f'        <p class="chat-help-detail">계정 {_format_numbers(document["account"])}단계는 '
                f'{escape(PLACEHOLDER)}로 두고 같은 자리에 이어 붙입니다.</p>'
            )
    else:
        lines.append(
            '        <p class="chat-help-detail">아직 촬영하지 않았습니다 — 이 시나리오는 계정 '
            '단계로만 이루어져 있습니다.</p>'
        )
    lines.extend(
        [
            '      </section>',
            '    <p class="chat-help-foot">',
            '      이 안내는 대본에서 자동으로 만들어집니다.',
            '      <a href="./index.html">튜토리얼 목록</a>',
            '      <a href="../help.html">사용 안내</a>',
            '    </p>',
            '  </main>',
            '</body>',
            '</html>',
        ]
    )
    return "\n".join(lines) + "\n"


def render_index(documents: list[dict]) -> str:
    items: list[str] = []
    for document in documents:
        guest = _format_numbers(document["guest"])
        account = _format_numbers(document["account"])
        if guest and account:
            scope = f"로그인 없이 {guest}단계, {account}단계는 화면 준비 중"
        elif guest:
            scope = f"로그인 없이 {guest}단계"
        else:
            scope = "계정 준비 중 — 화면 자리만 있습니다"
        items.extend(
            [
                '        <li>',
                (
                    f'          <a href="./{document["number"]}-{document["slug"]}.html">'
                    f'{escape(document["title"])}</a>'
                ),
                f'          <p>{escape(document["purpose"])} · {scope}</p>',
                '        </li>',
            ]
        )
    lines = [
        '<!doctype html>',
        '<html lang="ko">',
        '<head>',
        '  <meta charset="utf-8" />',
        '  <meta name="viewport" content="width=device-width, initial-scale=1" />',
        '  <meta name="color-scheme" content="light" />',
        '  <meta name="robots" content="noindex" />',
        '  <title>단계별 튜토리얼 — Padiem Chat</title>',
        '  <link rel="icon" href="data:," />',
        '  <link rel="stylesheet" href="../styles.css" />',
        '  <link rel="stylesheet" href="../help.css" />',
        '  <link rel="stylesheet" href="./tutorial.css" />',
        '  <!-- tools/tutorial/build_tutorials.py가 docs/qa/scenarios에서 만든 목록입니다. -->',
        '</head>',
        '<body class="chat-help-body">',
        '  <a class="chat-help-skip" href="#tutorialMain">본문으로 건너뛰기</a>',
        '  <header class="chat-help-header">',
        '    <div class="chat-help-brand">',
        '      <span class="chat-help-brand-mark" aria-hidden="true">P</span>',
        '      <span class="chat-help-brand-name">단계별 튜토리얼</span>',
        '    </div>',
        '    <nav class="chat-help-nav" aria-label="이동">',
        '      <a class="chat-help-back" href="../help.html">사용 안내</a>',
        '      <a class="chat-help-back" href="../">채팅으로 돌아가기</a>',
        '    </nav>',
        '  </header>',
        '  <main id="tutorialMain" class="chat-help-main">',
        '    <h1>단계별 튜토리얼</h1>',
        '    <p class="chat-help-lede">화면을 따라가며 익히는 안내입니다. 모든 문서는 시나리오 '
        '대본에서 자동으로 만들어지고, 로그인이 필요한 단계는 화면 자리만 비워 두었습니다.</p>',
        '    <ul class="tutorial-index">',
    ]
    lines.extend(items)
    lines.extend(
        [
            '    </ul>',
            '    <p class="chat-help-foot">',
            '      기능 설명은 <a href="../help.html">사용 안내</a>에 있습니다.',
            '    </p>',
            '  </main>',
            '</body>',
            '</html>',
        ]
    )
    return "\n".join(lines) + "\n"


def expected_pages(documents: list[dict]) -> dict[str, str]:
    pages = {"index.html": render_index(documents), "tutorial.css": TUTORIAL_CSS}
    for document in documents:
        pages[f"{document['number']}-{document['slug']}.html"] = render_page(document)
    return pages


def expected_assets(documents: list[dict]) -> set[str]:
    return {
        f"{document['key']}/step-{number:02d}.webp"
        for document in documents
        for number in sorted(set(document["guest"]) | set(document["captured"]))
    }


def _shrink_webp(image_module, source: Path) -> bytes:
    """The largest scale that still fits MAX_IMAGE_BYTES, as one webp."""

    with image_module.open(source) as opened:
        picture = opened.convert("RGB")
    smallest = b""
    for scale in (1.0, 0.85, 0.7, 0.55, 0.45):
        width = max(320, int(picture.width * scale))
        height = max(200, round(picture.height * width / picture.width))
        frame = picture if scale == 1.0 else picture.resize((width, height), image_module.LANCZOS)
        for quality in (82, 74, 66):
            buffer = io.BytesIO()
            frame.save(buffer, format="WEBP", quality=quality, method=6)
            data = buffer.getvalue()
            if len(data) <= MAX_IMAGE_BYTES:
                return data
            smallest = data
    return smallest


def convert_shots(shots: Path, asset_dir: Path, documents: list[dict] | None = None) -> list[Path]:
    """Recorder PNGs -> one small webp per guest step, inside the page assets."""

    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - the tool documents the extra
        raise SystemExit(
            "screenshots need Pillow: python -m pip install pillow"
        ) from None
    documents = documents if documents is not None else load_scenarios()
    written: list[Path] = []
    for document in documents:
        for number in sorted(set(document["guest"]) | set(document["captured"])):
            source = shots / document["key"] / f"step-{number:02d}.png"
            if not source.is_file():
                raise SystemExit(f"missing screenshot: {source}")
            target = asset_dir / document["key"] / f"step-{number:02d}.webp"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(_shrink_webp(Image, source))
            written.append(target)
    return written


def build(
    output_dir: Path = OUTPUT_DIR,
    page_dir: Path = PAGE_DIR,
    shots: Path | None = DEFAULT_SHOTS,
) -> list[Path]:
    documents = load_scenarios()
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    # Keep generated bytes identical on Windows and Linux.
    for document in documents:
        path = output_dir / f"{document['number']}-{document['slug']}.md"
        path.write_text(render(document), encoding="utf-8", newline="\n")
        written.append(path)
    readme = output_dir / "README.md"
    readme.write_text(render_readme(documents), encoding="utf-8", newline="\n")
    written.append(readme)

    page_dir.mkdir(parents=True, exist_ok=True)
    for name, text in expected_pages(documents).items():
        path = page_dir / name
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(path)
    if shots is not None and Path(shots).is_dir():
        written.extend(convert_shots(Path(shots), page_dir / "assets", documents))
    return written


def check(output_dir: Path = OUTPUT_DIR, page_dir: Path = PAGE_DIR) -> list[str]:
    """Everything that no longer matches what the screenplays produce now.

    The image comparison is by name and size, not by bytes: webp output depends
    on the encoder version, while a missing, orphaned or oversized step image is
    the drift a reviewer has to see.
    """

    documents = load_scenarios()
    stale: list[str] = []
    expected = {f"{document['number']}-{document['slug']}.md": render(document) for document in documents}
    expected["README.md"] = render_readme(documents)
    for name, text in expected.items():
        path = output_dir / name
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            stale.append(name)

    pages = expected_pages(documents)
    for name, text in pages.items():
        path = page_dir / name
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            stale.append(f"page:{name}")
    for path in sorted(page_dir.glob("*.html")):
        if path.name not in pages:
            stale.append(f"orphan_page:{path.name}")

    assets_dir = page_dir / "assets"
    present = {
        path.relative_to(assets_dir).as_posix() for path in assets_dir.rglob("*.webp")
    } if assets_dir.is_dir() else set()
    wanted = expected_assets(documents)
    stale.extend(f"image:{name}" for name in sorted(wanted - present))
    stale.extend(f"orphan_image:{name}" for name in sorted(present - wanted))
    for name in sorted(wanted & present):
        if (assets_dir / name).stat().st_size > MAX_IMAGE_BYTES:
            stale.append(f"image_too_large:{name}")
    return stale


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--pages", type=Path, default=PAGE_DIR)
    parser.add_argument("--shots", type=Path, default=DEFAULT_SHOTS)
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="write documents and pages only (no recording folder needed)",
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        stale = check(args.output, args.pages)
        if stale:
            print("tutorials_stale=" + ",".join(sorted(stale)))
            return 1
        print("tutorials_up_to_date")
        return 0
    written = build(
        args.output, args.pages, None if args.no_images else args.shots
    )
    print(f"tutorials_written={len(written)} output={args.output} pages={args.pages}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
