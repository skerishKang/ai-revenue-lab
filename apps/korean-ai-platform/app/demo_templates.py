"""Code-defined demo template catalog for the user workspace.

These are static fixtures — no DB table is added. Each template provides
prefill values for the existing task creation form.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DemoTemplate:
    id: str
    title: str
    short_description: str
    suggested_task_title: str
    suggested_instruction: str
    suggested_project_id: str
    image_path: str
    suggested_allowed: list[str] = field(default_factory=list)
    suggested_denied: list[str] = field(default_factory=list)


TEMPLATES: list[DemoTemplate] = [
    DemoTemplate(
        id="website",
        title="웹사이트 만들기",
        short_description="랜딩 페이지, 소개 사이트, 포트폴리오 등 웹페이지를 제작합니다.",
        suggested_task_title="회사 소개 랜딩 페이지 제작",
        suggested_instruction=(
            "회사 소개용 랜딩 페이지를 만들어 주세요. "
            "히어로 섹션, 서비스 소개, 연락처 폼을 포함하고 "
            "반응형으로 동작해야 합니다."
        ),
        suggested_project_id="internal-docs",
        image_path="/static/images/templates/website.svg",
        suggested_allowed=["web/", "docs/"],
        suggested_denied=[],
    ),
    DemoTemplate(
        id="document",
        title="문서 요약하기",
        short_description="긴 문서나 회의록을 핵심만 추려 요약합니다.",
        suggested_task_title="분기 보고서 핵심 요약",
        suggested_instruction=(
            "첨부된 분기 보고서를 핵심 지표, 주요 성과, "
            "리스크 요인 세 가지로 나누어 한 페이지 분량으로 "
            "요약해 주세요."
        ),
        suggested_project_id="internal-docs",
        image_path="/static/images/templates/document.svg",
        suggested_allowed=["docs/"],
        suggested_denied=[],
    ),
    DemoTemplate(
        id="research",
        title="자료 조사하기",
        short_description="특정 주제에 대한 시장·기술 자료를 조사하고 정리합니다.",
        suggested_task_title="경쟁 제품 기능 비교 조사",
        suggested_instruction=(
            "주요 경쟁 제품 3개의 핵심 기능, 가격 정책, "
            "차별점을 비교 표로 정리해 주세요. "
            "출처를 함께 명시해 주세요."
        ),
        suggested_project_id="internal-docs",
        image_path="/static/images/templates/research.svg",
        suggested_allowed=["docs/"],
        suggested_denied=[],
    ),
    DemoTemplate(
        id="data",
        title="데이터 정리하기",
        short_description="흩어진 데이터를 정제하고 구조를 맞춥니다.",
        suggested_task_title="고객 데이터 정제 및 표준화",
        suggested_instruction=(
            "고객 데이터 CSV에서 중복 행을 제거하고, "
            "전화번호·이메일 형식을 표준화한 뒤 "
            "누락 값 비율을 보고해 주세요."
        ),
        suggested_project_id="data-pipeline",
        image_path="/static/images/templates/data.svg",
        suggested_allowed=["src/", "tests/"],
        suggested_denied=["infra/", "secrets/"],
    ),
    DemoTemplate(
        id="marketing",
        title="홍보 문구 만들기",
        short_description="제품·서비스 홍보를 위한 문구와 카피를 작성합니다.",
        suggested_task_title="신제품 출시 홍보 카피 작성",
        suggested_instruction=(
            "신제품 출시를 위한 홍보 문구를 작성해 주세요. "
            "SNS용 짧은 문구 3개, 이메일 제목 2개, "
            "상세 페이지 소개 문단 1개를 포함해 주세요."
        ),
        suggested_project_id="internal-docs",
        image_path="/static/images/templates/marketing.svg",
        suggested_allowed=["docs/", "web/"],
        suggested_denied=[],
    ),
    DemoTemplate(
        id="code",
        title="코드 수정하기",
        short_description="버그 수정, 기능 추가, 리팩터링 등 코드 작업을 요청합니다.",
        suggested_task_title="주문 API 오류 처리 개선",
        suggested_instruction=(
            "주문 생성 API에서 재고 부족 시 500 오류가 "
            "발생하는 문제를 수정해 주세요. "
            "적절한 HTTP 상태 코드와 오류 메시지를 반환하고 "
            "테스트를 추가해 주세요."
        ),
        suggested_project_id="commerce-backend",
        image_path="/static/images/templates/code.svg",
        suggested_allowed=["app/", "tests/"],
        suggested_denied=["migrations/"],
    ),
]

TEMPLATES_BY_ID: dict[str, DemoTemplate] = {t.id: t for t in TEMPLATES}


def get_template(template_id: str) -> DemoTemplate | None:
    return TEMPLATES_BY_ID.get(template_id)
