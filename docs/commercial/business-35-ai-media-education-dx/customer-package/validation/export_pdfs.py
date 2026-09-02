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
            capture_output=True, text=True, timeout=60
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
    pages = [
        ("Business 35 \u00b7 AI Media Education & DX", "AI 교육에서 실제 업무전환까지", "지역 문화\u00b7교육\u00b7미디어 조직을 위한 진단\u00b7실습\u00b7워크플로 재설계\u00b7파일럿 프로그램\n제공: 파디엠\n대상: 지역 문화기관 \u00b7 교육기관 \u00b7 협회\u00b7단체 \u00b7 미디어\u00b7콘텐츠 기관\n대표 진입 상품: 상품 A \u00b7 진단 워크숍 (초기형 300만~500만원)\n파디엠 \u00b7 DRAFT\n가격은 시장 검증 전 자사 가격 가설입니다."),
        ("2. 현재 문제", "콘텐츠 제작은 늘었지만 조직의 기준과 검토체계는 따라오지 못합니다.", "수작업 제작 / 개인별 AI 사용 / 검토 기준 부재\n파디엠 \u00b7 DRAFT"),
        ("3. 일반 AI 교육의 한계", "교육 수료와 실제 업무 전환은 다릅니다.", "강의를 들어도 업무가 바뀌지 않음\n정책\u00b7검토\u00b7승인\u00b7측정과 연결되지 않음\n파디엠 \u00b7 DRAFT"),
        ("4. Business 35 방식 \u2014 AI 업무전환 프로그램", "진단에서 운영 플레이북까지 이어지는 7단계 업무전환 구조입니다.", "교육에서 끝나지 않고, 실제 업무 진단\u00b7실습\u00b7재설계\u00b7파일럿\u00b7측정\u00b7플레이북까지 연결합니다.\n진단 / 직무 교육 / 실제 실습 / 워크플로 재설계 / 제한 파일럿 / 성과 측정 / 운영 플레이북\n파디엠 \u00b7 DRAFT"),
        ("5. 대상 업무 \u2014 합성 예시", "지역 문화\u00b7교육\u00b7미디어 조직에서 시작하기 쉬운 업무입니다.", "행사 홍보물 초안 / 교육 프로그램 안내문 / 뉴스레터 초안 / SNS 콘텐츠 변환 / 자료 요약 / 검토 체크리스트\n이것은 실제 고객 성과 사례가 아니라 대상 업무의 합성 예시입니다.\n파디엠 \u00b7 DRAFT"),
        ("6. 상품 A \u2014 AI 업무전환 진단 워크숍", "짧고 낮은 진입장벽으로 고객의 첫 결정을 만듭니다.", "1~2일 워크숍\n초기형 300만~500만원 / 확장형 500만~800만원\n주요 산출물: 현재 업무 흐름 진단 / AI 적용 후보 업무 1~3개 선정 / 위험\u00b7금지 업무 분리\n파디엠 \u00b7 DRAFT\n가격은 시장 검증 전 자사 가격 가설입니다."),
        ("7. 상품 B1 \u2014 6주 디자인 파트너 파일럿", "작게 실행하고, 측정하고, 운영 기준을 남깁니다.", "6주 \u00b7 1팀 \u00b7 1핵심 업무\n1,000만~1,500만원 / 상품 B1 \u00b7 디자인 파트너\n파일럿 진행 흐름: 기준선 측정 / 직무별 교육 / 워크플로 재설계 / 제한 파일럿 / 성과\u00b7위험 보고서\nW0 계약\u00b7범위 / W1 진단\u00b7기준선 / W2 교육\u00b7실습 / W3 재설계 / W4 제한 파일럿 / W5 측정\u00b7보완 / W6 결과\u00b7플레이북\n파디엠 \u00b7 DRAFT"),
        ("8. KPI\u00b7위험관리", "속도만 보지 않고 품질\u00b7채택\u00b7거버넌스를 함께 봅니다.", "KPI 예시: 초안 작성시간 / 검토 회차 / 수정 반려율 / 승인 소요시간 / 참여자 task completion / 위험 사례 수\n위험관리: 위험업무 제외 \u00b7 사람 검토 gate \u00b7 승인 도구 외 사용 금지\nKPI는 목표 가설이며 성과 보장을 의미하지 않습니다.\n파디엠 \u00b7 DRAFT"),
        ("9. 가격 가설", "시장 검증 전 자사 가격 가설이며 범위 확인 후 최종 견적을 제시합니다.", "상품 A 진단 워크숍 초기형 300만~500만원 확장형 500만~800만원\n상품 B1 디자인 파트너 1,000만~1,500만원 6주 파일럿\n상품 B2 표준 파일럿 1,500만~2,500만원 6주 파일럿\n상품 C 운영 자문 월 300만~600만원 월 단위\n시장 검증 전 자사 가격 가설 / 범위\u00b7인원\u00b7기간에 따라 최종 견적 \u00b7 VAT 조건은 최종 견적서에서 확정\n파디엠 \u00b7 DRAFT"),
        ("10. 다음 단계", "30분 상담에서 대상 업무 하나를 정하고, 워크숍 범위를 확정합니다.", "1 30분 사전 상담 / 2 대상 업무 1개 선정 / 3 진단 워크숍 범위 확정 / 4 견적\u00b7일정 승인\n첫 상담에서 계약을 압박하지 않으며, 정부지원금 확정을 말하지 않습니다.\n조직별 사용정책\u00b7검토체계, 개인정보\u00b7저작권\u00b7조달, 전문 법률\u00b7계약 검토가 필요합니다.\n제공 및 계약 주체: 파디엠\n가격은 시장 검증 전 가설이며 범위\u00b7인원\u00b7기간에 따라 달라질 수 있습니다.\n전문 법률\u00b7계약 검토 후 최종 확정됩니다.\n파디엠 \u00b7 DRAFT"),
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
    pdf.multi_cell(190, 4, "교육에서 끝나지 않고, 실제 업무 진단\u00b7실습\u00b7워크플로 재설계\u00b7파일럿\u00b7측정\u00b7운영 플레이북까지 연결합니다.")
    pdf.set_text_color(*GRAY)
    pdf.set_font('Malgun', '', 6.5)
    lines = [
        "고객의 현재 문제: 수작업 콘텐츠 제작 / 개인별 AI 사용 / 검토\u00b7승인 기준 부재 / 개인정보\u00b7저작권 위험",
        "Business 35 방식: 진단 \u2192 직무 교육 \u2192 실제 실습 / 워크플로 재설계 \u2192 제한 파일럿 / 성과 측정 \u2192 운영 플레이북",
        "상품 A \u00b7 진단 워크숍: 1~2일 \u00b7 초기형 300만~500만원 \u00b7 확장형 500만~800만원 \u00b7 현재 흐름 진단 \u00b7 후보 선정 \u00b7 위험 분리",
        "상품 B1 \u00b7 디자인 파트너 파일럿: 6주 \u00b7 1팀 \u00b7 1업무 \u00b7 1,000만~1,500만원",
        "상품 B2 \u00b7 표준 6주 파일럿: 6주 \u00b7 1,500만~2,500만원 \u00b7 기준선\u00b7교육\u00b7재설계\u00b7파일럿\u00b7성과\u00b7플레이북",
        "상품 C \u00b7 운영 자문 \u00b7 월 300만~600만원",
        "다음 행동: 30분 사전 상담 \u2192 대상 업무 1개 선정 \u2192 진단 워크숍 범위 확정 \u2192 견적\u00b7일정 승인",
        "파디엠 \u00b7 DRAFT",
        "가격은 시장 검증 전 가설이며 범위\u00b7인원\u00b7기간에 따라 달라질 수 있습니다.",
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
        ("파디엠 \u00b7 AI 업무전환 진단 질문지   1. 조직\u00b7팀 기본정보   [ 1 / 3 ]", [
            "Business 35 \u00b7 AI 업무전환 프로그램",
            "고객 진단 질문지 \u00b7 작성 전 안내",
            "본 질문지는 견적\u00b7일정 확정 전 진단 자료로만 사용됩니다. 실제 개인정보나 내부자료의 원문을 기입하지 마시고, 분류\u00b7포함 여부만 표시해 주세요.",
            "1.1 조직 이름과 소속 팀, 팀 인원은 어떻게 되나요? (조직명\u00b7직책\u00b7인원만 기재)",
            "________________________________________________________",
            "1.2 콘텐츠\u00b7홍보\u00b7교육 업무를 담당하는 인력이 있나요?     예     아니오",
            "2.1 현재 콘텐츠 제작이 어떤 단계로 진행되나요? (기획\u2192초안\u2192검토\u2192승인\u2192게시 순으로)",
            "2.2 주요 콘텐츠 유형은 무엇인가요?     홍보물     안내문     뉴스레터     SNS     기타",
            "3.1 콘텐츠 1건당 각 단계에 며칠/몇 시간이 걸리나요? (단계별 시간 표)",
            "3.2 가장 오래 걸리는 단계는 무엇인가요? (짧게)",
            "파디엠 \u00b7 DRAFT",
        ]),
        ("파디엠 \u00b7 AI 업무전환 진단 질문지   4. 검토 단계   [ 2 / 3 ]", [
            "4.1 검토와 승인이 몇 단계이며, 누가 승인하나요? (단계 목록 + 직책)",
            "4.2 검토\u00b7승인 기준은 문서화되어 있나요?     예     아니오     부분",
            "5.1 조직원이 현재 사용하는 AI 도구와 용도는 무엇인가요? (도구명 + 용도)",
            "5.2 조직 차원의 AI 사용정책이 있나요?     예     아니오",
            "6.1 AI에 절대 입력하면 안 되는 자료가 있나요? (비밀\u00b7기밀\u00b7법률 검토 필요 자료 \u2014 유형 분류만)",
            "7.1 제작 콘텐츠에 개인정보가 포함됩니까?     예     아니오     일부",
            "8.1 타인 저작물을 사용하거나 외부 학습에 쓸 자료가 있나요?     예     아니오     일부",
            "9.1 파일럿 예산과 결과를 최종 승인할 수 있는 사람은 누구인가요? (직책만)",
            "파디엠 \u00b7 DRAFT",
        ]),
        ("파디엠 \u00b7 AI 업무전환 진단 질문지   10. 기준선 데이터   [ 3 / 3 ]", [
            "10.1 기준선(생산시간\u00b7재작업률 등)으로 쓸 수 있는 데이터가 있나요? (가능 항목 나열)",
            "11.1 6주 파일럿 후보 업무 1개를 고른다면 무엇인가요? (1건 선택)",
            "11.2 참여 팀(6\u201310명)과 운영 책임자 1인을 지정할 수 있나요?     예     아니오",
            "12.1 파일럿이 성공했다고 판단하는 기준은 무엇인가요? (예: 생산시간 단축, 품질 유지)",
            "13.1 어떤 경우에 파일럿을 중단해야 하나요? (위험업무 침범\u00b7자동 게시 요구 등)",
            "본 질문지는 견적\u00b7일정 확정 전 진단 자료로만 사용됩니다. 가격은 시장 검증 전 자사 가격 가설이며 실제 계약\u00b7매출 주장이 아닙니다. 조직별 사용정책\u00b7검토체계, 개인정보\u00b7저작권\u00b7조달 관련 사항은 고객별 확인과 전문 법률\u00b7계약 검토가 필요합니다.",
            "파디엠 \u00b7 DRAFT",
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
        if generated.exists() and generated != out_one_pdf:
            generated.rename(out_one_pdf)
            print(f"libreoffice converted onepage to {out_one_pdf.name}")
        elif not out_one_pdf.exists():
            fallback_onepage_pdf(out_one_pdf)
            print(f"fallback generated {out_one_pdf.name}")
        else:
            if not out_one_pdf.exists():
                fallback_onepage_pdf(out_one_pdf)
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
