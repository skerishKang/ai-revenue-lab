#!/usr/bin/env python3
"""Generate the Business 35 diagnostic questionnaire DOCX.

Sections follow 03-diagnostic-questionnaire.md plus the structured areas
specified for the customer package. No personal data entry is requested.
"""

from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

OUT = "docs/commercial/business-35-ai-media-education-dx/customer-package/Business35_Diagnostic_Questionnaire.docx"

NAVY = RGBColor(0x1F, 0x3A, 0x5F)
GRAY = RGBColor(0x55, 0x5A, 0x60)


def heading(doc, text, level=1):
    h = doc.add_heading(text, level=level)
    for run in h.runs:
        run.font.color.rgb = NAVY
        run.font.name = "Malgun Gothic"
    return h


def q(doc, num, question, guide, required=True):
    p = doc.add_paragraph()
    r = p.add_run(f"{num}. {question}")
    r.bold = True
    r.font.size = Pt(11)
    r.font.name = "Malgun Gothic"
    p2 = doc.add_paragraph()
    r2 = p2.add_run(f"   (답변 형식·확인 목적: {guide})")
    r2.font.size = Pt(9)
    r2.font.color.rgb = GRAY
    r2.font.name = "Malgun Gothic"
    ans = doc.add_paragraph()
    ar = ans.add_run("답변: ")
    ar.font.size = Pt(11)
    ar.font.name = "Malgun Gothic"
    ans.paragraph_format.space_after = Pt(12)


def build():
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Malgun Gothic"
    style.font.size = Pt(11)

    title = doc.add_heading("Business 35 · AI 업무전환 프로그램", level=0)
    for run in title.runs:
        run.font.color.rgb = NAVY

    p = doc.add_paragraph()
    r = p.add_run("고객 진단 질문지 (DRAFT)")
    r.bold = True
    r.font.size = Pt(14)
    r.font.color.rgb = NAVY

    status = doc.add_paragraph()
    sr = status.add_run(
        "CUSTOMER-FACING MASTER · FINAL IDENTITY REQUIRED · LEGAL REVIEW REQUIRED · NOT YET SENT\n"
        "제안 제공자 정보는 발송 전 최종 확정\n"
        "실제 개인정보나 내부자료를 기입하도록 요구하지 않습니다."
    )
    sr.font.size = Pt(10)
    sr.font.color.rgb = GRAY
    sr.font.name = "Malgun Gothic"

    heading(doc, "1. 조직·팀 기본정보", 1)
    q(doc, 1.1, "조직 이름과 소속 팀, 팀 인원은 어떻게 되나요?", "자유 텍스트 (직책·인원만)", True)
    q(doc, 1.2, "콘텐츠·홍보·교육 업무를 담당하는 인력은 몇 명인가요?", "숫자", True)

    heading(doc, "2. 현재 콘텐츠 업무", 1)
    q(doc, 2.1, "현재 콘텐츠 제작이 어떤 단계로 진행되나요? (기획→초안→검토→승인→게시)", "단계 나열", True)
    q(doc, 2.2, "주요 콘텐츠 유형은 무엇인가요? (홍보물·안내문·뉴스레터·SNS 등)", "유형 목록", True)

    heading(doc, "3. 소요시간", 1)
    q(doc, 3.1, "콘텐츠 1건당 각 단계에 며칠/몇 시간이 걸리나요?", "단계별 시간 표", True)
    q(doc, 3.2, "가장 오래 걸리는 단계는 무엇인가요?", "자유 텍스트", True)

    heading(doc, "4. 검토 단계", 1)
    q(doc, 4.1, "검토와 승인이 몇 단계이며, 누가 승인하나요?", "단계 목록 + 직책", True)
    q(doc, 4.2, "검토·승인 기준은 문서화되어 있나요?", "예/아니오/부분", True)

    heading(doc, "5. AI 사용 현황", 1)
    q(doc, 5.1, "조직원이 현재 사용하는 AI 도구와 용도는 무엇인가요?", "도구명 + 용도", True)
    q(doc, 5.2, "조직 차원의 AI 사용정책이 있나요?", "예/아니오", True)

    heading(doc, "6. 입력 금지 자료", 1)
    q(doc, 6.1, "AI에 절대 입력하면 안 되는 자료(비밀·기밀·법률 검토 필요)가 있나요?", "유형 분류만", True)

    heading(doc, "7. 개인정보", 1)
    q(doc, 7.1, "제작 콘텐츠에 개인정보(이름·연락처 등)가 포함됩니까?", "예/아니오/일부 + 위치 분류", True)

    heading(doc, "8. 저작권", 1)
    q(doc, 8.1, "타인 저작물을 사용하거나 외부 학습에 쓸 자료가 있나요?", "예/아니오/일부 + 유형", True)

    heading(doc, "9. 승인 책임자", 1)
    q(doc, 9.1, "파일럿 예산과 결과를 최종 승인할 수 있는 사람(직책)은 누구인가요?", "직책", True)

    heading(doc, "10. 기준선 데이터", 1)
    q(doc, 10.1, "기준선(생산시간·재작업률 등)으로 쓸 수 있는 데이터가 있나요?", "가능 항목 나열", True)

    heading(doc, "11. 파일럿 후보 업무", 1)
    q(doc, 11.1, "6주 파일럿 후보 업무 1개를 고른다면 무엇인가요?", "1건 선택", True)
    q(doc, 11.2, "참여 팀(6–10명)과 운영 책임자 1인을 지정할 수 있나요?", "역할·인원", True)

    heading(doc, "12. 성공 기준", 1)
    q(doc, 12.1, "파일럿이 성공했다고 판단하는 기준은 무엇인가요?", "예: 생산시간 단축, 품질 유지", True)

    heading(doc, "13. 중단 조건", 1)
    q(doc, 13.1, "어떤 경우에 파일럿을 중단해야 하나요? (위험업무 침범·자동 게시 요구 등)", "자유 텍스트", True)

    closing = doc.add_paragraph()
    cr = closing.add_run(
        "\n본 질문지는 견적·일정 확정 전 진단 자료로만 사용됩니다. "
        "가격은 시장 검증 전 자사 가격 가설이며 실제 계약·매출 주장이 아닙니다."
    )
    cr.font.size = Pt(9)
    cr.font.color.rgb = GRAY

    doc.save(OUT)
    print(f"saved {OUT}")


if __name__ == "__main__":
    build()
