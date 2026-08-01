#!/usr/bin/env python3
"""Generate the Business 35 customer-facing master proposal PPTX (10 slides, 16:9).

All text and shapes are editable. Each slide carries a footer page number and
speaker notes. No external images, no fonts, no stock assets.
"""

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

OUT = "docs/commercial/business-35-ai-media-education-dx/customer-package/Business35_Master_Proposal_10p.pptx"

NAVY = RGBColor(0x1F, 0x3A, 0x5F)
BLUE = RGBColor(0x2E, 0x5E, 0x8C)
GRAY = RGBColor(0x55, 0x5A, 0x60)
LIGHT = RGBColor(0xF2, 0xF4, 0xF7)
ACCENT = RGBColor(0xC2, 0x7B, 0x2D)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

SW, SH = Inches(13.333), Inches(7.5)

STATUS = "CUSTOMER-FACING MASTER · FINAL IDENTITY REQUIRED · LEGAL REVIEW REQUIRED · NOT YET SENT"
PROVIDER = "제안 제공자 정보는 발송 전 최종 확정"

TOTAL_SLIDES = 10


def new_deck():
    prs = Presentation()
    prs.slide_width = SW
    prs.slide_height = SH
    return prs


def add_slide(prs, title):
    layout = prs.slide_layouts[6]  # blank
    slide = prs.slides.add_slide(layout)
    # Background
    bg = slide.shapes.add_shape(1, 0, 0, SW, SH)
    bg.fill.solid()
    bg.fill.fore_color.rgb = LIGHT
    bg.line.fill.background()
    bg.shadow.inherit = False
    # Title band
    band = slide.shapes.add_shape(1, 0, 0, SW, Inches(1.15))
    band.fill.solid()
    band.fill.fore_color.rgb = NAVY
    band.line.fill.background()
    band.shadow.inherit = False
    tf = band.text_frame
    tf.margin_left = Inches(0.55)
    tf.margin_right = Inches(0.4)
    tf.margin_top = Inches(0.18)
    tf.margin_bottom = Inches(0.12)
    tf.word_wrap = True
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = title
    r.font.size = Pt(30)
    r.font.bold = True
    r.font.color.rgb = WHITE
    r.font.name = "Malgun Gothic"
    # Footer
    footer = slide.shapes.add_textbox(Inches(0.55), Inches(7.05), Inches(9.5), Inches(0.35))
    ftf = footer.text_frame
    ftf.word_wrap = True
    fp = ftf.paragraphs[0]
    fr = fp.add_run()
    fr.text = STATUS + "  ·  " + PROVIDER
    fr.font.size = Pt(9)
    fr.font.color.rgb = GRAY
    fr.font.name = "Malgun Gothic"
    return slide


def add_body_box(slide, x, y, w, h):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0.1)
    tf.margin_right = Inches(0.1)
    tf.margin_top = Inches(0.05)
    tf.margin_bottom = Inches(0.05)
    return tf


def add_page_number(prs, slide, n):
    pn = slide.shapes.add_textbox(Inches(12.35), Inches(7.05), Inches(0.8), Inches(0.35))
    tf = pn.text_frame
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.RIGHT
    r = p.add_run()
    r.text = f"{n} / {TOTAL_SLIDES}"
    r.font.size = Pt(10)
    r.font.color.rgb = GRAY
    r.font.name = "Malgun Gothic"


def para(tf, text, size=16, bold=False, color=GRAY, level=0, bullet=False, space_after=6, first=False):
    p = tf.paragraphs[0] if first and not tf.paragraphs[0].runs else tf.add_paragraph()
    p.level = level
    p.space_after = Pt(space_after)
    if bullet:
        r = p.add_run()
        r.text = "•  " + text
    else:
        r = p.add_run()
        r.text = text
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.color.rgb = color
    r.font.name = "Malgun Gothic"
    return p


def add_step_box(slide, x, y, w, h, label, num):
    box = slide.shapes.add_shape(5, x, y, w, h)  # rounded rect
    box.fill.solid()
    box.fill.fore_color.rgb = BLUE
    box.line.color.rgb = NAVY
    box.line.width = Pt(1)
    box.shadow.inherit = False
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0.08)
    tf.margin_right = Inches(0.08)
    tf.margin_top = Inches(0.04)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = num
    r.font.size = Pt(18)
    r.font.bold = True
    r.font.color.rgb = WHITE
    p2 = tf.add_paragraph()
    p2.alignment = PP_ALIGN.CENTER
    r2 = p2.add_run()
    r2.text = label
    r2.font.size = Pt(13)
    r2.font.color.rgb = WHITE
    r2.font.name = "Malgun Gothic"


def add_notes(slide, core, questions, caution):
    notes = slide.notes_slide.notes_text_frame
    notes.text = (
        "핵심 말할 내용: " + core + "\n\n"
        "고객에게 물어볼 질문: " + questions + "\n\n"
        "과장해서는 안 되는 부분: " + caution
    )


def build():
    prs = new_deck()

    # ---- Slide 1 ----
    s = add_slide(prs, "1. 현재 문제")
    tf = add_body_box(s, Inches(0.7), Inches(1.5), Inches(11.9), Inches(5.2))
    para(tf, "콘텐츠 제작·검토가 수작업", size=20, bold=True, color=NAVY, first=True)
    para(tf, "홍보물·안내문·뉴스레터를 만드는 데 여러 단계의 수동 검토가 걸립니다.", size=16)
    para(tf, "", size=8)
    para(tf, "AI 사용이 개인 단위", size=20, bold=True, color=NAVY)
    para(tf, "조직원마다 개인적으로 AI 도구를 쓰지만, 조직 차원의 기준은 없습니다.", size=16)
    para(tf, "", size=8)
    para(tf, "조직 기준 부재", size=20, bold=True, color=NAVY)
    para(tf, "검토·승인 기준, 사용정책, 금지 업무 규칙이 없어 위험이 커집니다.", size=16)
    add_notes(
        s,
        "고객 조직의 콘텐츠 제작이 수작업에 의존하고, AI는 개인 단위로만 쓰이며, 검토·승인 기준이 없다는 점을 공감하며 설명한다.",
        "현재 콘텐츠 1건을 만드는 데 며칠이 걸리나요? 검토는 몇 단계인가요?",
        "통계로 고객을 압박하지 않고, 고객의 실제 상황을 묻는 데 집중한다."
    )
    add_page_number(prs, s, 1)

    # ---- Slide 2 ----
    s = add_slide(prs, "2. 일반 AI 교육의 한계")
    tf = add_body_box(s, Inches(0.7), Inches(1.5), Inches(11.9), Inches(5.2))
    para(tf, "강의를 들어도 실제 업무가 바뀌지 않음", size=20, bold=True, color=NAVY, first=True)
    para(tf, "지식 전달은 되지만, 조직의 실제 업무 흐름과 연결되지 않으면 변화가 일어나지 않습니다.", size=16)
    para(tf, "", size=8)
    para(tf, "정책·검토·승인·성과 측정과 연결되지 않음", size=20, bold=True, color=NAVY)
    para(tf, "교육 수료는 역량 보유를 보장하지 않습니다. 검토 gate, 승인 절차, 성과 측정이 없다면 실무 반영이 어렵습니다.", size=16)
    add_notes(
        s,
        "일반 AI 교육이 왜 실제 업무 변화로 이어지지 않는지 구조적으로 설명한다. 경쟁 강의를 비방하지 않는다.",
        "지난 교육을 받고 실제 업무에 반영된 것은 무엇인가요?",
        "교육업체를 비판하는 어조를 쓰지 않는다."
    )
    add_page_number(prs, s, 2)

    # ---- Slide 3 ----
    s = add_slide(prs, "3. Business 35 방식 — AI 업무전환 프로그램")
    tf = add_body_box(s, Inches(0.7), Inches(1.5), Inches(11.9), Inches(2.6))
    para(tf, "교육에서 끝나지 않고, 실제 업무 진단·실습·재설계·파일럿·측정·플레이북까지 연결합니다.", size=17, bold=True, color=NAVY, first=True)
    steps = [
        ("진단", "1"), ("직무 교육", "2"), ("실제 실습", "3"), ("워크플로 재설계", "4"),
        ("제한 파일럿", "5"), ("성과 측정", "6"), ("운영 플레이북", "7"),
    ]
    box_w = Inches(1.55)
    gap = Inches(0.16)
    start_x = Inches(0.7)
    y = Inches(4.1)
    h = Inches(1.5)
    for i, (label, num) in enumerate(steps):
        x = start_x + (box_w + gap) * i
        add_step_box(s, x, y, box_w, h, label, num)
    add_notes(
        s,
        "7단계 업무전환 구조를 설명하고, 결과물이 사람이 승인한 운영 플레이북임을 강조한다.",
        "현재 가장 바꾸고 싶은 업무가 무엇인가요?",
        "전체 업무 전환을 보장하지 않는다."
    )
    add_page_number(prs, s, 3)

    # ---- Slide 4 ----
    s = add_slide(prs, "4. 대상 업무 — 합성 예시")
    tf = add_body_box(s, Inches(0.7), Inches(1.45), Inches(11.9), Inches(5.2))
    para(tf, "지역 문화·교육·미디어 조직에서 자주 등장하는 대상 업무의 합성 예시입니다.", size=16, color=GRAY, first=True)
    items = [
        "행사 홍보물 초안",
        "교육 프로그램 안내문",
        "뉴스레터 초안",
        "SNS 콘텐츠 변환",
        "자료 요약",
        "검토 체크리스트",
    ]
    col1, col2 = Inches(0.7), Inches(6.5)
    row_y = Inches(2.0)
    for i, item in enumerate(items):
        x = col1 if i < 3 else col2
        yy = row_y + Inches(0.85) * (i % 3)
        box = s.shapes.add_shape(5, x, yy, Inches(5.3), Inches(0.7))
        box.fill.solid()
        box.fill.fore_color.rgb = WHITE
        box.line.color.rgb = BLUE
        box.line.width = Pt(1)
        box.shadow.inherit = False
        btf = box.text_frame
        btf.word_wrap = True
        btf.vertical_anchor = MSO_ANCHOR.MIDDLE
        bp = btf.paragraphs[0]
        br = bp.add_run()
        br.text = "•  " + item
        br.font.size = Pt(16)
        br.font.color.rgb = NAVY
        br.font.name = "Malgun Gothic"
    para(tf, "이것은 실제 고객 성과 사례가 아니라 대상 업무의 합성 예시입니다.", size=13, color=GRAY)
    add_notes(
        s,
        "진단을 통해 고객 조직에 맞는 대상 업무 1개를 고르는 것을 안내한다. 합성 예시임을 분명히 한다.",
        "이 중 실제로 가장 시간이 오래 걸리는 업무는 무엇인가요?",
        "실제 고객 성과 사례처럼 표현하지 않는다."
    )
    add_page_number(prs, s, 4)

    # ---- Slide 5 ----
    s = add_slide(prs, "5. 상품 A — AI 업무전환 진단 워크숍")
    tf = add_body_box(s, Inches(0.7), Inches(1.5), Inches(11.9), Inches(5.2))
    para(tf, "1~2일", size=20, bold=True, color=NAVY, first=True)
    para(tf, "업무 현황 인터뷰, AI 적용 후보 선정, 위험업무 제외, 직무별 실습, 경영진 결과 보고", size=16)
    para(tf, "", size=8)
    para(tf, "초기 제안 300만~500만원", size=22, bold=True, color=ACCENT)
    para(tf, "가격은 시장 검증 전 자사 가격 가설입니다. 범위와 인원·기간에 따라 최종 견적이 달라집니다.", size=14, color=GRAY)
    add_notes(
        s,
        "진단 워크숍은 변화의 출발점이며, 고객 조직이 무엇을 바꿀지 함께 찾는 자리라고 설명한다.",
        "워크숍에 참여할 수 있는 팀과 일정이 있나요?",
        "가격을 확정 가격처럼 말하지 않는다 — 가설임을 명시한다."
    )
    add_page_number(prs, s, 5)

    # ---- Slide 6 ----
    s = add_slide(prs, "6. 상품 B — 6주 디자인 파트너 파일럿")
    tf = add_body_box(s, Inches(0.7), Inches(1.5), Inches(11.9), Inches(5.2))
    para(tf, "6주 · 1개 팀 · 1개 핵심 업무", size=20, bold=True, color=NAVY, first=True)
    para(tf, "기준선 측정 → 직무별 교육 → 실제 실습 → 워크플로 재설계 → 제한 파일럿 → 성과·위험 보고 → 운영 플레이북", size=16)
    para(tf, "", size=8)
    para(tf, "1,000만~1,500만원", size=22, bold=True, color=ACCENT)
    para(tf, "가격은 시장 검증 전 자사 가격 가설입니다. 범위와 인원·기간에 따라 최종 견적이 달라집니다.", size=14, color=GRAY)
    add_notes(
        s,
        "파일럿은 1팀·1핵심 업무로 제한되어 위험을 낮추고, 측정 가능한 결과를 만든다고 설명한다.",
        "파일럿 후보 업무가 있나요? 담당자를 지정할 수 있나요?",
        "성과를 보장하지 않는다. 사람 검토 gate가 필수임을 명시한다."
    )
    add_page_number(prs, s, 6)

    # ---- Slide 7 ----
    s = add_slide(prs, "7. 6주 수행 구조")
    rows = [
        ("Week 0", "계약·범위"), ("Week 1", "진단·기준선"), ("Week 2", "교육·실습"),
        ("Week 3", "재설계"), ("Week 4", "제한 파일럿"), ("Week 5", "측정·보완"),
        ("Week 6", "결과·운영 플레이북"),
    ]
    y = Inches(1.7)
    row_h = Inches(0.62)
    for label, desc in rows:
        box = s.shapes.add_shape(5, Inches(0.7), y, Inches(2.2), row_h)
        box.fill.solid()
        box.fill.fore_color.rgb = BLUE
        box.line.fill.background()
        box.shadow.inherit = False
        btf = box.text_frame
        btf.vertical_anchor = MSO_ANCHOR.MIDDLE
        bp = btf.paragraphs[0]
        bp.alignment = PP_ALIGN.CENTER
        br = bp.add_run()
        br.text = label
        br.font.size = Pt(14)
        br.font.bold = True
        br.font.color.rgb = WHITE
        br.font.name = "Malgun Gothic"
        box2 = s.shapes.add_shape(1, Inches(3.0), y, Inches(9.6), row_h)
        box2.fill.solid()
        box2.fill.fore_color.rgb = WHITE
        box2.line.color.rgb = BLUE
        box2.line.width = Pt(0.75)
        box2.shadow.inherit = False
        btf2 = box2.text_frame
        btf2.vertical_anchor = MSO_ANCHOR.MIDDLE
        btf2.margin_left = Inches(0.15)
        bp2 = btf2.paragraphs[0]
        br2 = bp2.add_run()
        br2.text = desc
        br2.font.size = Pt(15)
        br2.font.color.rgb = NAVY
        br2.font.name = "Malgun Gothic"
        y += row_h + Inches(0.1)
    add_notes(
        s,
        "6주 일정이 명확하다는 점을 보여준다. 각 주차의 산출물과 검토 gate가 계획서(04)에 있다고 안내한다.",
        "6주 동안 주당 2~4시간을 참여할 수 있나요?",
        "일정이 모든 조직에 동일하게 적용된다고 단정하지 않는다."
    )
    add_page_number(prs, s, 7)

    # ---- Slide 8 ----
    s = add_slide(prs, "8. KPI와 위험관리")
    tf = add_body_box(s, Inches(0.7), Inches(1.45), Inches(11.9), Inches(5.2))
    para(tf, "KPI 예시", size=20, bold=True, color=NAVY, first=True)
    kpis = ["초안 작성시간", "검토 회차", "수정 반려율", "승인 소요시간", "참여자 task completion", "위험 사례 수"]
    for i, k in enumerate(kpis):
        col = Inches(0.7) if i < 3 else Inches(6.5)
        yy = Inches(2.0) + Inches(0.7) * (i % 3)
        box = s.shapes.add_shape(5, col, yy, Inches(5.3), Inches(0.55))
        box.fill.solid()
        box.fill.fore_color.rgb = WHITE
        box.line.color.rgb = BLUE
        box.line.width = Pt(0.75)
        box.shadow.inherit = False
        btf = box.text_frame
        btf.vertical_anchor = MSO_ANCHOR.MIDDLE
        bp = btf.paragraphs[0]
        br = bp.add_run()
        br.text = k
        br.font.size = Pt(14)
        br.font.color.rgb = NAVY
        br.font.name = "Malgun Gothic"
    para(tf, "위험관리: 위험업무 제외, 사람 검토 gate, 승인 도구 외 사용 금지, 사고 시 중단 절차", size=16, color=GRAY)
    para(tf, "KPI는 목표 가설이며 성과 보장을 의미하지 않습니다.", size=14, bold=True, color=ACCENT)
    add_notes(
        s,
        "KPI는 속도·품질·채택·거버넌스 준수를 분리해 측정한다고 설명한다. 성과 보장이 아님을 강조한다.",
        "현재 어떤 기준으로 성과를 판단하고 있나요?",
        "KPI 목표 가설을 성과 보장으로 오인하지 않게 한다."
    )
    add_page_number(prs, s, 8)

    # ---- Slide 9 ----
    s = add_slide(prs, "9. 가격 가설")
    tf = add_body_box(s, Inches(0.7), Inches(1.5), Inches(11.9), Inches(5.2))
    price_lines = [
        "A 진단 워크숍           300만–800만원  (초기 제안 300만–500만원)",
        "B 디자인 파트너 파일럿    1,000만–1,500만원",
        "B 표준 6주 파일럿         1,500만–2,500만원",
        "C 조직 운영 자문          월 300만–600만원",
    ]
    for i, line in enumerate(price_lines):
        box = s.shapes.add_shape(1, Inches(0.7), Inches(1.9) + Inches(0.75) * i, Inches(11.9), Inches(0.6))
        box.fill.solid()
        box.fill.fore_color.rgb = WHITE
        box.line.color.rgb = BLUE
        box.line.width = Pt(0.75)
        box.shadow.inherit = False
        btf = box.text_frame
        btf.vertical_anchor = MSO_ANCHOR.MIDDLE
        btf.margin_left = Inches(0.2)
        bp = btf.paragraphs[0]
        br = bp.add_run()
        br.text = line
        br.font.size = Pt(17)
        br.font.color.rgb = NAVY
        br.font.name = "Malgun Gothic"
    para(tf, "", size=6)
    para(tf, "시장 검증 전 자사 가격 가설", size=15, bold=True, color=ACCENT)
    para(tf, "범위·인원·기간에 따라 최종 견적", size=15, bold=True, color=ACCENT)
    para(tf, "VAT 조건은 최종 견적서에서 확정", size=15, bold=True, color=ACCENT)
    add_notes(
        s,
        "가격은 가설이며 범위·인원·기간에 따라 달라진다고 명확히 한다. VAT는 최종 견적서에서 확정된다고 말한다.",
        "어느 상품 범위가 관심 있나요?",
        "경쟁사 평균 가격 주장, 정부지원금 수령 가능 주장을 하지 않는다."
    )
    add_page_number(prs, s, 9)

    # ---- Slide 10 ----
    s = add_slide(prs, "10. 다음 단계")
    steps10 = [
        ("1", "30분 사전 상담"),
        ("2", "대상 업무 1개 선정"),
        ("3", "진단 워크숍 범위 확정"),
        ("4", "견적·일정 승인"),
    ]
    for i, (num, label) in enumerate(steps10):
        box = s.shapes.add_shape(5, Inches(0.7) + Inches(3.1) * i, Inches(2.4), Inches(2.7), Inches(2.2))
        box.fill.solid()
        box.fill.fore_color.rgb = BLUE
        box.line.color.rgb = NAVY
        box.line.width = Pt(1)
        box.shadow.inherit = False
        btf = box.text_frame
        btf.word_wrap = True
        btf.vertical_anchor = MSO_ANCHOR.MIDDLE
        bp = btf.paragraphs[0]
        bp.alignment = PP_ALIGN.CENTER
        br = bp.add_run()
        br.text = num
        br.font.size = Pt(28)
        br.font.bold = True
        br.font.color.rgb = WHITE
        p2 = btf.add_paragraph()
        p2.alignment = PP_ALIGN.CENTER
        r2 = p2.add_run()
        r2.text = label
        r2.font.size = Pt(15)
        r2.font.color.rgb = WHITE
        r2.font.name = "Malgun Gothic"
    tf = add_body_box(s, Inches(0.7), Inches(5.0), Inches(11.9), Inches(1.5))
    para(tf, "첫 상담에서 계약을 압박하지 않으며, 정부지원금 확정을 말하지 않습니다.", size=14, color=GRAY, first=True)
    para(tf, "조직별 사용정책·검토체계, 개인정보·저작권·조달, 전문 법률·계약 검토가 필요합니다.", size=14, color=GRAY)
    add_notes(
        s,
        "다음 단계를 명확히 제시하고, 첫 상담에서는 계약 압박이나 정부지원금 확정 발언을 하지 않는다.",
        "편하신 시간에 30분 상담을 잡을 수 있을까요?",
        "정부지원금 수령 가능, 1억원 이하 자동 수의계약을 말하지 않는다."
    )
    add_page_number(prs, s, 10)

    prs.save(OUT)
    print(f"saved {OUT} with {len(prs.slides._sldIdLst)} slides")


if __name__ == "__main__":
    build()
