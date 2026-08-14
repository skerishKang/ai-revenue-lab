#!/usr/bin/env python3
"""Generate the Business 35 diagnostic questionnaire DOCX (3 pages).

- Title in one/two natural lines
- Page headers repeated per page
- Narrative questions get 2-3 answer lines
- Yes/No questions get real checkboxes; choice questions get selection cells
- No internal English status markers in the customer document
- Notice block at the bottom of the last page
- 3 pages maximum
"""

from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_BREAK

OUT = "docs/commercial/business-35-ai-media-education-dx/customer-package/Business35_Diagnostic_Questionnaire.docx"

NAVY = RGBColor(0x1F, 0x3A, 0x5F)
GRAY = RGBColor(0x55, 0x5A, 0x60)


def heading(doc, text):
    h = doc.add_heading(text, level=1)
    for run in h.runs:
        run.font.color.rgb = NAVY
        run.font.name = "Malgun Gothic"
        run.font.size = Pt(13)
    return h


def narrative(doc, num, question, guide):
    p = doc.add_paragraph()
    r = p.add_run(f"{num}. {question}")
    r.bold = True
    r.font.size = Pt(10.5)
    r.font.name = "Malgun Gothic"
    p2 = doc.add_paragraph()
    r2 = p2.add_run(f"({guide})")
    r2.font.size = Pt(8.5)
    r2.font.color.rgb = GRAY
    r2.font.name = "Malgun Gothic"
    for _ in range(2):
        line = doc.add_paragraph()
        lr = line.add_run("_" * 60)
        lr.font.size = Pt(11)
        lr.font.name = "Malgun Gothic"
        line.paragraph_format.space_after = Pt(8)


def short_answer(doc, num, question, guide):
    p = doc.add_paragraph()
    r = p.add_run(f"{num}. {question}")
    r.bold = True
    r.font.size = Pt(10.5)
    r.font.name = "Malgun Gothic"
    p2 = doc.add_paragraph()
    r2 = p2.add_run(f"({guide})")
    r2.font.size = Pt(8.5)
    r2.font.color.rgb = GRAY
    r2.font.name = "Malgun Gothic"
    line = doc.add_paragraph()
    lr = line.add_run("_" * 60)
    lr.font.size = Pt(11)
    lr.font.name = "Malgun Gothic"
    line.paragraph_format.space_after = Pt(8)


def yesno(doc, num, question, options):
    p = doc.add_paragraph()
    r = p.add_run(f"{num}. {question}")
    r.bold = True
    r.font.size = Pt(10.5)
    r.font.name = "Malgun Gothic"
    op = doc.add_paragraph()
    for label in options:
        run = op.add_run(f"  ☐  {label}")
        run.font.size = Pt(10.5)
        run.font.name = "Malgun Gothic"
    op.paragraph_format.space_after = Pt(8)


def choice(doc, num, question, options):
    p = doc.add_paragraph()
    r = p.add_run(f"{num}. {question}")
    r.bold = True
    r.font.size = Pt(10.5)
    r.font.name = "Malgun Gothic"
    op = doc.add_paragraph()
    for label in options:
        run = op.add_run(f"  ☐  {label}    ")
        run.font.size = Pt(10.5)
        run.font.name = "Malgun Gothic"
    op.paragraph_format.space_after = Pt(8)


def page_header(doc, title, page_no):
    ph = doc.add_paragraph()
    pr = ph.add_run("파디엠 · AI 업무전환 진단 질문지   ")
    pr.font.size = Pt(10)
    pr.font.bold = True
    pr.font.color.rgb = NAVY
    pr.font.name = "Malgun Gothic"
    pt = ph.add_run(title + "   ")
    pt.font.size = Pt(12)
    pt.font.bold = True
    pt.font.color.rgb = NAVY
    pt.font.name = "Malgun Gothic"
    prr = ph.add_run(f"[ {page_no} / 3 ]")
    prr.font.size = Pt(9)
    prr.font.color.rgb = GRAY
    prr.font.name = "Malgun Gothic"
    ph.paragraph_format.space_after = Pt(8)


def page_break(doc):
    p = doc.add_paragraph()
    p.add_run().add_break(WD_BREAK.PAGE)


def build():
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Malgun Gothic"
    style.font.size = Pt(10.5)

    # Narrower margins to fit 3 pages
    for section in doc.sections:
        section.top_margin = Inches(0.5)
        section.bottom_margin = Inches(0.5)
        section.left_margin = Inches(0.6)
        section.right_margin = Inches(0.6)

    # ---- Page 1 ----
    title = doc.add_heading("Business 35 · AI 업무전환 프로그램", level=0)
    for run in title.runs:
        run.font.color.rgb = NAVY
        run.font.name = "Malgun Gothic"
        run.font.size = Pt(20)

    sub = doc.add_paragraph()
    sr = sub.add_run("고객 진단 질문지 · 작성 전 안내")
    sr.font.size = Pt(13)
    sr.font.bold = True
    sr.font.color.rgb = NAVY

    guide = doc.add_paragraph()
    gr = guide.add_run(
        "본 질문지는 견적·일정 확정 전 진단 자료로만 사용됩니다. "
        "실제 개인정보나 내부자료의 원문을 기입하지 마시고, 분류·포함 여부만 표시해 주세요."
    )
    gr.font.size = Pt(9)
    gr.font.color.rgb = GRAY
    gr.font.name = "Malgun Gothic"

    page_header(doc, "1. 조직·팀 기본정보", 1)
    narrative(doc, "1.1", "조직 이름과 소속 팀, 팀 인원은 어떻게 되나요?", "조직명·직책·인원만 기재")
    yesno(doc, "1.2", "콘텐츠·홍보·교육 업무를 담당하는 인력이 있나요?", ["예", "아니오"])

    page_header(doc, "2. 현재 콘텐츠 업무", 1)
    narrative(doc, "2.1", "현재 콘텐츠 제작이 어떤 단계로 진행되나요?", "기획→초안→검토→승인→게시 순으로")
    choice(doc, "2.2", "주요 콘텐츠 유형은 무엇인가요?", ["홍보물", "안내문", "뉴스레터", "SNS", "기타"])

    page_header(doc, "3. 소요시간", 1)
    narrative(doc, "3.1", "콘텐츠 1건당 각 단계에 며칠/몇 시간이 걸리나요?", "단계별 시간 표")
    short_answer(doc, "3.2", "가장 오래 걸리는 단계는 무엇인가요?", "짧게")

    page_break(doc)

    # ---- Page 2 ----
    page_header(doc, "4. 검토 단계", 2)
    narrative(doc, "4.1", "검토와 승인이 몇 단계이며, 누가 승인하나요?", "단계 목록 + 직책")
    yesno(doc, "4.2", "검토·승인 기준은 문서화되어 있나요?", ["예", "아니오", "부분"])

    page_header(doc, "5. AI 사용 현황", 2)
    narrative(doc, "5.1", "조직원이 현재 사용하는 AI 도구와 용도는 무엇인가요?", "도구명 + 용도")
    yesno(doc, "5.2", "조직 차원의 AI 사용정책이 있나요?", ["예", "아니오"])

    page_header(doc, "6. 입력 금지 자료", 2)
    narrative(doc, "6.1", "AI에 절대 입력하면 안 되는 자료가 있나요?", "비밀·기밀·법률 검토 필요 자료 — 유형 분류만")

    page_header(doc, "7. 개인정보", 2)
    choice(doc, "7.1", "제작 콘텐츠에 개인정보가 포함됩니까?", ["예", "아니오", "일부"])

    page_header(doc, "8. 저작권", 2)
    choice(doc, "8.1", "타인 저작물을 사용하거나 외부 학습에 쓸 자료가 있나요?", ["예", "아니오", "일부"])

    page_header(doc, "9. 승인 책임자", 2)
    short_answer(doc, "9.1", "파일럿 예산과 결과를 최종 승인할 수 있는 사람은 누구인가요?", "직책만")

    page_break(doc)

    # ---- Page 3 ----
    page_header(doc, "10. 기준선 데이터", 3)
    narrative(doc, "10.1", "기준선(생산시간·재작업률 등)으로 쓸 수 있는 데이터가 있나요?", "가능 항목 나열")

    page_header(doc, "11. 파일럿 후보 업무", 3)
    narrative(doc, "11.1", "6주 파일럿 후보 업무 1개를 고른다면 무엇인가요?", "1건 선택")
    yesno(doc, "11.2", "참여 팀(6–10명)과 운영 책임자 1인을 지정할 수 있나요?", ["예", "아니오"])

    page_header(doc, "12. 성공 기준", 3)
    narrative(doc, "12.1", "파일럿이 성공했다고 판단하는 기준은 무엇인가요?", "예: 생산시간 단축, 품질 유지")

    page_header(doc, "13. 중단 조건", 3)
    narrative(doc, "13.1", "어떤 경우에 파일럿을 중단해야 하나요?", "위험업무 침범·자동 게시 요구 등")

    closing = doc.add_paragraph()
    cr = closing.add_run(
        "\n본 질문지는 견적·일정 확정 전 진단 자료로만 사용됩니다. "
        "가격은 시장 검증 전 자사 가격 가설이며 실제 계약·매출 주장이 아닙니다. "
        "조직별 사용정책·검토체계, 개인정보·저작권·조달 관련 사항은 고객별 확인과 "
        "전문 법률·계약 검토가 필요합니다."
    )
    cr.font.size = Pt(9)
    cr.font.color.rgb = GRAY
    cr.font.name = "Malgun Gothic"

    doc.save(OUT)
    print(f"saved {OUT}")


if __name__ == "__main__":
    build()
