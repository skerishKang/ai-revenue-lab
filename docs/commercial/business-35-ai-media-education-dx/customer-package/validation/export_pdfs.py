#!/usr/bin/env python3
"""Export PPTX/DOCX to PDF deterministically using fpdf2 with Korean font."""
from __future__ import annotations
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def try_libreoffice(src: Path, out_dir: Path) -> bool:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return False
    try:
        result = subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(out_dir), str(src)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
        )
        return result.returncode == 0 and (out_dir / (src.stem + ".pdf")).exists()
    except Exception as e:
        print(f"libreoffice failed for {src.name}: {e}")
        return False

def _make_fpdf():
    from fpdf import FPDF
    import datetime
    pdf = FPDF(format='A4')
    pdf.set_auto_page_break(auto=False)
    # deterministic creation date per #1504 build integrity
    try:
        pdf.set_creation_date(datetime.datetime(2026, 9, 3, 0, 0, 0))
    except Exception:
        pass
    # Register Korean font
    try:
        pdf.add_font('Malgun', '', r'C:\Windows\Fonts\malgun.ttf')
        pdf.add_font('Malgun', 'B', r'C:\Windows\Fonts\malgunbd.ttf')
    except Exception as e:
        print(f"font add failed: {e}")
        pass
    return pdf

def fallback_proposal_pdf(out_path: Path):
    pdf = _make_fpdf()
    NAVY = (31, 58, 95)
    GRAY = (85, 90, 96)
    journey = ("현재 미디어 업무 병목 이해 → 조직·결과물·병목·팀 규모·AI 사용 상태 입력 "
               "→ 조직별 진단 + 새 업무 흐름 + 추천 파일럿 확인 → 운영체계 산출물 이해 "
               "→ 진단 워크숍 또는 6주 파일럿 범위 판단 → 자기 조직용 전환 요약으로 상담 준비")
    pages = [
        ("1. 제품과 결과 — 파디엠 AI 미디어 업무전환 스튜디오", "팀의 실제 미디어 업무 한 흐름을 사람이 승인하는 운영체계로 바꾼다",
         "파디엠 AI 미디어 업무전환 스튜디오 — 서비스 주도형 업무전환 스튜디오\n입력 한 번으로 진단·새 업무 흐름·사람 검토 지점·추천 파일럿·운영 산출물을 구성한다\n대상: 지역 문화기관 · 교육기관 · 협회·단체 · 미디어·콘텐츠 기관 · 기업 홍보·콘텐츠팀\n제품 흐름: 고객 입력 → 진단 → 새 workflow → 추천 pilot\nV3.1 여정: " + journey + "\n실제 계약·매출 발생 주장이 아닙니다. 제공: 파디엠\n파디엠 · DRAFT\n가격은 시장 검증 전 자사 가격 가설입니다."),
        ("2. 지금 바꿀 업무를 고른다", "어떤 미디어 업무의 어디가 막혀 있는지를 먼저 정한다",
         "다섯 가지 입력: 조직·결과물·병목·팀 규모·AI 사용 상태\n결과물 후보: 홍보물·교육자료·영상·이미지·캠페인 콘텐츠\n병목 후보: 기획·초안·제작·검토·승인·배포\n합성·비식별 입력으로 제품 구조와 파일럿 후보 설명\n파디엠 · DRAFT"),
        ("3. 조직별 진단이 나온다", "조직마다 적용 후보·제외 영역·사람 검토 지점이 달라야 한다",
         "적용 후보 진단 / 사람 검토 지점 / 승인 도구와 금지·주의 자료의 경계\nAI 활용 확산과 함께 개인정보·저작권·투명성·안전성·사람 검토 등 조직 차원의 사용정책과 거버넌스 요구가 강화되고 있다\n진단은 법률 판단을 대신하지 않는다\n파디엠 · DRAFT"),
        ("4. 새 업무 흐름을 설계한다", "AI는 workflow 안에 들어가고, 사람 승인 gate는 사라지지 않는다",
         "현재 흐름: 기획 → 초안 → 제작 → 검토 → 승인 → 게시\n전환 흐름 예시: 요청 정의 → AI 보조 초안 → 제작 → 사람 검토 → 수정 → 승인 → 게시\n자동화 대상과 사람 담당자의 책임 구분, 예외 처리와 중단 조건 설계\n파디엠 · DRAFT"),
        ("5. 운영 산출물을 확인한다", "발표 자료가 아니라 팀이 실제로 쓰는 운영 산출물로 남는다",
         "업무 요청서 / AI 사용정책 초안 / 금지·주의 자료 기준 / 사람 검토 지도\n프롬프트·작업 템플릿 / KPI 기준선·측정표 / 파일럿 운영 체크리스트 / 전환 요약\n운영체계 산출물 이해 — 고객 조직 범위에 맞춰 선택\n파디엠 · DRAFT"),
        ("6. 상품 A · 진단 워크숍", "바꿀 업무와 파일럿 범위를 먼저 확정한다",
         "1~2일 워크숍\n초기형 300만–500만원 / 확장형 500만–800만원 (broad 300만–800만원)\n산출물: 진단 요약 / 추천 workflow 초안 / 파일럿 후보 및 범위 제안 / 위험·확인 항목 목록\n파디엠 · DRAFT\n가격은 시장 검증 전 자사 가격 가설입니다."),
        ("7. 상품 B1/B2 · 6주 파일럿", "실제 workflow와 사람 검토 체계를 6주간 시험한다",
         "B1 디자인 파트너 1,000만–1,500만원 / B2 표준 1,500만–2,500만원\nW0 범위·책임 / W1 기준선 진단 / W2 직무별 교육 / W3 실제 실습 / W4 재설계 / W5 제한 파일럿 / W6 측정·플레이북\n이 주차 구조는 제품을 정의하는 7단계 정체성이 아니라, 선택된 파일럿을 수행하는 delivery detail이다\n파디엠 · DRAFT"),
        ("8. KPI와 위험을 함께 본다", "품질·사람 검토·정책 준수·팀 사용성을 함께 측정한다",
         "KPI 후보: 기준 생산시간 vs 파일럿 생산시간 / 재작업률 / 사람 검토 통과율 / 정책 위반 또는 중단 건수 / 팀 참여·실제 사용률 / 결과물 품질 평가 / 미해결 위험·운영 산출물 승인\n위험 경계: 민감정보 무제한 외부 입력 금지 · 사람 검토 없는 자동 게시 금지\n성과를 보장하지 않는다. 기준선과 KPI로 변화 여부를 측정한다\n파디엠 · DRAFT"),
        ("9. 상품 C와 가격 가설", "범위 확인 후 최종 견적 — 모두 시장 검증 전 가설이다",
         "상품 A 진단 워크숍 초기형 300만–500만원 확장형 500만–800만원 (broad 300만–800만원)\n상품 B1 디자인 파트너 1,000만–1,500만원 6주 파일럿\n상품 B2 표준 파일럿 1,500만–2,500만원 6주 파일럿\n상품 C 운영 자문 월 300만–600만원 월 단위\nVAT 조건은 최종 견적서에서 확정 · 고객별 가격 승인 전 외부 확정가 금지\n파디엠 · DRAFT"),
        ("10. 다음 행동과 계약 경계", "진단 워크숍 또는 6주 파일럿의 범위를 먼저 확인한다",
         "1 바꿀 업무 1건 선정 / 2 검토 지점 확인 / 3 A·B1/B2 적합 판단 / 4 범위·중단 조건 합의 / 5 고객별 가격 가설 재승인 / 6 법률·계약 검토 후 최종 제안\n개인정보·저작권·조달은 고객별 확인 필요\nSOW와 위험·데이터 부속서는 전문 법률·계약 검토 필요\n제공 및 계약 주체: 파디엠\n가격은 시장 검증 전 가설, 현재 문서는 내부 상업 초안이며 실제 계약·매출 발생 주장이 아니다\n파디엠 · DRAFT"),
    ]
    for idx, (title, headline, body) in enumerate(pages, start=1):
        pdf.add_page()
        # Header band
        pdf.set_fill_color(*NAVY)
        pdf.rect(0, 0, 210, 22, 'F')
        pdf.set_y(4)
        pdf.set_font('Malgun', 'B', 13)
        pdf.set_text_color(255,255,255)
        pdf.cell(0, 8, title, align='L')
        pdf.set_font('Malgun', '', 8)
        pdf.set_text_color(*NAVY)
        pdf.set_y(26)
        pdf.cell(0, 6, headline, align='L')
        pdf.set_text_color(*GRAY)
        pdf.set_font('Malgun', '', 7)
        y = 36
        pdf.set_y(y)
        for line in body.split("\n"):
            pdf.set_x(10)
            pdf.multi_cell(190, 4, line, align='L')
        # Footer
        pdf.set_y(285)
        pdf.set_font('Malgun', '', 6)
        pdf.set_text_color(*GRAY)
        pdf.cell(0, 4, f"파디엠 \u00b7 DRAFT                                                                 {idx} / 10", align='L')
    pdf.output(str(out_path))

def fallback_onepage_pdf(out_path: Path):
    pdf = _make_fpdf()
    pdf.add_page()
    NAVY = (31, 58, 95)
    GRAY = (85, 90, 96)
    pdf.set_fill_color(*NAVY)
    pdf.rect(0, 0, 210, 32, 'F')
    pdf.set_y(6)
    pdf.set_font('Malgun', 'B', 14)
    pdf.set_text_color(255,255,255)
    pdf.cell(0, 7, "Business 35 \u00b7 AI Media Education & DX", align='L')
    pdf.set_font('Malgun', '', 9)
    pdf.cell(0, 7, "AI 업무전환 프로그램 \u2014 1페이지 소개", align='L', new_x="LMARGIN", new_y="NEXT")
    pdf.set_font('Malgun', 'B', 8)
    pdf.cell(0, 5, "제공: 파디엠", align='L')
    pdf.set_text_color(*NAVY)
    pdf.set_y(36)
    pdf.set_font('Malgun', 'B', 8)
    pdf.multi_cell(190, 4, "조직의 실제 미디어 업무 한 흐름을 입력하면, AI 적용 후보·사람 검토 지점·추천 파일럿·운영 산출물을 한 번에 구성한다.")
    pdf.set_text_color(*GRAY)
    pdf.set_font('Malgun', '', 6.5)
    lines = [
        "V3.1 사용자가 실제로 하는 일: 현재 미디어 업무의 병목을 확인한다 / 조직·결과물·병목·팀 규모·AI 사용 상태를 입력한다 / 조직별 진단과 새 업무 흐름을 확인한다 / 사람 검토 지점과 운영 산출물을 확인한다 / 추천된 진단 워크숍 또는 6주 파일럿 범위를 판단한다 / 자기 조직용 전환 요약으로 상담을 준비한다",
        "상품 A · 진단 워크숍: 1~2일 · 초기형 300만–500만원 · 확장형 500만–800만원",
        "상품 B1 · 디자인 파트너 파일럿: 6주 · 1팀 · 1업무 · 1,000만–1,500만원",
        "상품 B2 · 표준 6주 파일럿: 6주 · 1,500만–2,500만원",
        "상품 C · 운영 자문 · 월 300만–600만원",
        "다음 행동: 진단 워크숍 또는 6주 파일럿 범위 확인 → 바꾸고 싶은 미디어 업무 1건 선정 → 현재 흐름·병목·사람 검토 지점 확인",
        "파디엠 · DRAFT",
        "가격은 시장 검증 전 가설이며 범위·인원·기간에 따라 달라질 수 있습니다.",
    ]
    for line in lines:
        pdf.set_x(10)
        pdf.multi_cell(190, 4, line)
    pdf.set_y(285)
    pdf.set_font('Malgun', '', 6)
    pdf.cell(0, 4, "파디엠 \u00b7 DRAFT", align='L')
    pdf.output(str(out_path))

def fallback_questionnaire_pdf(out_path: Path):
    pdf = _make_fpdf()
    sections = [
        ("파디엠 · AI 업무전환 진단 질문지   Q1–Q5 V3.1 다섯 가지 입력   [ 1 / 3 ]", [
            "Business 35 · 파디엠 AI 미디어 업무전환 스튜디오 — 고객 진단 질문지",
            "V3.1 입력(Q1–Q5): 조직 유형 / 결과물 유형 / 병목 지점 / 현재 팀 규모 / AI 사용 상태",
            "본 질문지는 견적·일정 확정 전 진단 자료로만 사용됩니다. 실제 개인정보나 내부자료의 원문을 기입하지 마시고, 분류·포함 여부만 표시해 주세요.",
            "Q1. 조직 유형     ☐ 지역 문화기관     ☐ 지역 교육기관     ☐ 지역 협회·단체     ☐ 지역 미디어·콘텐츠 기관     ☐ 기업 홍보·콘텐츠팀     ☐ 기타",
            "Q1-기타 자유 기재: ________________________________________",
            "Q2. 결과물 유형     ☐ 홍보물     ☐ 교육자료     ☐ 영상·이미지     ☐ 캠페인 콘텐츠     ☐ 보도자료     ☐ 기타",
            "Q2-부 주 결과물 1개 + 부 결과물 목록: ________________________________________",
            "Q3. 병목 지점 (1–2개)     ☐ 기획     ☐ 초안     ☐ 제작     ☐ 검토     ☐ 승인     ☐ 배포",
            "Q3-이유: ________________________________________",
            "파디엠 · DRAFT",
        ]),
        ("파디엠 · AI 업무전환 진단 질문지   Q4–Q9 팀·상태·흐름   [ 2 / 3 ]", [
            "Q4. 현재 팀 규모 (상시 담당 인원 수 + 역할별 구성, 실명 대신 역할·인원만)",
            "________________________________________________________",
            "Q5. AI 사용 상태     ☐ 미사용     ☐ 개인별 탐색     ☐ 일부 업무 보조     ☐ 승인 도구 운영 중     ☐ 기타",
            "Q5-도구 목록: ________________________________________",
            "Q6. 현재 콘텐츠 제작 흐름 (기획→초안→검토→승인→게시 순으로)",
            "Q7. 업무별 소요시간 (콘텐츠 1건당 단계별 시간 표)",
            "Q8. 검토·승인 단계 (단계 목록 + 역할, 직책만)",
            "Q9. 현재 사용하는 AI 도구 상세 (도구명 + 용도 + 빈도)",
            "파디엠 · DRAFT",
        ]),
        ("파디엠 · AI 업무전환 진단 질문지   Q10–Q17 거버넌스·준비   [ 3 / 3 ]", [
            "Q10. 개인정보 포함 여부     ☐ 예     ☐ 아니오     ☐ 일부",
            "Q11. 저작권 자료 사용 여부     ☐ 예     ☐ 아니오     ☐ 일부",
            "Q12. 외부 공개 여부 (채널 목록): ________________________________________",
            "Q13. 재작업·실패 유형: ________________________________________",
            "Q14. 과거 교육 경험 (선택)     ☐ 예     ☐ 아니오",
            "Q15. 금지 업무: ________________________________________",
            "Q16. 파일럿 담당자 (1팀 6–10명 + 운영 책임자 1인): ________________________________________",
            "Q17. 예산 승인자 (직책): ________________________________________",
            "본 질문지는 견적·일정 확정 전 진단 자료로만 사용됩니다. 가격은 시장 검증 전 자사 가격 가설이며 실제 계약·매출 주장이 아닙니다. 조직별 사용정책·검토체계, 개인정보·저작권·조달 관련 사항은 고객별 확인과 전문 법률·계약 검토가 필요합니다.",
            "파디엠 · DRAFT",
        ]),
    ]
    for header, lines in sections:
        pdf.add_page()
        pdf.set_font('Malgun', 'B', 7)
        pdf.set_text_color(31,58,95)
        pdf.cell(0, 6, header, align='L', new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(85,90,96)
        pdf.set_font('Malgun', '', 7)
        for line in lines:
            pdf.multi_cell(190, 4, line)
            pdf.ln(1)
        pdf.set_y(285)
        pdf.set_font('Malgun', '', 6)
        pdf.cell(0, 4, "파디엠 \u00b7 DRAFT", align='L')
    pdf.output(str(out_path))

def main():
    src_pptx = ROOT / "Business35_Master_Proposal_10p.pptx"
    out_pdf = ROOT / "Business35_Master_Proposal_10p.pdf"
    if src_pptx.exists():
        ok = try_libreoffice(src_pptx, ROOT)
        if ok:
            print(f"libreoffice converted {src_pptx.name}")
        else:
            fallback_proposal_pdf(out_pdf)
            print(f"fallback generated {out_pdf.name}")
    src_one = ROOT / "Business35_OnePage_Offer_Source.pptx"
    out_one_pdf = ROOT / "Business35_OnePage_Offer.pdf"
    if src_one.exists():
        ok = try_libreoffice(src_one, ROOT)
        generated = ROOT / "Business35_OnePage_Offer_Source.pdf"
        if ok and generated.exists() and generated != out_one_pdf:
            generated.rename(out_one_pdf)
            print(f"libreoffice converted onepage to {out_one_pdf.name}")
        elif ok and out_one_pdf.exists():
            print(f"libreoffice converted {src_one.name}")
        else:
            # No LibreOffice: always regenerate deterministically (never keep stale PDF).
            fallback_onepage_pdf(out_one_pdf)
            print(f"fallback generated {out_one_pdf.name}")
    src_docx = ROOT / "Business35_Diagnostic_Questionnaire.docx"
    out_q_pdf = ROOT / "Business35_Diagnostic_Questionnaire.pdf"
    if src_docx.exists():
        ok = try_libreoffice(src_docx, ROOT)
        if ok:
            print(f"libreoffice converted {src_docx.name}")
        else:
            fallback_questionnaire_pdf(out_q_pdf)
            print(f"fallback generated {out_q_pdf.name}")

if __name__ == "__main__":
    main()
