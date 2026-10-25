import {
  computeUserValueScore,
  type PublicOpportunity,
} from './domain.js';

/**
 * Manually curated, publicly verified opportunities (B64 public supply lane).
 *
 * Every record was re-checked against the official source URL on 2026-10-25.
 * These records pay PADIEM nothing (monetizationRole NONE): they link users to
 * official provider pages. They are NOT provider-approved B2B supply and must
 * never be promoted into LIVE_AUTHORIZED provider lanes.
 *
 * COM2 owns the refresh loop (status changes, dedupe, re-verification). Until a
 * confirmed auto-collection permission exists for a vendor, updates stay on
 * this manual curation path and verifiedAt moves only with a documented check.
 */

const VERIFIED_AT = '2026-10-25T00:50:00.000Z';

const record = (
  input: Omit<PublicOpportunity, 'userValueScore' | 'monetizationRole'> &
    Partial<Pick<PublicOpportunity, 'userValueScore'>>,
): PublicOpportunity => {
  const score =
    input.userValueScore ??
    computeUserValueScore({
      rewardConfirmed: input.reward.confirmed,
      todayTier: input.todayTier,
      koreaConfirmed: input.koreaStatus === 'CONFIRMED',
    });
  return Object.freeze({ ...input, userValueScore: score, monetizationRole: 'NONE' as const });
};

export const VERIFIED_PUBLIC_OPPORTUNITIES: readonly PublicOpportunity[] = Object.freeze([
  Object.freeze(
    record({
      id: 'pub-prolific-participate',
      sourceId: 'SRC-PROLIFIC',
      vendor: 'Prolific',
      category: 'SURVEY',
      titleKo: 'Prolific 유료 온라인 리서치 참여 (한국 참여 가능)',
      titleEn: 'Prolific paid online research participation',
      country: '글로벌 (한국은 공식 참여 국가 목록에 포함)',
      koreaStatus: 'CONFIRMED',
      participationMethod: 'Prolific 개인 계정 가입 후 계정 검증, 이후 발표된 연구에 직접 참여',
      reward: Object.freeze({
        displayValue: '연구별 상이 (보상액 미확인)',
        currency: null,
        basis: 'UNCONFIRMED' as const,
        confirmed: false,
      }),
      payer: 'Prolific (연구 스폰서)',
      qualifications: '만 18세 이상, 계정 검증 완료, 현재 거주 국가가 공식 참여 국가 목록에 포함 (한국 포함)',
      applyUrl: 'https://www.prolific.com/',
      sourceUrl: 'https://participant-help.prolific.com/en/articles/445007-who-can-participate-in-studies-on-prolific',
      verifiedAt: VERIFIED_AT,
      status: 'OPEN' as const,
      todayTier: 'IMMEDIATE' as const,
    }),
  ),
  Object.freeze(
    record({
      id: 'pub-outlier-ko-voice',
      sourceId: 'SRC-OUTLIER',
      vendor: 'Outlier',
      category: 'MICROTASK',
      titleKo: '한국어 Voice AI Evaluator (AI 음성 대화 평가)',
      titleEn: 'Korean Voice AI Evaluator — Up to $31/hr',
      country: 'South Korea (Remote)',
      koreaStatus: 'CONFIRMED',
      participationMethod: 'Outlier 계정 가입 → 본인·전화번호 인증 → 스킬 평가 통과 후 프로젝트 배정 (프리랜스 1099 계약 형태)',
      reward: Object.freeze({
        displayValue: '시급 최대 $31 (USD)',
        currency: 'USD',
        basis: 'HOURLY' as const,
        confirmed: true,
      }),
      payer: 'Outlier (주급, PayPal 또는 Airtm 지급)',
      qualifications: '한국어 유창 (읽기·쓰기·평가), 미스터리 서지 인센티브 +7.5% 가능, 대부분 주 5-10시간',
      applyUrl: 'https://app.outlier.ai/login?job_post_id=4722459005',
      sourceUrl: 'https://outlier.ai/languages/ko-kr',
      verifiedAt: VERIFIED_AT,
      status: 'OPEN' as const,
      todayTier: 'SCREENING_REQUIRED' as const,
    }),
  ),
  Object.freeze(
    record({
      id: 'pub-oneforma-local-search-korea',
      sourceId: 'SRC-ONEFORMA',
      vendor: 'OneForma',
      category: 'MICROTASK',
      titleKo: 'Local Search Quality Evaluator (한국 포함 6개국)',
      titleEn: 'Local Search Quality Evaluator',
      country: 'South Korea (China, Mexico, Norway, UK, US 포함 6개국)',
      koreaStatus: 'CONFIRMED',
      participationMethod: 'OneForma 무료 프로필 가입 → 프로젝트 지원 → 매칭 후 착수',
      reward: Object.freeze({
        displayValue: '시간당 지급 (금액 미확인)',
        currency: null,
        basis: 'HOURLY' as const,
        confirmed: false,
      }),
      payer: 'OneForma (Centific)',
      qualifications: '해당 지역 거주 5년 이상, 주 10시간, 검색 의도·사실관계 평가 기준 숙지',
      applyUrl: 'https://www.oneforma.com/jobs/',
      sourceUrl: 'https://www.oneforma.com/jobs/',
      verifiedAt: VERIFIED_AT,
      status: 'OPEN' as const,
      todayTier: 'SCREENING_REQUIRED' as const,
    }),
  ),
  Object.freeze(
    record({
      id: 'pub-oneforma-translation-rater-korea',
      sourceId: 'SRC-ONEFORMA',
      vendor: 'OneForma',
      category: 'MICROTASK',
      titleKo: 'Paragraph-Level Translation Quality Rater (한국 포함 30개국)',
      titleEn: 'Paragraph-Level Translation Quality Rater',
      country: 'South Korea (30개 나라 중 1)',
      koreaStatus: 'CONFIRMED',
      participationMethod: 'OneForma 무료 프로필 가입 → 프로젝트 지원 → 매칭 후 착수',
      reward: Object.freeze({
        displayValue: '승인 에셋당 지급 (금액 미확인)',
        currency: null,
        basis: 'PER_ASSET' as const,
        confirmed: false,
      }),
      payer: 'OneForma (Centific)',
      qualifications: '원어-번어 단락 품질 비교·수용성 판단, 원어 숙련도 필요, 일 2시간 규모',
      applyUrl: 'https://www.oneforma.com/jobs/',
      sourceUrl: 'https://www.oneforma.com/jobs/',
      verifiedAt: VERIFIED_AT,
      status: 'OPEN' as const,
      todayTier: 'SCREENING_REQUIRED' as const,
    }),
  ),
  Object.freeze(
    record({
      id: 'pub-dataannotation-korean',
      sourceId: 'SRC-DATAANNOTATION',
      vendor: 'DataAnnotation',
      category: 'MICROTASK',
      titleKo: 'DataAnnotation Korean Specialist (AI 학습 언어 스페셜리스트)',
      titleEn: 'Korean Specialist (Languages) — Up to $40/hr',
      country: '글로벌 (한국어 스페셜리스트 직군, 거주 요건 미확인)',
      koreaStatus: 'UNCONFIRMED',
      participationMethod: 'DataAnnotation 지원 → 자격 평가 통과 후 프로젝트 배정 (원격, 과제 기반 프리랜서)',
      reward: Object.freeze({
        displayValue: '시급 최대 $40 (USD)',
        currency: 'USD',
        basis: 'HOURLY' as const,
        confirmed: true,
      }),
      payer: 'DataAnnotation (지급 방식 미확인)',
      qualifications: '한국어 스페셜리스트 직군 (최근 69명 채용 표기), 추론·조심성·전문성 평가',
      applyUrl: 'https://dataannotation.tech/',
      sourceUrl: 'https://dataannotation.tech/',
      verifiedAt: VERIFIED_AT,
      status: 'OPEN' as const,
      todayTier: 'SCREENING_REQUIRED' as const,
    }),
  ),
  Object.freeze(
    record({
      id: 'pub-telus-korea-ai-community',
      sourceId: 'SRC-TELUS',
      vendor: 'TELUS Digital',
      category: 'SHORT_GIG',
      titleKo: 'TELUS Digital AI Community — 한국 원격 직무 (1건 공개)',
      titleEn: 'TELUS Digital AI Community — South Korea (1 open role)',
      country: 'South Korea (Remote)',
      koreaStatus: 'CONFIRMED',
      participationMethod: 'TELUS 채용 포털에서 한국 대상 직무 지원 (공개 1건, AI Community 카테고리)',
      reward: Object.freeze({
        displayValue: '미확인 (공고 조건 기준)',
        currency: null,
        basis: 'UNCONFIRMED' as const,
        confirmed: false,
      }),
      payer: 'TELUS Digital (원격 커뮤니티 직무)',
      qualifications: '공고별 자격 요건 (채용 포털에서 확인), 한국 지역 대상 원격',
      applyUrl: 'https://jobs.telusdigital.com/search/jobs/in/country/korea-republic-of',
      sourceUrl: 'https://jobs.telusdigital.com/search/jobs/in/country/korea-republic-of',
      verifiedAt: VERIFIED_AT,
      status: 'OPEN' as const,
      todayTier: 'SCREENING_REQUIRED' as const,
    }),
  ),
]);

export function loadVerifiedPublicOpportunities(): readonly PublicOpportunity[] {
  return VERIFIED_PUBLIC_OPPORTUNITIES;
}

export function publicOpportunityById(
  opportunities: readonly PublicOpportunity[],
  id: string,
): PublicOpportunity | null {
  return opportunities.find((item) => item.id === id) ?? null;
}
