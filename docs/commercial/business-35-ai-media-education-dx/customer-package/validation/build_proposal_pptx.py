#!/usr/bin/env python3
"""Generate the Business 35 customer-facing master proposal PPTX (10 slides, 16:9).

Structure:
1 표지·핵심 제안 / 2 현재 문제 / 3 일반 AI 교육의 한계 / 4 Business 35 방식 /
5 대상 업무 예시 / 6 상품 A / 7 상품 B·6주 구조 / 8 KPI·위험관리 /
9 가격 가설 / 10 다음 단계

Layout rule: title band 0..1.15; headline 1.3..1.92; body starts at 2.1;
footer at 7.05. No overlapping text layers. All text/shapes editable; each slide
carries a page number and speaker notes. No external images/fonts/stock assets.
"""

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

OUT = "docs/commercial/business-35-ai-media-education-dx/customer-package/Business35_Master_Proposal_10p.pptx"

NAVY = RGBColor(0x1F, 0x3A, 0x5F)
BLUE = RGBColor(0x2E, 0x5E, 0x8C)
GRAY = RGBColor(0x55, 0x5A, 0x60)
LIGHT = RGBColor(0xF2, 0xF4, 0xF7)
ACCENT = RGBColor(0xC2, 0x7B, 0x2D)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
SOFT = RGBColor(0xD5, 0xDE, 0xE8)

SW, SH = Inches(13.333), Inches(7.5)

FOOTER_COVER = "DRAFT · 제공자 정보 및 법률 검토 필요"
FOOTER_INNER = "DRAFT"
FOOTER_LAST = "제공자 정보 최종 확정 필요"
PROVIDER = "제안 제공자 정보는 발송 전 최종 확정"

TOTAL_SLIDES = 10

HEADLINE_Y = Inches(1.3)
HEADLINE_H = Inches(0.62)
BODY_Y = Inches(2.1)


def new_deck():
    prs = Presentation()
    prs.slide_width = SW
    prs.slide_height = SH
    return prs


def add_slide(prs, title, footer_mode="inner", slide_no=None, headline=None):
    layout = prs.slide_layouts[6]
    slide = prs.slides.add_slide(layout)
    bg = slide.shapes.add_shape(1, 0, 0, SW, SH)
    bg.fill.solid()
    bg.fill.fore_color.rgb = LIGHT
    bg.line.fill.background()
    bg.shadow.inherit = False
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
    if slide_no is not None:
        # Badge sits in the headline zone's right side, NOT overlapping the title band
        badge = slide.shapes.add_shape(5, Inches(12.05), Inches(1.38), Inches(0.95), Inches(0.6))
        badge.fill.solid()
        badge.fill.fore_color.rgb = ACCENT
        badge.line.fill.background()
        badge.shadow.inherit = False
        btf = badge.text_frame
        btf.vertical_anchor = MSO_ANCHOR.MIDDLE
        bp = btf.paragraphs[0]
        bp.alignment = PP_ALIGN.CENTER
        br = bp.add_run()
        br.text = f"{slide_no:02d}"
        br.font.size = Pt(18)
        br.font.bold = True
        br.font.color.rgb = WHITE
        br.font.name = "Malgun Gothic"
    # Single headline layer (one message, no duplicate body text near it)
    if headline:
        hb = slide.shapes.add_shape(1, Inches(0.7), HEADLINE_Y, Inches(11.15), HEADLINE_H)
        hb.fill.solid()
        hb.fill.fore_color.rgb = RGBColor(0xE3, 0xE9, 0xF0)
        hb.line.color.rgb = BLUE
        hb.line.width = Pt(0.75)
        hb.shadow.inherit = False
        htf = hb.text_frame
        htf.word_wrap = True
        htf.vertical_anchor = MSO_ANCHOR.MIDDLE
        htf.margin_left = Inches(0.2)
        hp = htf.paragraphs[0]
        hr = hp.add_run()
        hr.text = headline
        hr.font.size = Pt(15)
        hr.font.bold = True
        hr.font.color.rgb = NAVY
        hr.font.name = "Malgun Gothic"
    # Footer
    footer = slide.shapes.add_textbox(Inches(0.55), Inches(7.05), Inches(11.7), Inches(0.35))
    ftf = footer.text_frame
    ftf.word_wrap = True
    fp = ftf.paragraphs[0]
    fr = fp.add_run()
    if footer_mode == "cover":
        fr.text = FOOTER_COVER
    elif footer_mode == "last":
        fr.text = FOOTER_LAST + "  ·  " + PROVIDER
    else:
        fr.text = FOOTER_INNER
    fr.font.size = Pt(11)
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


def para(tf, text, size=16, bold=False, color=GRAY, first=False, space_before=None, space_after=8, align=None):
    p = tf.paragraphs[0] if first and not tf.paragraphs[0].runs else tf.add_paragraph()
    if space_before is not None:
        p.space_before = Pt(space_before)
    p.space_after = Pt(space_after)
    if align:
        p.alignment = align
    r = p.add_run()
    r.text = text
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.color.rgb = color
    r.font.name = "Malgun Gothic"
    return p


def add_step_box(slide, x, y, w, h, num, label):
    box = slide.shapes.add_shape(5, x, y, w, h)
    box.fill.solid()
    box.fill.fore_color.rgb = BLUE
    box.line.color.rgb = NAVY
    box.line.width = Pt(1)
    box.shadow.inherit = False
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0.06)
    tf.margin_right = Inches(0.06)
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


def add_card(slide, x, y, w, h, title, body_lines, title_color=NAVY, body_size=14):
    card = slide.shapes.add_shape(1, x, y, w, h)
    card.fill.solid()
    card.fill.fore_color.rgb = WHITE
    card.line.color.rgb = BLUE
    card.line.width = Pt(1)
    card.shadow.inherit = False
    ctf = card.text_frame
    ctf.word_wrap = True
    ctf.vertical_anchor = MSO_ANCHOR.MIDDLE
    ctf.margin_left = Inches(0.2)
    ctf.margin_right = Inches(0.2)
    ctf.margin_top = Inches(0.15)
    cp = ctf.paragraphs[0]
    cp.alignment = PP_ALIGN.CENTER
    cr = cp.add_run()
    cr.text = title
    cr.font.size = Pt(18)
    cr.font.bold = True
    cr.font.color.rgb = title_color
    cr.font.name = "Malgun Gothic"
    for line in body_lines:
        cp2 = ctf.add_paragraph()
        cp2.space_before = Pt(6)
        cp2.alignment = PP_ALIGN.CENTER
        cr2 = cp2.add_run()
        cr2.text = line
        cr2.font.size = Pt(body_size)
        cr2.font.color.rgb = GRAY
        cr2.font.name = "Malgun Gothic"
    return card


def build():
    prs = new_deck()

    # ---- Slide 1 · 표지 ----
    s = add_slide(prs, "Business 35 · AI Media Education & DX",
                  footer_mode="cover", slide_no=1,
                  headline="AI 교육에서 실제 업무전환까지")
    tf = add_body_box(s, Inches(0.7), BODY_Y, Inches(11.9), Inches(4.2))
    para(tf, "지역 문화·교육·미디어 조직을 위한 진단·실습·워크플로 재설계·파일럿 프로그램",
         size=18, bold=True, color=NAVY, first=True)
    para(tf, "대상: 지역 문화기관 · 교육기관 · 협회·단체 · 미디어·콘텐츠 기관",
         size=15, color=GRAY, space_before=12)
    para(tf, "대표 진입 상품: 상품 A · 진단 워크숍 (초기형 300만~500만원)",
         size=15, color=GRAY, space_before=12)
    para(tf, "상세 내용은 이어지는 페이지에서 확인하실 수 있습니다.",
         size=13, color=GRAY, space_before=16)
    add_notes(
        s,
        "표지에서 제품명·핵심 제안 한 문장·대상 고객군·대표 진입 상품·DRAFT 상태만 보여준다.",
        "조직에서 가장 시간이 오래 걸리는 콘텐츠 업무는 무엇인가요?",
        "가격을 확정 가격처럼 말하지 않는다. 성과·정부지원금을 보장하지 않는다."
    )
    add_page_number(prs, s, 1)

    # ---- Slide 2 · 현재 문제 ----
    s = add_slide(prs, "2. 현재 문제", slide_no=2,
                  headline="콘텐츠 제작은 늘었지만 조직의 기준과 검토체계는 따라오지 못합니다.")
    cards = [
        ("A", "수작업 제작", ["홍보물·안내문·뉴스레터 초안이", "개인 경험과 수동 검토에 의존합니다."]),
        ("B", "개인별 AI 사용", ["조직원마다 개인적으로 AI를 쓰지만", "조직 차원의 기준은 없습니다."]),
        ("C", "검토 기준 부재", ["검토·승인 기준, 사용정책, 금지 업무", "규칙이 없어 위험이 커집니다."]),
    ]
    for i, (badge, title, lines) in enumerate(cards):
        cx = Inches(0.7) + Inches(4.1) * i
        card = s.shapes.add_shape(5, cx, BODY_Y, Inches(3.85), Inches(3.2))
        card.fill.solid()
        card.fill.fore_color.rgb = WHITE
        card.line.color.rgb = BLUE
        card.line.width = Pt(1)
        card.shadow.inherit = False
        ctf = card.text_frame
        ctf.word_wrap = True
        ctf.margin_left = Inches(0.2)
        ctf.margin_right = Inches(0.2)
        ctf.margin_top = Inches(0.25)
        cp = ctf.paragraphs[0]
        cp.alignment = PP_ALIGN.CENTER
        cr = cp.add_run()
        cr.text = badge
        cr.font.size = Pt(26)
        cr.font.bold = True
        cr.font.color.rgb = ACCENT
        cr.font.name = "Malgun Gothic"
        cp2 = ctf.add_paragraph()
        cp2.alignment = PP_ALIGN.CENTER
        cr2 = cp2.add_run()
        cr2.text = title
        cr2.font.size = Pt(19)
        cr2.font.bold = True
        cr2.font.color.rgb = NAVY
        cr2.font.name = "Malgun Gothic"
        for line in lines:
            cp3 = ctf.add_paragraph()
            cp3.space_before = Pt(8)
            cp3.alignment = PP_ALIGN.CENTER
            cr3 = cp3.add_run()
            cr3.text = line
            cr3.font.size = Pt(14)
            cr3.font.color.rgb = GRAY
            cr3.font.name = "Malgun Gothic"
    add_notes(
        s,
        "고객 조직의 콘텐츠 제작이 수작업에 의존하고, AI는 개인 단위로만 쓰이며, 검토·승인 기준이 없다는 점을 공감하며 설명한다.",
        "현재 콘텐츠 1건을 만드는 데 며칠이 걸리나요? 검토는 몇 단계인가요?",
        "통계로 고객을 압박하지 않고, 고객의 실제 상황을 묻는 데 집중한다."
    )
    add_page_number(prs, s, 2)

    # ---- Slide 3 · 일반 AI 교육의 한계 ----
    s = add_slide(prs, "3. 일반 AI 교육의 한계", slide_no=3,
                  headline="교육 수료와 실제 업무 전환은 다릅니다.")
    card1 = add_card(s, Inches(0.7), BODY_Y, Inches(5.9), Inches(2.3),
                     "강의를 들어도 업무가 바뀌지 않음",
                     ["지식 전달은 되지만 조직의 실제 업무 흐름과", "연결되지 않으면 변화가 일어나지 않습니다."])
    card2 = add_card(s, Inches(6.9), BODY_Y, Inches(5.9), Inches(2.3),
                     "정책·검토·승인·측정과 연결되지 않음",
                     ["교육 수료는 역량 보유를 보장하지 않습니다.", "검토 gate·승인 절차·성과 측정이 없으면", "실무 반영이 어렵습니다."])
    tf = add_body_box(s, Inches(0.7), Inches(4.8), Inches(11.9), Inches(1.6))
    para(tf, "일반 AI 교육은 지식을 주지만, 조직의 사용정책·검토체계·성과 측정과 연결되지 않아 실제 업무 변화로 이어지지 않습니다.",
         size=15, color=GRAY, first=True)
    add_notes(
        s,
        "일반 AI 교육이 왜 실제 업무 변화로 이어지지 않는지 구조적으로 설명한다. 경쟁 강의를 비방하지 않는다.",
        "지난 교육을 받고 실제 업무에 반영된 것은 무엇인가요?",
        "교육업체를 비판하는 어조를 쓰지 않는다."
    )
    add_page_number(prs, s, 3)

    # ---- Slide 4 · Business 35 방식 ----
    s = add_slide(prs, "4. Business 35 방식 — AI 업무전환 프로그램", slide_no=4,
                  headline="진단에서 운영 플레이북까지 이어지는 7단계 업무전환 구조입니다.")
    tf = add_body_box(s, Inches(0.7), BODY_Y, Inches(11.9), Inches(1.2))
    para(tf, "교육에서 끝나지 않고, 실제 업무 진단·실습·재설계·파일럿·측정·플레이북까지 연결합니다.",
         size=17, bold=True, color=NAVY, first=True)
    steps = [
        ("진단", "1"), ("직무 교육", "2"), ("실제 실습", "3"), ("워크플로 재설계", "4"),
        ("제한 파일럿", "5"), ("성과 측정", "6"), ("운영 플레이북", "7"),
    ]
    box_w = Inches(1.55)
    gap = Inches(0.16)
    start_x = Inches(0.7)
    y = Inches(4.2)
    h = Inches(1.6)
    for i, (label, num) in enumerate(steps):
        x = start_x + (box_w + gap) * i
        add_step_box(s, x, y, box_w, h, num, label)
        # connecting arrow between steps
        if i < len(steps) - 1:
            arrow_x = x + box_w + Inches(0.01)
            arrow = s.shapes.add_shape(13, arrow_x, y + Inches(0.55), Inches(0.14), Inches(0.5))
            arrow.fill.solid()
            arrow.fill.fore_color.rgb = ACCENT
            arrow.line.fill.background()
            arrow.shadow.inherit = False
            arrow.rotation = 0
    add_notes(
        s,
        "7단계 업무전환 구조를 설명하고, 결과물이 사람이 승인한 운영 플레이북임을 강조한다.",
        "현재 가장 바꾸고 싶은 업무가 무엇인가요?",
        "전체 업무 전환을 보장하지 않는다."
    )
    add_page_number(prs, s, 4)

    # ---- Slide 5 · 대상 업무 예시 ----
    s = add_slide(prs, "5. 대상 업무 — 합성 예시", slide_no=5,
                  headline="지역 문화·교육·미디어 조직에서 시작하기 쉬운 업무입니다.")
    items = [
        "행사 홍보물 초안",
        "교육 프로그램 안내문",
        "뉴스레터 초안",
        "SNS 콘텐츠 변환",
        "자료 요약",
        "검토 체크리스트",
    ]
    col1, col2 = Inches(0.7), Inches(6.5)
    row_y = BODY_Y
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
    tf = add_body_box(s, Inches(0.7), Inches(4.9), Inches(11.9), Inches(1.2))
    para(tf, "이것은 실제 고객 성과 사례가 아니라 대상 업무의 합성 예시입니다. 진단을 통해 고객 조직에 맞는 업무 1개를 고릅니다.",
         size=13, color=GRAY, first=True)
    add_notes(
        s,
        "진단을 통해 고객 조직에 맞는 대상 업무 1개를 고르는 것을 안내한다. 합성 예시임을 분명히 한다.",
        "이 중 실제로 가장 시간이 오래 걸리는 업무는 무엇인가요?",
        "실제 고객 성과 사례처럼 표현하지 않는다."
    )
    add_page_number(prs, s, 5)

    # ---- Slide 6 · 상품 A ----
    s = add_slide(prs, "6. 상품 A — AI 업무전환 진단 워크숍", slide_no=6,
                  headline="짧고 낮은 진입장벽으로 고객의 첫 결정을 만듭니다.")
    dur = s.shapes.add_shape(5, Inches(0.7), BODY_Y, Inches(2.9), Inches(1.3))
    dur.fill.solid()
    dur.fill.fore_color.rgb = BLUE
    dur.line.fill.background()
    dur.shadow.inherit = False
    dtf = dur.text_frame
    dtf.vertical_anchor = MSO_ANCHOR.MIDDLE
    dp = dtf.paragraphs[0]
    dp.alignment = PP_ALIGN.CENTER
    dr = dp.add_run()
    dr.text = "1~2일 워크숍"
    dr.font.size = Pt(18)
    dr.font.bold = True
    dr.font.color.rgb = WHITE
    dr.font.name = "Malgun Gothic"
    prc = s.shapes.add_shape(5, Inches(0.7), Inches(3.6), Inches(2.9), Inches(1.6))
    prc.fill.solid()
    prc.fill.fore_color.rgb = ACCENT
    prc.line.fill.background()
    prc.shadow.inherit = False
    ptf2 = prc.text_frame
    ptf2.vertical_anchor = MSO_ANCHOR.MIDDLE
    ptf2.word_wrap = True
    pp = ptf2.paragraphs[0]
    pp.alignment = PP_ALIGN.CENTER
    prr = pp.add_run()
    prr.text = "초기형 300만~500만원"
    prr.font.size = Pt(15)
    prr.font.bold = True
    prr.font.color.rgb = WHITE
    prr.font.name = "Malgun Gothic"
    pp2 = ptf2.add_paragraph()
    pp2.alignment = PP_ALIGN.CENTER
    prr2 = pp2.add_run()
    prr2.text = "확장형 500만~800만원"
    prr2.font.size = Pt(13)
    prr2.font.color.rgb = RGBColor(0xFF, 0xE8, 0xC8)
    prr2.font.name = "Malgun Gothic"
    out = s.shapes.add_shape(1, Inches(3.95), BODY_Y, Inches(8.65), Inches(2.8))
    out.fill.solid()
    out.fill.fore_color.rgb = WHITE
    out.line.color.rgb = BLUE
    out.line.width = Pt(1)
    out.shadow.inherit = False
    otf = out.text_frame
    otf.word_wrap = True
    otf.margin_left = Inches(0.25)
    otf.margin_top = Inches(0.2)
    op = otf.paragraphs[0]
    orr = op.add_run()
    orr.text = "주요 산출물"
    orr.font.size = Pt(17)
    orr.font.bold = True
    orr.font.color.rgb = NAVY
    orr.font.name = "Malgun Gothic"
    outputs = [
        "현재 업무 흐름 진단",
        "AI 적용 후보 업무 1~3개 선정",
        "위험·금지 업무 분리",
        "직무별 실습 결과",
        "경영진 결과 보고",
    ]
    for o in outputs:
        op2 = otf.add_paragraph()
        orr2 = op2.add_run()
        orr2.text = "•  " + o
        orr2.font.size = Pt(15)
        orr2.font.color.rgb = GRAY
        orr2.font.name = "Malgun Gothic"
    para_tf = add_body_box(s, Inches(0.7), Inches(5.2), Inches(11.9), Inches(1.4))
    para(para_tf, "가격은 시장 검증 전 자사 가격 가설입니다. 범위와 인원·기간에 따라 최종 견적이 달라집니다.",
         size=14, color=GRAY, first=True)
    add_notes(
        s,
        "진단 워크숍은 변화의 출발점이며, 고객 조직이 무엇을 바꿀지 함께 찾는 자리라고 설명한다.",
        "워크숍에 참여할 수 있는 팀과 일정이 있나요?",
        "가격을 확정 가격처럼 말하지 않는다 — 가설임을 명시한다."
    )
    add_page_number(prs, s, 6)

    # ---- Slide 7 · 상품 B1 + 6주 구조 ----
    s = add_slide(prs, "7. 상품 B1 — 6주 디자인 파트너 파일럿", slide_no=7,
                  headline="작게 실행하고, 측정하고, 운영 기준을 남깁니다.")
    sc = s.shapes.add_shape(5, Inches(0.7), BODY_Y, Inches(2.9), Inches(1.3))
    sc.fill.solid()
    sc.fill.fore_color.rgb = BLUE
    sc.line.fill.background()
    sc.shadow.inherit = False
    stf = sc.text_frame
    stf.vertical_anchor = MSO_ANCHOR.MIDDLE
    sp = stf.paragraphs[0]
    sp.alignment = PP_ALIGN.CENTER
    srr = sp.add_run()
    srr.text = "6주 · 1팀 · 1핵심 업무"
    srr.font.size = Pt(17)
    srr.font.bold = True
    srr.font.color.rgb = WHITE
    srr.font.name = "Malgun Gothic"
    prc6 = s.shapes.add_shape(5, Inches(0.7), Inches(3.6), Inches(2.9), Inches(1.5))
    prc6.fill.solid()
    prc6.fill.fore_color.rgb = ACCENT
    prc6.line.fill.background()
    prc6.shadow.inherit = False
    ptf6 = prc6.text_frame
    ptf6.vertical_anchor = MSO_ANCHOR.MIDDLE
    ptf6.word_wrap = True
    pp6 = ptf6.paragraphs[0]
    pp6.alignment = PP_ALIGN.CENTER
    prr6 = pp6.add_run()
    prr6.text = "1,000만~1,500만원"
    prr6.font.size = Pt(17)
    prr6.font.bold = True
    prr6.font.color.rgb = WHITE
    prr6.font.name = "Malgun Gothic"
    pp6b = ptf6.add_paragraph()
    pp6b.alignment = PP_ALIGN.CENTER
    prr6b = pp6b.add_run()
    prr6b.text = "상품 B1 · 디자인 파트너"
    prr6b.font.size = Pt(11)
    prr6b.font.color.rgb = RGBColor(0xFF, 0xE8, 0xC8)
    prr6b.font.name = "Malgun Gothic"
    out6 = s.shapes.add_shape(1, Inches(3.95), BODY_Y, Inches(8.65), Inches(2.8))
    out6.fill.solid()
    out6.fill.fore_color.rgb = WHITE
    out6.line.color.rgb = BLUE
    out6.line.width = Pt(1)
    out6.shadow.inherit = False
    otf6 = out6.text_frame
    otf6.word_wrap = True
    otf6.margin_left = Inches(0.25)
    otf6.margin_top = Inches(0.2)
    op6 = otf6.paragraphs[0]
    orr6b = op6.add_run()
    orr6b.text = "파일럿 진행 흐름"
    orr6b.font.size = Pt(17)
    orr6b.font.bold = True
    orr6b.font.color.rgb = NAVY
    orr6b.font.name = "Malgun Gothic"
    flow6 = [
        "기준선 측정",
        "직무별 교육 · 실제 실습",
        "워크플로 재설계 · 사람 검토 gate",
        "제한 파일럿 실행",
        "성과·위험 보고서 · 운영 플레이북",
    ]
    for o in flow6:
        op6b = otf6.add_paragraph()
        orr6c = op6b.add_run()
        orr6c.text = "•  " + o
        orr6c.font.size = Pt(15)
        orr6c.font.color.rgb = GRAY
        orr6c.font.name = "Malgun Gothic"
    # 6-week timeline row
    rows = [
        ("W0", "계약·범위", "범위 확정"),
        ("W1", "진단·기준선", "기준선 측정"),
        ("W2", "교육·실습", "역량 확인"),
        ("W3", "재설계", "검토 gate"),
        ("W4", "제한 파일럿", "실행 결과"),
        ("W5", "측정·보완", "중간 보고"),
        ("W6", "결과·플레이북", "플레이북 승인"),
    ]
    tl_y = Inches(5.1)
    tl_h = Inches(0.95)
    tl_w = Inches(1.62)
    tl_gap = Inches(0.12)
    for i, (label, desc, result) in enumerate(rows):
        tx = Inches(0.7) + (tl_w + tl_gap) * i
        box = s.shapes.add_shape(5, tx, tl_y, tl_w, tl_h)
        box.fill.solid()
        box.fill.fore_color.rgb = BLUE
        box.line.fill.background()
        box.shadow.inherit = False
        btf = box.text_frame
        btf.word_wrap = True
        btf.vertical_anchor = MSO_ANCHOR.MIDDLE
        btf.margin_left = Inches(0.04)
        btf.margin_right = Inches(0.04)
        bp = btf.paragraphs[0]
        bp.alignment = PP_ALIGN.CENTER
        br = bp.add_run()
        br.text = label + " " + desc
        br.font.size = Pt(11)
        br.font.bold = True
        br.font.color.rgb = WHITE
        br.font.name = "Malgun Gothic"
        bp2 = btf.add_paragraph()
        bp2.alignment = PP_ALIGN.CENTER
        br2 = bp2.add_run()
        br2.text = "▸ " + result
        br2.font.size = Pt(10)
        br2.font.color.rgb = RGBColor(0xE8, 0xEE, 0xF5)
        br2.font.name = "Malgun Gothic"
        # connecting timeline line between weeks
        if i < len(rows) - 1:
            line_x = tx + tl_w + Inches(0.01)
            line = s.shapes.add_shape(1, line_x, tl_y + Inches(0.42), Inches(0.1), Inches(0.1))
            line.fill.solid()
            line.fill.fore_color.rgb = ACCENT
            line.line.fill.background()
            line.shadow.inherit = False
    tf6 = add_body_box(s, Inches(0.7), Inches(6.25), Inches(11.9), Inches(0.7))
    para(tf6, "가격은 시장 검증 전 가설입니다. 6주 상세 일정은 별도 수행계획서(04)에 있습니다.",
         size=13, color=GRAY, first=True)
    add_notes(
        s,
        "파일럿은 1팀·1핵심 업무로 제한되어 위험을 낮추고, 측정 가능한 결과를 만든다고 설명한다.",
        "파일럿 후보 업무가 있나요? 담당자를 지정할 수 있나요?",
        "성과를 보장하지 않는다. 사람 검토 gate가 필수임을 명시한다."
    )
    add_page_number(prs, s, 7)

    # ---- Slide 8 · KPI·위험관리 ----
    s = add_slide(prs, "8. KPI·위험관리", slide_no=8,
                  headline="속도만 보지 않고 품질·채택·거버넌스를 함께 봅니다.")
    tf = add_body_box(s, Inches(0.7), BODY_Y, Inches(11.9), Inches(0.8))
    para(tf, "KPI 예시", size=20, bold=True, color=NAVY, first=True)
    kpis = ["초안 작성시간", "검토 회차", "수정 반려율", "승인 소요시간", "참여자 task completion", "위험 사례 수"]
    for i, k in enumerate(kpis):
        col = Inches(0.7) if i < 3 else Inches(6.5)
        yy = Inches(2.9) + Inches(0.7) * (i % 3)
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
    tf2 = add_body_box(s, Inches(0.7), Inches(5.0), Inches(11.9), Inches(1.5))
    para(tf2, "위험관리: 위험업무 제외 · 사람 검토 gate · 승인 도구 외 사용 금지 · 사고 시 중단 절차",
         size=16, color=GRAY, first=True)
    para(tf2, "KPI는 목표 가설이며 성과 보장을 의미하지 않습니다.", size=14, bold=True, color=ACCENT, space_before=10)
    add_notes(
        s,
        "KPI는 속도·품질·채택·거버넌스 준수를 분리해 측정한다고 설명한다. 성과 보장이 아님을 강조한다.",
        "현재 어떤 기준으로 성과를 판단하고 있나요?",
        "KPI 목표 가설을 성과 보장으로 오인하지 않게 한다."
    )
    add_page_number(prs, s, 8)

    # ---- Slide 9 · 가격 가설 ----
    s = add_slide(prs, "9. 가격 가설", slide_no=9,
                  headline="시장 검증 전 자사 가격 가설이며 범위 확인 후 최종 견적을 제시합니다.")
    price_cards = [
        ("상품 A", "진단 워크숍", "초기형 300만~500만원", "확장형 500만~800만원"),
        ("상품 B1", "디자인 파트너", "1,000만~1,500만원", "6주 파일럿"),
        ("상품 B2", "표준 파일럿", "1,500만~2,500만원", "6주 파일럿"),
        ("상품 C", "운영 자문", "월 300만~600만원", "월 단위"),
    ]
    for i, (prod, name, price, note) in enumerate(price_cards):
        cx = Inches(0.7) + Inches(3.1) * i
        card = s.shapes.add_shape(5, cx, BODY_Y, Inches(2.85), Inches(2.6))
        card.fill.solid()
        card.fill.fore_color.rgb = WHITE
        card.line.color.rgb = BLUE
        card.line.width = Pt(1.25)
        card.shadow.inherit = False
        ctf = card.text_frame
        ctf.word_wrap = True
        ctf.vertical_anchor = MSO_ANCHOR.MIDDLE
        cp = ctf.paragraphs[0]
        cp.alignment = PP_ALIGN.CENTER
        cr = cp.add_run()
        cr.text = prod
        cr.font.size = Pt(13)
        cr.font.bold = True
        cr.font.color.rgb = BLUE
        cr.font.name = "Malgun Gothic"
        cp2 = ctf.add_paragraph()
        cp2.alignment = PP_ALIGN.CENTER
        cr2 = cp2.add_run()
        cr2.text = name
        cr2.font.size = Pt(17)
        cr2.font.bold = True
        cr2.font.color.rgb = NAVY
        cr2.font.name = "Malgun Gothic"
        cp3 = ctf.add_paragraph()
        cp3.alignment = PP_ALIGN.CENTER
        cr3 = cp3.add_run()
        cr3.text = price
        cr3.font.size = Pt(17)
        cr3.font.bold = True
        cr3.font.color.rgb = ACCENT
        cr3.font.name = "Malgun Gothic"
        cp4 = ctf.add_paragraph()
        cp4.alignment = PP_ALIGN.CENTER
        cr4 = cp4.add_run()
        cr4.text = note
        cr4.font.size = Pt(11)
        cr4.font.color.rgb = GRAY
        cr4.font.name = "Malgun Gothic"
    tf = add_body_box(s, Inches(0.7), Inches(4.9), Inches(11.9), Inches(1.6))
    para(tf, "시장 검증 전 자사 가격 가설", size=15, bold=True, color=ACCENT, first=True)
    para(tf, "범위·인원·기간에 따라 최종 견적 · VAT 조건은 최종 견적서에서 확정",
         size=15, bold=True, color=ACCENT, space_before=6)
    add_notes(
        s,
        "가격은 가설이며 범위·인원·기간에 따라 달라진다고 명확히 한다. VAT는 최종 견적서에서 확정된다고 말한다.",
        "어느 상품 범위가 관심 있나요?",
        "경쟁사 평균 가격 주장, 정부지원금 수령 가능 주장을 하지 않는다."
    )
    add_page_number(prs, s, 9)

    # ---- Slide 10 · 다음 단계 ----
    s = add_slide(prs, "10. 다음 단계", footer_mode="last", slide_no=10,
                  headline="30분 상담에서 대상 업무 하나를 정하고, 워크숍 범위를 확정합니다.")
    steps10 = [
        ("1", "30분 사전 상담", "현재 업무 흐름과 위험 확인"),
        ("2", "대상 업무 1개 선정", "홍보·교육·콘텐츠 중 하나"),
        ("3", "진단 워크숍 범위 확정", "참여자·일정·자료 범위"),
        ("4", "견적·일정 승인", "가격 가설 기반 최종 견적"),
    ]
    for i, (num, label, desc) in enumerate(steps10):
        box = s.shapes.add_shape(5, Inches(0.7) + Inches(3.1) * i, BODY_Y, Inches(2.7), Inches(2.4))
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
        r2.font.bold = True
        r2.font.color.rgb = WHITE
        r2.font.name = "Malgun Gothic"
        p3 = btf.add_paragraph()
        p3.alignment = PP_ALIGN.CENTER
        r3 = p3.add_run()
        r3.text = desc
        r3.font.size = Pt(11)
        r3.font.color.rgb = SOFT
        r3.font.name = "Malgun Gothic"
    tf = add_body_box(s, Inches(0.7), Inches(4.9), Inches(11.9), Inches(1.6))
    para(tf, "첫 상담에서 계약을 압박하지 않으며, 정부지원금 확정을 말하지 않습니다.",
         size=14, color=GRAY, first=True)
    para(tf, "조직별 사용정책·검토체계, 개인정보·저작권·조달, 전문 법률·계약 검토가 필요합니다.",
         size=14, color=GRAY, space_before=8)
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
