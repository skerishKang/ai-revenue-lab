"""Record types and lookup functions for the #6061 content-rule contract.

The vocabulary is taken from the research, not invented here:
``DocumentKind`` mirrors the seven country-specific capabilities in #6014 §3-B,
``InstitutionTier`` mirrors the tiers confirmed in #6016 to #6019, and
``Verification`` mirrors the evidence grades used throughout those reports.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Country(str, Enum):
    KR = "kr"
    US = "us"
    UK = "uk"
    FR = "fr"


class InstitutionTier(str, Enum):
    """Who holds the mandate. Deliberately not collapsed across countries."""

    # Korea
    KR_NATIONAL = "kr_national"          # 국회의원실
    KR_METROPOLITAN = "kr_metropolitan"  # 광역의회(시·도)
    KR_LOCAL = "kr_local"                # 기초의회(시·군·구)
    # United States
    US_FEDERAL_HOUSE = "us_federal_house"
    US_FEDERAL_SENATE = "us_federal_senate"
    US_STATE = "us_state"
    US_LOCAL = "us_local"
    # United Kingdom
    UK_COMMONS = "uk_commons"
    UK_LORDS = "uk_lords"
    UK_DEVOLVED = "uk_devolved"          # Holyrood / Senedd / Assembly
    UK_COUNCILLOR = "uk_councillor"
    # France
    FR_NATIONAL = "fr_national"          # député / sénateur
    FR_REGION = "fr_region"
    FR_DEPARTMENT = "fr_department"
    FR_COMMUNE = "fr_commune"
    FR_INTERCOMMUNAL = "fr_intercommunal"


class DocumentKind(str, Enum):
    """The capability axes a feature has to behave differently for."""

    SPEECH = "speech"                     # 연설문·축사
    SNS = "sns"                           # SNS 콘텐츠
    RECORD = "record"                     # 의정활동 기록
    MINUTES_SUMMARY = "minutes_summary"   # 회의록 요약
    RESEARCH = "research"                 # 자료 수집·검색
    STORED_DOCUMENT = "stored_document"   # 문서 저장·재사용
    COLLABORATION = "collaboration"       # 의원·실무진 협업
    LEGISLATIVE_DRAFT = "legislative_draft"   # 법률안·조례·수정안
    SCRUTINY = "scrutiny"                 # 행정사무감사·대응·질의
    BUDGET = "budget"                     # 예산·결산 분석
    CASEWORK = "casework"                 # 민원·casework
    FORMATTED_OFFICIAL = "formatted_official"  # 공식 문서 양식
    ELECTORAL = "electoral"               # 선거·정당 vs 공적 업무 구분


class Verification(str, Enum):
    VERIFIED = "verified"        # 1차 출처를 회수해 대조함
    UNVERIFIED = "unverified"    # 근거를 아직 회수하지 못함
    PARTIAL = "partial"          # 일부만 대조, 빈 필드가 있다


class ApprovalBasis(str, Enum):
    """What the rules say about who must approve this document kind.

    ``SELF`` is a real configuration, not a degraded one: a Korean 기초의원 or a
    US council member may be the only person in the workflow.
    """

    SELF = "self"                    # 의원 본인이 작성·승인 (강제 검토자 없음)
    STAFF_DRAFTS_MEMBER_APPROVES = "staff_drafts_member_approves"
    COMMITTEE_OR_OFFICER = "committee_or_officer"
    NOT_RESEARCHED = "not_researched"


@dataclass(frozen=True)
class Unverified:
    """A named gap: what we could not confirm, and why."""

    field: str
    reason: str


@dataclass(frozen=True)
class Source:
    title: str
    locator: str
    url: str
    accessed: str
    primary: bool = True


@dataclass(frozen=True)
class ParliamentRule:
    """One (country, tier, document kind) behaviour contract."""

    country: Country
    tier: InstitutionTier
    kind: DocumentKind
    approval: ApprovalBasis
    citation_required: bool
    coordinate_kinds: tuple[str, ...]
    effective_date_check: bool
    language_register: str
    openness: str
    terms: tuple[str, ...]
    verification: Verification
    sources: tuple[Source, ...]
    gaps: tuple[Unverified, ...] = ()
    notes: str = ""

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.country.value, self.tier.value, self.kind.value)

    @property
    def unverified_fields(self) -> tuple[str, ...]:
        return tuple(g.field for g in self.gaps)

    def is_safe_to_use_as_fact(self) -> bool:
        """A PARTIAL record may guide layout, never a legal assertion."""
        return self.verification is Verification.VERIFIED and not self.gaps


@dataclass(frozen=True)
class StaffingModel:
    """How support around a member is legally organised at that tier."""

    country: Country
    tier: InstitutionTier
    basis: str
    unit_of_support: str
    headcount_rule: str
    sources: tuple[Source, ...]
    verification: Verification = Verification.VERIFIED
    gaps: tuple[Unverified, ...] = ()


@dataclass(frozen=True)
class WorkflowStep:
    actor: str
    action: str
    mandatory: bool


_REGISTRY: dict[tuple[str, str, str], ParliamentRule] = {}
_STAFFING: dict[tuple[str, str], StaffingModel] = {}


def register_rule(rule: ParliamentRule) -> ParliamentRule:
    key = rule.key
    if key in _REGISTRY:
        raise ValueError(f"duplicate parliament rule for {key}")
    _REGISTRY[key] = rule
    return rule


def register_staffing(model: StaffingModel) -> StaffingModel:
    key = (model.country.value, model.tier.value)
    if key in _STAFFING:
        raise ValueError(f"duplicate staffing model for {key}")
    _STAFFING[key] = model
    return model


def _missing(country: str, tier: str, kind: str) -> ParliamentRule:
    """Fail-closed answer for anything we have not registered.

    Empty collections rather than defaults: a caller that forgets to check
    ``verification`` gets nothing usable instead of a plausible guess.
    """
    return ParliamentRule(
        country=Country(country),
        tier=InstitutionTier(tier),
        kind=DocumentKind(kind),
        approval=ApprovalBasis.NOT_RESEARCHED,
        citation_required=False,
        coordinate_kinds=(),
        effective_date_check=False,
        language_register="",
        openness="",
        terms=(),
        verification=Verification.UNVERIFIED,
        sources=(),
        gaps=(Unverified("whole record", f"no research registered for {country}/{tier}/{kind}"),),
        notes="fail-closed placeholder",
    )


def _coerce(enum, value, label):
    """Enum values are the only accepted coordinates.

    An unknown country or tier raises instead of returning a placeholder, so a
    typo can never look like "researched but unverified".
    """
    if isinstance(value, enum):
        return value
    try:
        return enum(value)
    except ValueError as exc:
        raise KeyError(f"unknown {label}: {value!r}") from exc


def rule_for(country: Country | str, tier: InstitutionTier | str, kind: DocumentKind | str) -> ParliamentRule:
    c = _coerce(Country, country, "country").value
    t = _coerce(InstitutionTier, tier, "institution tier").value
    k = _coerce(DocumentKind, kind, "document kind").value
    found = _REGISTRY.get((c, t, k))
    return found if found is not None else _missing(c, t, k)


def rules_for_country(country: Country | str) -> tuple[ParliamentRule, ...]:
    c = country.value if isinstance(country, Country) else country
    return tuple(r for key, r in sorted(_REGISTRY.items()) if key[0] == c)


def registered_keys() -> tuple[tuple[str, str, str], ...]:
    return tuple(sorted(_REGISTRY))


def unresolved_keys() -> tuple[tuple[str, str, str], ...]:
    return tuple(r.key for r in _REGISTRY.values() if r.verification is not Verification.VERIFIED)


def staffing_for(country: Country | str, tier: InstitutionTier | str) -> StaffingModel | None:
    c = country.value if isinstance(country, Country) else country
    t = tier.value if isinstance(tier, InstitutionTier) else tier
    return _STAFFING.get((c, t))


def approver_required(rule: ParliamentRule) -> bool:
    """True only where the researched rule actually names another approver.

    A member who is alone in the workflow is not forced into a phantom step, so
    ``SELF`` and ``NOT_RESEARCHED`` both answer False here.
    """
    return rule.approval in (
        ApprovalBasis.STAFF_DRAFTS_MEMBER_APPROVES,
        ApprovalBasis.COMMITTEE_OR_OFFICER,
    )


def workflow_steps(rule: ParliamentRule, *, staffed: bool) -> tuple[WorkflowStep, ...]:
    """The six-stage pipeline from #6021, with the review stage omitted when
    there is no second person. Never invents an approver."""
    steps = [WorkflowStep("user", "inputs the case and source material", True)]
    steps.append(WorkflowStep("parliament ai", "drafts with citation coordinates attached", True))
    if rule.citation_required:
        steps.append(WorkflowStep("parliament ai", "attaches source and effective-date evidence", True))
    if staffed and approver_required(rule):
        steps.append(WorkflowStep("staff", "reviews draft and flags unverified claims", True))
    steps.append(WorkflowStep("member", "approves publication or keeps the draft", True))
    steps.append(WorkflowStep("parliament ai", "stores the artefact for reuse", True))
    return tuple(steps)
