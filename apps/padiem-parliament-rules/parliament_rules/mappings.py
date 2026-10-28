"""The researched values behind the #6061 contract.

Each record states which conclusion it rests on, with the primary source that
was actually retrieved during #6016 to #6019 and #6026. Where the research left
a gap the record says so in ``gaps`` instead of borrowing another tier's answer.

Coverage rule of this file: a tier/kind pair is registered only when #6014 §3-B
carries an explicit finding for it. Pairs we did not research are absent, so
``rule_for`` returns the fail-closed placeholder rather than an invention.
"""
from __future__ import annotations

from .contract import (
    ApprovalBasis,
    Country,
    DocumentKind,
    InstitutionTier,
    ParliamentRule,
    Source,
    StaffingModel,
    Unverified,
    Verification,
    register_rule,
    register_staffing,
)

K = DocumentKind
T = InstitutionTier
A = ApprovalBasis
V = Verification


def _src(title: str, locator: str, url: str, accessed: str = "2026-10-28") -> Source:
    return Source(title=title, locator=locator, url=url, accessed=accessed)


# --- primary sources, by short name -------------------------------------------
KR_LOCAL_AUTONOMY = _src(
    "지방자치법",
    "시행 2026-10-15 (공포 2026-04-14 / 법률 제21544호)",
    "https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=285291&efYd=20261015&chrClsCd=010202&urlMode=lsInfoP",
)
KR_ASSEMBLY_ACT = _src(
    "국회법",
    "시행 2026-10-02 (공포 2026-09-08 / 법률 제21883호)",
    "https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=289167&efYd=20261002&chrClsCd=010202&urlMode=lsInfoP",
)
KR_DECREE = _src(
    "행정업무의 운영 및 혁신에 관한 규정",
    "시행 2026-10-02 (공포 2026-09-29 / 대통령령 제36728호)",
    "https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=290525&efYd=20261002&chrClsCd=010202&urlMode=lsInfoP",
)
KR_STAFF_ACT = _src(
    "국회의원의 보좌직원과 수당 등에 관한 법률",
    "시행 2022-04-05 (공포 2022-01-04 / 법률 제18719호)",
    "https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=238915&efYd=20220405&chrClsCd=010202&urlMode=lsInfoP",
)
KR_Gyeongnam_RULES = _src(
    "경상남도의회 회의 규칙",
    "공포 2026-06-25 / 제100호 (자치법규일련번호 2134141)",
    "https://www.law.go.kr/DRF/lawService.do?OC=test&target=ordin&MST=2134141&type=XML",
)
KR_Gangjin_RULES = _src(
    "강진군의회 회의 규칙",
    "공포 2026-09-10 / 제6호 (자치법규일련번호 2169581)",
    "https://www.law.go.kr/DRF/lawService.do?OC=test&target=ordin&MST=2169581&type=XML",
)
KR_ENFORCEMENT_DECREE = _src(
    "지방자치법 시행령",
    "시행 2026-07-01 (공포 2026-06-23 / 대통령령 제36424호)",
    "https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=287053&efYd=20260701&chrClsCd=010202&urlMode=lsInfoP",
)
KR_LOCAL_ACCOUNTING = _src(
    "지방회계법",
    "시행 2026-10-20 (공포 2026-10-20 / 법률 제22084호)",
    "https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=291205&efYd=20261020&chrClsCd=010202&urlMode=lsInfoP",
)

US_HOUSE_CSM = _src(
    "House Communications Standards Manual",
    "판 호 확인 필요 (2025-12-01 본문을 회수; HCSC Rules Rule 26은 2020판을 편입했다고 선언)",
    "https://cha.house.gov/communications-standards-manual",
)
US_HCSC_RULES = _src(
    "Rules of the House Communications Standards Commission, 119th Congress",
    "Commission Resolution 119-01 (2 U.S.C. §§501·504 + House Rule XXIV clauses (4)-(9))",
    "https://cha.house.gov/house-communications-standards-commission-rules",
)
US_SENATE_SOPOEA = _src(
    "CRS R44399, Senators' Official Personnel and Office Expense Account",
    "Version 6, updated 2026-08-04",
    "https://www.congress.gov/crs_external_products/R/PDF/R44399/R44399.6.pdf",
)
US_SENATE_APPROP = _src(
    "S. Rept. 119-38, Legislative Branch Appropriations 2026",
    "2025-07-10",
    "https://www.govinfo.gov/content/pkg/CRPT-119srpt38/pdf/CRPT-119srpt38.pdf",
)
US_IOWA_CODE = _src(
    "Iowa Code §2.10 (2022 edition)",
    "salary and district allowance",
    "https://www.legis.iowa.gov/docs/code/2022/2.10.pdf",
)
US_WA_RCW_35A = _src(
    "RCW 35A.13.010 (code city, council-manager)",
    "councilmembers are the only elective officers; city manager heads the administration",
    "https://app.leg.wa.gov/RCW/default.aspx?cite=35A.13.010",
)
US_WA_PRA = _src(
    "RCW 42.56.010 / 42.30.080",
    "public records and open public meetings reach local agencies",
    "https://app.leg.wa.gov/RCW/default.aspx?cite=42.56.010",
)
US_FPPC_MAIL = _src(
    "California FPPC, Prohibited Mass Mailings (Gov. Code §§89001-89003)",
    "digital channels excluded from the mass-mailing rule",
    "https://www.fppc.ca.gov/learn/public-official-and-employee-rules/communications-sent-using-public-funds/prohibited-mass-mailings/",
)
US_OSC_HATCH = _src(
    "U.S. Office of Special Counsel, Hatch Act: State, D.C. and Local",
    "5 U.S.C. §§1501-1508; elected officers exempt from the candidacy bar",
    "https://www.osc.gov/services/hatch-act/statelocal/",
)

UK_PSA_2009 = _src(
    "Parliamentary Standards Act 2009, s.2",
    "Nothing in this Act shall affect the House of Lords",
    "https://www.legislation.gov.uk/ukpga/2009/13/section/2",
)
UK_SCOTLAND_ACT = _src(
    "Scotland Act 1998, s.1 and Schedule 1",
    "73 constituencies; eight regions; seven regional members each",
    "https://www.legislation.gov.uk/ukpga/1998/46/schedule/1/data.xml",
)
UK_WALES_ACT = _src(
    "Government of Wales Act 2006, s.1(2) as substituted by asc 4 s.1",
    "16 Senedd constituencies, six seats each; in force 2024-08-24",
    "https://www.legislation.gov.uk/ukpga/2006/32/section/1",
)
UK_NIA_1998 = _src(
    "Northern Ireland Act 1998, s.34(2) and s.29",
    "single transferable vote; statutory committees",
    "https://www.legislation.gov.uk/ukpga/1998/47/section/34",
)
UK_DPA_2018 = _src(
    "Data Protection Act 2018, Schedule 1 Part 2 paragraph 23",
    "elected representative definition reaches local authority members and mayors",
    "https://www.legislation.gov.uk/ukpga/2018/12/schedule/1/data.xml",
)
UK_LGA_2003_REGS = _src(
    "Local Authorities (Members' Allowances) (England) Regulations 2003",
    "SI 2003/1021 - no staff allowance line",
    "https://www.legislation.gov.uk/uksi/2003/1021/contents",
)
UK_SENNEDD_DETERMINATION = _src(
    "Determination on Members' Pay, Staffing and Business Costs 2026-27 (No. 2)",
    "Independent Remuneration Board of the Senedd, issued September 2026",
    "https://remunerationboard.wales/media/tvuisvwc/determination-on-members-pay-staffing-and-business-costs-2026-27-number-2.pdf",
)
UK_NI_STAFFING = _src(
    "Assembly Members (Office and Staffing Costs and Allowances) Determination (NI) 2025",
    "revised 2026-04-30; para 28(3) record-keeping duty",
    "https://www.niassembly.gov.uk/your-mlas/members-salaries-and-expenses/administration-guide---financial-support-for-members/",
)
UK_WELSH_MEASURE = _src(
    "Welsh Language (Wales) Measure 2011, Part 4 (ss.25-34)",
    "standards include a record-keeping duty on designated bodies",
    "https://www.legislation.gov.uk/mwa/2011/1/contents",
)

FR_DGCL_MAIRE = _src(
    "DGCL, Guide du maire 2026, Chapitre 2",
    "CGCT L.2121-28 and CGFP L.333-1 to L.333-12",
    "https://www.collectivites-locales.gouv.fr/files/files/1.%20Connaitre%20les%20acteurs%20et%20les%20institutions/3.%20Elus%20locaux/guide%20du%20maire%202026/Chapitre%202_DGCL_Guide-du-Maire_2026.pdf",
)
FR_DGCL_STATUT = _src(
    "DGCL, Un nouveau statut de l'élu local",
    "loi n° 2025-1249 du 22 décembre 2025, published JO 2025-12-23",
    "https://www.collectivites-locales.gouv.fr/actualites/un-nouveau-statut-de-lelu-local",
)
FR_CONSTITUTION_PETITIONS = _src(
    "Assemblée nationale, Fiches Connaissance de l'Assemblée (art. 44·40·45·51-2)",
    "official index and Fiche PDF",
    "https://www.assemblee-nationale.fr/dyn/synthese",
)
FR_PETITIONS_PLATFORM = _src(
    "Petitions de l'Assemblée nationale",
    "thresholds 100 000 and 500 000 signatures",
    "https://petitions.assemblee-nationale.fr/pages/parcours_petition",
)
FR_SENAT_DATA = _src(
    "data.senat.fr open data",
    "AMELI amendments, DOSLEG, comptes rendus, questions",
    "https://data.senat.fr/",
)

KR_TERMS = ("의원", "보좌진", "정책지원관", "전문위원", "의안", "조례", "행정사무감사")
US_TERMS = ("Member of Congress", "state legislator", "chief of staff", "caucus staff", "constituent", "council-manager")
UK_TERMS = ("MP", "constituency", "casework", "member of staff", "councillor", "MS", "MSP", "MLA")
FR_TERMS = ("député", "collaborateur", "conseiller municipal", "délibération", "arrêté", "amendement")


def _rule(
    country: Country,
    tier: T,
    kind: K,
    approval: A,
    *,
    citation: bool,
    coords: tuple[str, ...],
    effective: bool,
    register: str,
    openness: str,
    terms: tuple[str, ...],
    verification: V,
    sources: tuple[Source, ...],
    gaps: tuple[Unverified, ...] = (),
    notes: str = "",
) -> ParliamentRule:
    return register_rule(
        ParliamentRule(
            country=country,
            tier=tier,
            kind=kind,
            approval=approval,
            citation_required=citation,
            coordinate_kinds=coords,
            effective_date_check=effective,
            language_register=register,
            openness=openness,
            terms=terms,
            verification=verification,
            sources=sources,
            gaps=gaps,
            notes=notes,
        )
    )


# =========================================================================
# KOREA
# =========================================================================
# National Assembly: the member alone can never be the whole record - the
# Assembly Act requires a cost estimate from the PBO for money-binding bills.

_rule(
    Country.KR, T.KR_NATIONAL, K.LEGISLATIVE_DRAFT, A.STAFF_DRAFTS_MEMBER_APPROVES,
    citation=True, coords=("lawId+promulgationDate+promulgationNo", "articleKey", "effectiveDate"),
    effective=True, register="한글 공문서체", openness="의안 원문은 공개",
    terms=KR_TERMS, verification=V.VERIFIED,
    sources=(KR_ASSEMBLY_ACT,),
    notes="국회법 제79조(10인 찬성·대표발의 명시)·제79조의2(비용추계서)",
)
_rule(
    Country.KR, T.KR_METROPOLITAN, K.LEGISLATIVE_DRAFT, A.SELF,
    citation=True, coords=("ordinanceId", "promulgationDate", "effectiveDate"),
    effective=True, register="한글 공문서체", openness="조례 공포·시행 정보 공개",
    terms=KR_TERMS, verification=V.PARTIAL,
    sources=(KR_LOCAL_AUTONOMY, KR_Gyeongnam_RULES),
    gaps=(Unverified("initiation quorum", "경상남도의회 회의규칙에 정족수가 없고 조례로 위임된다 (#6016 §4.1)"),),
    notes="지방자치법 제76조①의 위임 + 기관별 규칙",
)
_rule(
    Country.KR, T.KR_LOCAL, K.LEGISLATIVE_DRAFT, A.SELF,
    citation=True, coords=("ordinanceId", "promulgationDate", "effectiveDate"),
    effective=True, register="한글 공문서체", openness="조례 공포·시행 정보 공개",
    terms=KR_TERMS, verification=V.VERIFIED,
    sources=(KR_LOCAL_AUTONOMY, KR_Gangjin_RULES),
    notes="강진군의회 회의규칙 제21조: 재적 5분의 1 연서, 제21조② 비용추계 생략 가능",
)
_rule(
    Country.KR, T.KR_METROPOLITAN, K.SCRUTINY, A.SELF,
    citation=True, coords=("documentTitle", "page"),
    effective=True, register="한글 공문서체", openness="감사·조사는 공개 원칙(예외 의결)",
    terms=KR_TERMS, verification=V.VERIFIED,
    sources=(KR_LOCAL_AUTONOMY, KR_ENFORCEMENT_DECREE),
    notes="지방자치법 제49조(시·도 14일)·시행령 제51조",
)
_rule(
    Country.KR, T.KR_LOCAL, K.SCRUTINY, A.SELF,
    citation=True, coords=("documentTitle", "page"),
    effective=True, register="한글 공문서체", openness="감사·조사는 공개 원칙(예외 의결)",
    terms=KR_TERMS, verification=V.VERIFIED,
    sources=(KR_LOCAL_AUTONOMY, KR_ENFORCEMENT_DECREE),
    notes="지방자치법 제49조(시·군·구 9일) - 광역과 기한이 다르다",
)
_rule(
    Country.KR, T.KR_NATIONAL, K.BUDGET, A.COMMITTEE_OR_OFFICER,
    citation=True, coords=("cellAddress", "sourcePage"),
    effective=False, register="한글 공문서체", openness="국가결산 공개",
    terms=KR_TERMS, verification=V.PARTIAL,
    sources=(KR_ASSEMBLY_ACT,),
    gaps=(Unverified("table schema", "별표·첨부는 조문 단위 응답에 포함되지 않는다 (#6016 §5)"),),
    notes="산수는 결정론적 계산, LLM에 맡기지 않음 (#6023)",
)
_rule(
    Country.KR, T.KR_LOCAL, K.BUDGET, A.SELF,
    citation=True, coords=("cellAddress", "sourcePage"),
    effective=False, register="한글 공문서체", openness="결산·재무보고서 공개",
    terms=KR_TERMS, verification=V.VERIFIED,
    sources=(KR_LOCAL_ACCOUNTING, KR_LOCAL_AUTONOMY),
    notes="지방회계법 제15조·제17조가 결산서 구성을 법률로 정한다",
)
_rule(
    Country.KR, T.KR_NATIONAL, K.CASEWORK, A.STAFF_DRAFTS_MEMBER_APPROVES,
    citation=False, coords=(), effective=False,
    register="한글 공문서체", openness="비공개 - 개인정보",
    terms=KR_TERMS, verification=V.PARTIAL,
    sources=(KR_ASSEMBLY_ACT,),
    gaps=(Unverified("retention", "접속기록·보관 요건 대비 구현 미확인 (#6024 §3)"),),
    notes="국회법 제123조 국민동의청원 경로는 존재, 의원실 자체 민원은 미규율",
)
_rule(
    Country.KR, T.KR_LOCAL, K.CASEWORK, A.SELF,
    citation=False, coords=(), effective=False,
    register="한글 공문서체", openness="비공개 - 개인정보",
    terms=KR_TERMS, verification=V.PARTIAL,
    sources=(KR_LOCAL_AUTONOMY,),
    gaps=(Unverified("petition route", "지방의회 청원은 의원 소개가 유일한 입구 - 소개 없는 주민문의 지위 미확인"),),
    notes="지방자치법 제85조",
)
_rule(
    Country.KR, T.KR_METROPOLITAN, K.RECORD, A.SELF,
    citation=True, coords=("meetingName", "meetingDate", "speaker"),
    effective=False, register="한글 공문서체",
    openness="회의록 회기 종료 후 30일 공개, 중계영상 편집 금지",
    terms=KR_TERMS, verification=V.VERIFIED,
    sources=(KR_ENFORCEMENT_DECREE, KR_Gyeongnam_RULES),
    notes="시행령 제56조①(속기·녹음 보존) + 경남 규칙 제53조·제87조의2",
)
_rule(
    Country.KR, T.KR_LOCAL, K.RECORD, A.SELF,
    citation=True, coords=("meetingName", "meetingDate", "speaker"),
    effective=False, register="한글 공문서체",
    openness="회의록 30일, 의사중계 영상 7일 내 상시 공개",
    terms=KR_TERMS, verification=V.VERIFIED,
    sources=(KR_ENFORCEMENT_DECREE, KR_Gangjin_RULES),
    notes="강진군 규칙 제56조·제58조",
)
_rule(
    Country.KR, T.KR_NATIONAL, K.FORMATTED_OFFICIAL, A.SELF,
    citation=True, coords=("lawId+promulgationDate+promulgationNo", "articleKey", "effectiveDate"),
    effective=True, register="한글·가로쓰기·24시각제 쌍점 (제7조)",
    openness="개방형 파일 형식 + 요지·키워드 요구 (제5조②)",
    terms=KR_TERMS, verification=V.PARTIAL,
    sources=(KR_DECREE,),
    gaps=(Unverified("applicability", "제2조 열거에 국회가 없어 의원실 작성물의 적용 범위가 미확정 (#6026 §1.5)"),),
    notes="제6조①(결재로 성립)·제9조①(결재 전 검토, 생략 시 사유 기재)",
)
_rule(
    Country.KR, T.KR_LOCAL, K.FORMATTED_OFFICIAL, A.SELF,
    citation=True, coords=("ordinanceId", "promulgationDate", "effectiveDate"),
    effective=True, register="한글·가로쓰기·24시각제 쌍점 (제7조)",
    openness="개방형 파일 형식 + 요지·키워드 요구 (제5조②)",
    terms=KR_TERMS, verification=V.PARTIAL,
    sources=(KR_DECREE, KR_Gangjin_RULES),
    gaps=(Unverified("applicability", "지방의회 의원실까지 제5조②·제9조가 자동 적용된다는 근거를 회수하지 못함 (#6026 §6-1)"),),
    notes="사무기구가 아닌 의원 개인 작성물에 대한 적용 범위는 미확정으로 남긴다",
)
_rule(
    Country.KR, T.KR_NATIONAL, K.ELECTORAL, A.NOT_RESEARCHED,
    citation=False, coords=(), effective=False, register="", openness="",
    terms=(), verification=V.UNVERIFIED, sources=(),
    gaps=(Unverified("whole record", "공직선거법 조문은 정수·획정만 회수했고 의원실 선거업무 경계는 미회수"),),
    notes="정치적 설득 기능은 별도 검토 전 확정 금지 (#6014 경계)",
)

# =========================================================================
# UNITED STATES
# =========================================================================
_rule(
    Country.US, T.US_FEDERAL_HOUSE, K.SNS, A.STAFF_DRAFTS_MEMBER_APPROVES,
    citation=False, coords=(), effective=False,
    register="US English, official-communications tone",
    openness="official communication - regulated content",
    terms=US_TERMS, verification=V.PARTIAL,
    sources=(US_HOUSE_CSM, US_HCSC_RULES),
    gaps=(Unverified("edition", "HCSC Rules Rule 26은 2020판을 편입하는데 회수 본문은 2025-12-01 자다 (#6026 §2.3)"),),
    notes="campaign·fundraising 콘텐츠 금지가 성문 규칙",
)
_rule(
    Country.US, T.US_FEDERAL_SENATE, K.SNS, A.SELF,
    citation=False, coords=(), effective=False,
    register="US English",
    openness="no single Senate communications manual found",
    terms=US_TERMS, verification=V.PARTIAL,
    sources=(US_SENATE_SOPOEA,),
    gaps=(Unverified("communications manual", "rules.senate.gov 403 - 상원 통신 규범 단행본 미확인 (#6017 §10)"),),
    notes="계정 전용 제한만 확인: personal·political·campaign expenses 금지",
)
_rule(
    Country.US, T.US_FEDERAL_HOUSE, K.BUDGET, A.COMMITTEE_OR_OFFICER,
    citation=True, coords=("statuteOrPublicLaw", "releasePoint"), effective=True,
    register="US English", openness="public law + committee prints",
    terms=US_TERMS, verification=V.PARTIAL,
    sources=(US_SENATE_APPROP,),
    gaps=(Unverified("sum basis", "인쇄 합계와 주별 50행 합산이 일치하지 않는다 (#6017 §10-1)"),),
)
_rule(
    Country.US, T.US_STATE, K.LEGISLATIVE_DRAFT, A.SELF,
    citation=True, coords=("stateCitation", "sessionDate"), effective=True,
    register="state drafting conventions", openness="per-state",
    terms=US_TERMS, verification=V.PARTIAL,
    sources=(US_IOWA_CODE,),
    gaps=(Unverified("50 states", "입법서비스 주체(caucus/기관형)가 주마다 달라 일반화 불가 (#6017 §3)"),),
    notes="캘리포니아는 기관이 법안을 작성, 아이오와는 caucus staff",
)
_rule(
    Country.US, T.US_LOCAL, K.LEGISLATIVE_DRAFT, A.SELF,
    citation=False, coords=(), effective=False,
    register="plain English", openness="clerk-published agenda/minutes",
    terms=US_TERMS, verification=V.VERIFIED,
    sources=(US_WA_RCW_35A, US_WA_PRA),
    notes="council-manager에서는 의원 개인 조직이 법령상 없고 기록은 clerk 단위",
)
_rule(
    Country.US, T.US_LOCAL, K.SNS, A.SELF,
    citation=False, coords=(), effective=False,
    register="plain English", openness="no state analogue of the House CSM verified",
    terms=US_TERMS, verification=V.PARTIAL,
    sources=(US_FPPC_MAIL,),
    gaps=(Unverified("state coverage", "CA 외 49개주 조사 안 함; CA는 인쇄물만 규제하고 전자채널은 명시 제외"),),
    notes="규범 공백은 자유가 아니라 미검증 (#6014 §8)",
)
_rule(
    Country.US, T.US_STATE, K.ELECTORAL, A.NOT_RESEARCHED,
    citation=False, coords=(), effective=False, register="", openness="",
    terms=(), verification=V.PARTIAL,
    sources=(US_OSC_HATCH,),
    gaps=(Unverified("state ethics codes", "OSC가 주·지방 정치활동법 목록을 보유·집행하지 않는다고 공표"),),
    notes="Hatch Act는 직원 대상, 선출직 출마는 예외",
)
_rule(
    Country.US, T.US_FEDERAL_SENATE, K.RESEARCH, A.SELF,
    citation=True, coords=("govInfoPackage", "congressGovBillId"), effective=True,
    register="US English", openness="public",
    terms=US_TERMS, verification=V.VERIFIED,
    sources=(US_SENATE_SOPOEA, _src("Congress.gov API", "/v3/member/{bioguideId} 실측 200/4,254B", "https://api.congress.gov/")),
    notes="상원 직원 공개 원자료는 Report of the Secretary (S. Doc. 119-5)",
)

# =========================================================================
# UNITED KINGDOM
# =========================================================================
_rule(
    Country.UK, T.UK_LORDS, K.STORED_DOCUMENT, A.SELF,
    citation=False, coords=(), effective=False,
    register="British English", openness="monthly claims published",
    terms=("peer", "no constituency"), verification=V.VERIFIED,
    sources=(UK_PSA_2009,),
    notes="IPSA 규범이 상원에 적용되지 않아 의원실 문서 규범도 대응물이 없다 (#6018 §1)",
)
_rule(
    Country.UK, T.UK_COMMONS, K.CASEWORK, A.STAFF_DRAFTS_MEMBER_APPROVES,
    citation=False, coords=(), effective=False,
    register="British English, clear language", openness="casework 파일은 의원 관리",
    terms=UK_TERMS, verification=V.VERIFIED,
    sources=(UK_DPA_2018,),
    notes="DPA Sch1 Pt2 ¶23이 elected representative를 정의로 포괄",
)
_rule(
    Country.UK, T.UK_COUNCILLOR, K.CASEWORK, A.SELF,
    citation=False, coords=(), effective=False,
    register="plain English", openness="constituency casework",
    terms=("councillor", "monitoring officer"), verification=V.PARTIAL,
    sources=(UK_LGA_2003_REGS, UK_DPA_2018),
    gaps=(Unverified("complaint route", "England 접수 주체(LGSCO 이관 근거) 원문 미확보 - lgo.org.uk 000"),),
    notes="수당 규정에 직원 항목이 없어 지원 인력이 없는 것이 기본",
)
_rule(
    Country.UK, T.UK_DEVOLVED, K.RECORD, A.SELF,
    citation=True, coords=("meetingName", "meetingDate", "speaker"), effective=False,
    register="British English (Welsh bilingual where standards apply)",
    openness="official record + full translation duty",
    terms=UK_TERMS, verification=V.PARTIAL,
    sources=(UK_WELSH_MEASURE, UK_SCOTLAND_ACT),
    gaps=(Unverified("per-institution scheme", "Holyrood/Senedd/Assembly 기록 규범이 문서가 달라 기관별 확인 필요"),),
)
_rule(
    Country.UK, T.UK_DEVOLVED, K.STORED_DOCUMENT, A.SELF,
    citation=False, coords=(), effective=False,
    register="British English", openness="allowance publication systems",
    terms=UK_TERMS, verification=V.VERIFIED,
    sources=(UK_SENNEDD_DETERMINATION, UK_NI_STAFFING, UK_WALES_ACT, UK_NIA_1998),
    notes="4나라가 서로 다른 기관·문서로 직원 예산을 정한다 (#6018 §2-4)",
)
_rule(
    Country.UK, T.UK_COMMONS, K.ELECTORAL, A.NOT_RESEARCHED,
    citation=False, coords=(), effective=False, register="", openness="",
    terms=(), verification=V.UNVERIFIED, sources=(),
    gaps=(Unverified("whole record", "MP 사무실 통신에 대한 chamber-level 규범이 없다는 관측 외에는 미회수"),),
)

# =========================================================================
# FRANCE
# =========================================================================
_rule(
    Country.FR, T.FR_NATIONAL, K.LEGISLATIVE_DRAFT, A.STAFF_DRAFTS_MEMBER_APPROVES,
    citation=True, coords=("legiArticle", "LEGITEXT", "versionDate"), effective=True,
    register="français naturel", openness="documents législatifs publics",
    terms=FR_TERMS, verification=V.PARTIAL,
    sources=(FR_CONSTITUTION_PETITIONS, _src("DILA open data", "LEGITEXT/LEGIARTI, ETAT=VIGUEUR", "https://www.dila.gouv.fr/editeur")),
    gaps=(Unverified("dila editeur page", "404 회수 - 미러 경로로 대체 확인 (#6022)"),),
    notes="art. 44·40·45; art. 40 재정 수용성 통제는 작성 시점에 필요",
)
_rule(
    Country.FR, T.FR_COMMUNE, K.STORED_DOCUMENT, A.SELF,
    citation=False, coords=(), effective=False,
    register="français administratif", openness="RAJA·délibérations",
    terms=FR_TERMS, verification=V.VERIFIED,
    sources=(FR_DGCL_MAIRE,),
    notes="groupe d'élus 수단은 L.2121-28(10만 명 이상, 상한 30%), 직원 근거는 CGFP L.333-1 이하",
)
_rule(
    Country.FR, T.FR_COMMUNE, K.CASEWORK, A.SELF,
    citation=False, coords=(), effective=False,
    register="français administratif", openness="non-public",
    terms=FR_TERMS, verification=V.PARTIAL,
    sources=(FR_DGCL_MAIRE,),
    gaps=(Unverified("petition route", "3DS 법의 지방 청원·citoyen 회의 조문을 공식 원문으로 특정 실패 (#6019 §8)"),),
)
_rule(
    Country.FR, T.FR_NATIONAL, K.CASEWORK, A.STAFF_DRAFTS_MEMBER_APPROVES,
    citation=False, coords=(), effective=False,
    register="français", openness="pétitions publiques dès 100 000 signatures",
    terms=FR_TERMS, verification=V.VERIFIED,
    sources=(FR_PETITIONS_PLATFORM,),
    notes="100 000 / 500 000 + 30 départements 임계값",
)
_rule(
    Country.FR, T.FR_NATIONAL, K.RESEARCH, A.SELF,
    citation=True, coords=("legiArticle", "JORFDate"), effective=True,
    register="français", openness="open data",
    terms=FR_TERMS, verification=V.PARTIAL,
    sources=(FR_SENAT_DATA,),
    gaps=(Unverified("assemblee api", "DNS 실패 + SPA 셸 404 - API 성공 호출 0건 (#6019 §5)"),),
    notes="상원은 데이터셋, 하원은 파일 경로",
)
_rule(
    Country.FR, T.FR_NATIONAL, K.ELECTORAL, A.NOT_RESEARCHED,
    citation=False, coords=(), effective=False, register="", openness="",
    terms=(), verification=V.UNVERIFIED, sources=(),
    gaps=(Unverified("whole record", "선거기간 공표 금지의 성문 근거를 특정하지 못함"),),
)


# =========================================================================
# staffing models (#6014 §3-B1) - who may employ whom, per tier
# =========================================================================
register_staffing(StaffingModel(
    Country.KR, T.KR_NATIONAL,
    basis="국회의원의 보좌직원과 수당 등에 관한 법률 제2조·제5조·제6조",
    unit_of_support="의원 개인 사무실(법정 정원)",
    headcount_rule="별표 1에 정원이 고정되어 있으나 조문 단위 응답에 별표가 없다",
    sources=(KR_STAFF_ACT,),
    verification=V.PARTIAL,
    gaps=(Unverified("headcount", "별표 1 수치 미회수 (#6016 §5-1)"),),
))
register_staffing(StaffingModel(
    Country.KR, T.KR_METROPOLITAN,
    basis="지방자치법 제41조 + 시행령 제36조",
    unit_of_support="의회 소속 정책지원관(지방공무원)",
    headcount_rule="의원 정수의 2분의 1 범위에서 조례로 정한다",
    sources=(KR_LOCAL_AUTONOMY, KR_ENFORCEMENT_DECREE),
))
register_staffing(StaffingModel(
    Country.KR, T.KR_LOCAL,
    basis="지방자치법 제41조·제102조·제103조",
    unit_of_support="의회 사무국·사무과 직원(임면권은 의장)",
    headcount_rule="정수는 대통령령 기준을 고려한 조례, 의원 개인 보좌 인력은 법에 없음",
    sources=(KR_LOCAL_AUTONOMY,),
))
register_staffing(StaffingModel(
    Country.US, T.US_FEDERAL_SENATE,
    basis="2 U.S.C. §4575 + S. Rept. 119-38 + CRS R44399",
    unit_of_support="상원 의원실(SOPOEA 통합계정)",
    headcount_rule="인원 상한 없음 - 상한은 달러와 보수율",
    sources=(US_SENATE_SOPOEA, US_SENATE_APPROP),
))
register_staffing(StaffingModel(
    Country.US, T.US_LOCAL,
    basis="RCW 35A.13.010 (council-manager 사례)",
    unit_of_support="시 행정부(city manager) 소속",
    headcount_rule="의원은 유일한 선출직, 개인 보좌 조직이 법령상 없음",
    sources=(US_WA_RCW_35A,),
    verification=V.PARTIAL,
    gaps=(Unverified("other cities", "Seattle 외 표본 없음, 50개주 로컬 일반화 불가"),),
))
register_staffing(StaffingModel(
    Country.UK, T.UK_LORDS,
    basis="Parliamentary Standards Act 2009 s.2",
    unit_of_support="유급 각료·office holder의 secretarial assistance만",
    headcount_rule="peer 일반 직원 항목 없음",
    sources=(UK_PSA_2009,),
))
register_staffing(StaffingModel(
    Country.UK, T.UK_COUNCILLOR,
    basis="Local Authorities (Members' Allowances) (England) Regulations 2003",
    unit_of_support="지방당 officer(monitoring officer 등) - 의원 개인 직원 아님",
    headcount_rule="수당 체계에 직원 항목 없음",
    sources=(UK_LGA_2003_REGS,),
))
register_staffing(StaffingModel(
    Country.UK, T.UK_DEVOLVED,
    basis="Senedd determination 2026-27 / NI Office and Staffing Determination 2025",
    unit_of_support="기관별 상한액 지원 인력",
    headcount_rule="웨일스 £148,382·북아일랜드 £90,900 등 문서별 상한",
    sources=(UK_SENNEDD_DETERMINATION, UK_NI_STAFFING),
    verification=V.PARTIAL,
    gaps=(Unverified("scotland figures", "레인 회수치(£169,000)를 제 손으로 재대조하지 않음"),),
))
register_staffing(StaffingModel(
    Country.FR, T.FR_NATIONAL,
    basis="crédit collaborateur (AN Fiche n°11)",
    unit_of_support="député 개인 고용(사법상 계약)",
    headcount_rule="월 11,463 유로 한도, 최대 5명",
    sources=(_src("AN Fiche n°11", "collaborateurs du député", "https://www.assemblee-nationale.fr"),),
    verification=V.PARTIAL,
    gaps=(Unverified("fiche url", "Fiche 상세 URL을 이번 세션에서 재확인하지 않음 (#6015 회수)"),),
))
register_staffing(StaffingModel(
    Country.FR, T.FR_COMMUNE,
    basis="CGFP L.333-1 à L.333-11 (cabinet), L.333-12 (groupes), CGCT L.2121-28",
    unit_of_support="cabinet 직원 / groupe d'élus 직원",
    headcount_rule="코뮌 10만 명 이상에서 groupe 수단 상한 30%(indemnités 총액, 사회보험료 포함)",
    sources=(FR_DGCL_MAIRE,),
))
register_staffing(StaffingModel(
    Country.FR, T.FR_DEPARTMENT,
    basis="loi n° 2025-1249 du 22 décembre 2025",
    unit_of_support="département 차등 지원",
    headcount_rule="조문별 병렬 체계, 현행 상한은 미확인",
    sources=(FR_DGCL_STATUT,),
    verification=V.PARTIAL,
    gaps=(Unverified("groupe means", "L.2121-28에 대응하는 département 조문을 특정하지 못함 (#6019 §8-1)"),),
))
