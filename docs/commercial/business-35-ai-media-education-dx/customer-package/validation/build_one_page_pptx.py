#!/usr/bin/env python3
"""Generate the Business 35 customer-facing one-page offer source PPTX.

Single slide, 16:9, editable text, speaker notes. Exported to PDF separately.
"""

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

OUT = "docs/commercial/business-35-ai-media-education-dx/customer-package/Business35_OnePage_Offer_Source.pptx"

NAVY = RGBColor(0x1F, 0x3A, 0x5F)
BLUE = RGBColor(0x2E, 0x5E, 0x8C)
GRAY = RGBColor(0x55, 0x5A, 0x60)
LIGHT = RGBColor(0xF2, 0xF4, 0xF7)
ACCENT = RGBColor(0xC2, 0x7B, 0x2D)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

SW, SH = Inches(13.333), Inches(7.5)

STATUS = "CUSTOMER-FACING MASTER · FINAL IDENTITY REQUIRED · LEGAL REVIEW REQUIRED · NOT YET SENT"
PROVIDER = "제안 제공자 정보는 발송 전 최종 확정"


def para(tf, text, size=14, bold=False, color=GRAY, first=False, align=None):
    p = tf.paragraphs[0] if first and not tf.paragraphs[0].runs else tf.add_paragraph()
    if align:
        p.alignment = align
    r = p.add_run()
    r.text = text
    r.font.size = Pt(size)
    r.font.bold = bold
    r.font.color.rgb = color
    r.font.name = "Malgun Gothic"
    return p


def build():
    prs = Presentation()
    prs.slide_width = SW
    prs.slide_height = SH
    layout = prs.slide_layouts[6]
    slide = prs.slides.add_slide(layout)

    bg = slide.shapes.add_shape(1, 0, 0, SW, SH)
    bg.fill.solid()
    bg.fill.fore_color.rgb = LIGHT
    bg.line.fill.background()
    bg.shadow.inherit = False

    # Cover band
    band = slide.shapes.add_shape(1, 0, 0, SW, Inches(1.35))
    band.fill.solid()
    band.fill.fore_color.rgb = NAVY
    band.line.fill.background()
    band.shadow.inherit = False
    tf = band.text_frame
    tf.margin_left = Inches(0.55)
    tf.margin_top = Inches(0.22)
    tf.word_wrap = True
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = "Business 35 · AI Media Education & DX"
    r.font.size = Pt(28)
    r.font.bold = True
    r.font.color.rgb = WHITE
    r.font.name = "Malgun Gothic"
    p2 = tf.add_paragraph()
    r2 = p2.add_run()
    r2.text = "AI 업무전환 프로그램 — 1페이지 소개"
    r2.font.size = Pt(16)
    r2.font.color.rgb = RGBColor(0xC9, 0xD6, 0xE3)
    r2.font.name = "Malgun Gothic"

    # Value proposition
    tb = slide.shapes.add_textbox(Inches(0.55), Inches(1.6), Inches(12.2), Inches(1.0))
    vtf = tb.text_frame
    vtf.word_wrap = True
    para(vtf, "교육에서 끝나지 않고, 실제 업무 진단·실습·워크플로 재설계·파일럿·측정·운영 플레이북까지 연결합니다.",
         size=16, bold=True, color=NAVY, first=True)

    # Problem
    tb = slide.shapes.add_textbox(Inches(0.55), Inches(2.55), Inches(12.2), Inches(1.1))
    ptf = tb.text_frame
    ptf.word_wrap = True
    para(ptf, "고객의 현재 문제", size=14, bold=True, color=BLUE, first=True)
    para(ptf, "홍보·교육·콘텐츠 제작 수작업 · AI 사용 개인 단위 · 검토·승인 기준 부재 · 개인정보·저작권·사람 검토 위험", size=13, color=GRAY)

    # 7 steps
    tb = slide.shapes.add_textbox(Inches(0.55), Inches(3.6), Inches(12.2), Inches(0.9))
    stf = tb.text_frame
    stf.word_wrap = True
    para(stf, "7단계 방식", size=14, bold=True, color=BLUE, first=True)
    para(stf, "진단 → 직무 교육 → 실제 실습 → 워크플로 재설계 → 제한 파일럿 → 성과 측정 → 운영 플레이북", size=13, color=NAVY)

    # Products
    tb = slide.shapes.add_textbox(Inches(0.55), Inches(4.45), Inches(12.2), Inches(1.15))
    prf = tb.text_frame
    prf.word_wrap = True
    para(prf, "상품 A / B / C", size=14, bold=True, color=BLUE, first=True)
    para(prf, "A 진단 워크숍 300만–800만원 (초기 300만–500만원)", size=13, color=GRAY)
    para(prf, "B 디자인 파트너 파일럿 1,000만–1,500만원 · B 표준 6주 파일럿 1,500만–2,500만원", size=13, color=GRAY)
    para(prf, "C 조직 운영 자문 월 300만–600만원", size=13, color=GRAY)

    # Next steps
    tb = slide.shapes.add_textbox(Inches(0.55), Inches(5.75), Inches(12.2), Inches(0.9))
    ntf = tb.text_frame
    ntf.word_wrap = True
    para(ntf, "다음 행동", size=14, bold=True, color=BLUE, first=True)
    para(ntf, "30분 사전 상담 → 대상 업무 1개 선정 → 진단 워크숍 범위 확정 → 견적·일정 승인", size=13, color=GRAY)

    # Footer
    foot = slide.shapes.add_textbox(Inches(0.55), Inches(6.85), Inches(12.2), Inches(0.5))
    ftf = foot.text_frame
    ftf.word_wrap = True
    para(ftf, STATUS + "  ·  " + PROVIDER, size=9, color=GRAY, first=True)
    para(ftf, "가격은 시장 검증 전 자사 가격 가설 · 범위와 인원·기간에 따라 최종 견적 · VAT는 최종 견적서에서 확정", size=9, color=GRAY)

    notes = slide.notes_slide.notes_text_frame
    notes.text = (
        "핵심 말할 내용: 1페이지 안에 문제·방식·상품·가격·다음 단계를 설명한다.\n\n"
        "고객에게 물어볼 질문: 어떤 업무가 가장 시간이 많이 걸리나요?\n\n"
        "과장해서는 안 되는 부분: 가격을 확정 가격처럼 말하지 않고, 성과·정부지원금을 보장하지 않는다."
    )

    prs.save(OUT)
    print(f"saved {OUT}")


if __name__ == "__main__":
    build()
