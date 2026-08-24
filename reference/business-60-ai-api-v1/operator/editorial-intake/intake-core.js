(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.B60EditorialIntake = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const OPPORTUNITY_TYPES = Object.freeze([
    'TEMP_FREE_ACCESS',
    'SIGNUP_CREDIT',
    'RECURRING_FREE',
    'ALWAYS_FREE'
  ]);
  const EDITORIAL_ROLES = Object.freeze(['HOTTEST', 'JUST_DROPPED', 'STANDARD', 'REFERENCE']);
  const ELIGIBILITY = Object.freeze(['ANY_USER', 'NEW_USER_ONLY', 'ACCOUNT_REQUIRED', 'UNKNOWN']);
  const VERIFICATION = Object.freeze(['VERIFIED_OFFICIAL_WEB', 'VERIFIED_OFFICIAL_SOCIAL', 'PENDING_VERIFICATION']);
  const SOURCE_AUTHORITY = Object.freeze(['OFFICIAL_WEB', 'OFFICIAL_SOCIAL', 'OFFICIAL_GITHUB', 'PARTNER', 'COMMUNITY_SOCIAL']);
  const AUTHORITATIVE_EXPIRY = new Set(['VERIFIED_OFFICIAL_WEB', 'VERIFIED_OFFICIAL_SOCIAL']);

  const clean = value => String(value == null ? '' : value).trim();
  const cleanNullable = value => clean(value) || null;
  const list = value => Array.from(new Set(String(value || '')
    .split(/[\n,]+/)
    .map(item => item.trim())
    .filter(Boolean)));

  function isHttpUrl(value) {
    try {
      const url = new URL(clean(value));
      return url.protocol === 'http:' || url.protocol === 'https:';
    } catch (_) {
      return false;
    }
  }

  function slugify(value) {
    return clean(value)
      .toLowerCase()
      .normalize('NFKD')
      .replace(/[^a-z0-9가-힣]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 72);
  }

  function todayKey(date = new Date()) {
    return new Intl.DateTimeFormat('sv-SE', {
      timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit'
    }).format(date);
  }

  function kstTimestamp(date = new Date()) {
    const parts = new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'
    }).formatToParts(date).reduce((acc, part) => {
      acc[part.type] = part.value;
      return acc;
    }, {});
    return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}+09:00`;
  }

  function normalizeDraft(raw = {}, now = new Date()) {
    const provider = clean(raw.provider);
    const productOrModel = clean(raw.productOrModel);
    const id = clean(raw.id) || slugify(`${provider}-${productOrModel || raw.headline || raw.title}`);
    const verification = VERIFICATION.includes(raw.verification) ? raw.verification : 'PENDING_VERIFICATION';
    const sourceAuthority = SOURCE_AUTHORITY.includes(raw.sourceAuthority) ? raw.sourceAuthority : '';
    const opportunityType = OPPORTUNITY_TYPES.includes(raw.opportunityType) ? raw.opportunityType : '';
    const editorialRole = EDITORIAL_ROLES.includes(raw.editorialRole) ? raw.editorialRole : 'STANDARD';
    const eligibility = ELIGIBILITY.includes(raw.eligibility) ? raw.eligibility : 'UNKNOWN';

    return {
      id,
      editorialRole,
      opportunityType,
      eligibility,
      provider,
      title: clean(raw.title) || productOrModel || clean(raw.headline),
      headline: clean(raw.headline),
      benefitLabel: clean(raw.benefitLabel),
      summary: clean(raw.summary),
      productOrModel,
      categories: list(raw.categories),
      access: list(raw.access),
      priceOrCredit: cleanNullable(raw.priceOrCredit),
      limit: cleanNullable(raw.limit),
      recurrence: opportunityType === 'RECURRING_FREE' ? {
        cadence: cleanNullable(raw.recurrenceCadence),
        label: cleanNullable(raw.recurrenceLabel) || cleanNullable(raw.benefitLabel),
        resetRule: cleanNullable(raw.resetRule)
      } : null,
      startAt: cleanNullable(raw.startAt),
      expiresAt: cleanNullable(raw.expiresAt),
      expiryVerification: AUTHORITATIVE_EXPIRY.has(raw.expiryVerification) ? raw.expiryVerification : null,
      conditions: list(raw.conditions),
      ctaUrl: clean(raw.ctaUrl),
      observedAt: clean(raw.observedAt) || kstTimestamp(now),
      verifiedAt: clean(raw.verifiedAt) || todayKey(now),
      verification,
      sources: [{
        label: clean(raw.sourceLabel),
        url: clean(raw.sourceUrl),
        authority: sourceAuthority
      }],
      mediaDraft: {
        image: cleanNullable(raw.image),
        alt: cleanNullable(raw.imageAlt),
        source: cleanNullable(raw.imageSource),
        credit: cleanNullable(raw.imageCredit),
        sourcePage: cleanNullable(raw.imageSourcePage)
      }
    };
  }

  function dateOrder(a, b) {
    if (!a || !b) return null;
    const left = Date.parse(`${a}T00:00:00Z`);
    const right = Date.parse(`${b}T00:00:00Z`);
    if (Number.isNaN(left) || Number.isNaN(right)) return null;
    return Math.sign(left - right);
  }

  function validateDraft(raw = {}, now = new Date()) {
    const draft = normalizeDraft(raw, now);
    const errors = [];
    const warnings = [];
    const pending = [];

    const requiredText = [
      ['provider', '제공자'],
      ['productOrModel', '제품/모델'],
      ['headline', '헤드라인'],
      ['benefitLabel', '혜택'],
      ['summary', '요약'],
      ['opportunityType', '혜택 유형'],
      ['ctaUrl', '사용/신청 URL']
    ];
    requiredText.forEach(([key, label]) => {
      if (!draft[key]) errors.push({ code: `MISSING_${key.toUpperCase()}`, message: `${label}이 필요합니다.` });
    });

    if (!draft.id) errors.push({ code: 'MISSING_ID', message: '안정적인 id를 만들 수 없습니다.' });
    if (!isHttpUrl(draft.ctaUrl)) errors.push({ code: 'INVALID_CTA_URL', message: '사용/신청 URL은 http(s) 주소여야 합니다.' });
    if (!draft.sources[0].label) errors.push({ code: 'MISSING_SOURCE_LABEL', message: '출처 이름이 필요합니다.' });
    if (!isHttpUrl(draft.sources[0].url)) errors.push({ code: 'INVALID_SOURCE_URL', message: '출처 URL은 http(s) 주소여야 합니다.' });
    if (!draft.sources[0].authority) errors.push({ code: 'MISSING_SOURCE_AUTHORITY', message: '출처 권위를 선택해야 합니다.' });

    if (!OPPORTUNITY_TYPES.includes(draft.opportunityType)) {
      errors.push({ code: 'INVALID_OPPORTUNITY_TYPE', message: '정의된 무료 혜택 유형을 선택해야 합니다.' });
    }

    if (draft.verification === 'PENDING_VERIFICATION') {
      pending.push({ code: 'PENDING_VERIFICATION', message: '핵심 혜택이 아직 공식 확인 상태가 아닙니다.' });
    }

    if (draft.expiresAt && !draft.expiryVerification) {
      pending.push({ code: 'UNVERIFIED_EXPIRY', message: '종료일은 입력됐지만 종료일의 공식 검증 근거가 없습니다. 종료 임박/카운트다운으로 사용할 수 없습니다.' });
    }

    if (dateOrder(draft.startAt, draft.expiresAt) === 1) {
      errors.push({ code: 'DATE_ORDER', message: '시작일이 종료일보다 늦습니다.' });
    }

    if (draft.opportunityType === 'SIGNUP_CREDIT' && draft.editorialRole === 'HOTTEST') {
      pending.push({ code: 'SIGNUP_HOTTEST_EXCEPTION', message: '가입 크레딧을 HOTTEST로 올리려면 별도의 편집상 예외 판단이 필요합니다.' });
    }

    if (draft.opportunityType === 'SIGNUP_CREDIT' && draft.eligibility === 'ANY_USER') {
      warnings.push({ code: 'SIGNUP_ELIGIBILITY_RECHECK', message: '가입 크레딧인데 ANY_USER입니다. 신규/계정 조건을 다시 확인하세요.' });
    }

    if (draft.opportunityType === 'RECURRING_FREE') {
      if (!draft.recurrence || !draft.recurrence.cadence) {
        errors.push({ code: 'MISSING_RECURRENCE_CADENCE', message: '반복 무료는 리필 주기(cadence)가 필요합니다.' });
      }
      if (!draft.recurrence || !draft.recurrence.label) {
        errors.push({ code: 'MISSING_RECURRENCE_LABEL', message: '반복 무료는 반복 혜택 표시값이 필요합니다.' });
      }
      if (!draft.recurrence?.resetRule) {
        warnings.push({ code: 'UNKNOWN_RESET_RULE', message: '정확한 리셋 시각/규칙이 공식 확인되지 않았다면 비워 두어도 됩니다. 임의로 만들지 마세요.' });
      }
    }

    if (!draft.categories.length) warnings.push({ code: 'NO_CATEGORIES', message: '검색/필터용 카테고리를 하나 이상 권장합니다.' });
    if (!draft.access.length) warnings.push({ code: 'NO_ACCESS', message: '실제 접근 경로를 하나 이상 권장합니다.' });
    if (!draft.conditions.length) warnings.push({ code: 'NO_CONDITIONS', message: '계정/카드/지역/사용량 조건을 확인해 기록하는 것을 권장합니다.' });

    const hasImage = Boolean(draft.mediaDraft.image);
    const hasImageProvenance = Boolean(draft.mediaDraft.source && draft.mediaDraft.credit && draft.mediaDraft.sourcePage);
    if (hasImage && !hasImageProvenance) {
      warnings.push({ code: 'IMAGE_PROVENANCE_INCOMPLETE', message: '이미지를 쓰려면 source/credit/sourcePage를 함께 기록하세요.' });
    }

    const today = todayKey(now);
    const isExpired = Boolean(draft.expiresAt && dateOrder(draft.expiresAt, today) === -1);
    let disposition;
    if (isExpired) disposition = 'EXPIRED';
    else if (errors.length || pending.length) disposition = 'PENDING_VERIFICATION';
    else if (draft.opportunityType === 'SIGNUP_CREDIT') disposition = 'PUBLISH_SIGNUP_BENEFIT';
    else if (draft.opportunityType === 'ALWAYS_FREE' || draft.opportunityType === 'RECURRING_FREE') disposition = 'PUBLISH_ALWAYS_FREE';
    else disposition = 'PUBLISH_NOW';

    const verdict = errors.length ? 'BLOCKED' : pending.length ? 'PENDING' : 'READY';
    return {
      verdict,
      disposition,
      errors,
      pending,
      warnings,
      urgencyEligible: Boolean(draft.expiresAt && draft.expiryVerification && !isExpired),
      candidate: draft
    };
  }

  function opportunityRecord(candidate) {
    const c = candidate.candidate || candidate;
    const record = {
      id: c.id,
      editorialRole: c.editorialRole,
      opportunityType: c.opportunityType,
      eligibility: c.eligibility,
      provider: c.provider,
      title: c.title,
      headline: c.headline,
      benefitLabel: c.benefitLabel,
      summary: c.summary,
      productOrModel: c.productOrModel,
      categories: c.categories,
      access: c.access,
      priceOrCredit: c.priceOrCredit,
      limit: c.limit,
      startAt: c.startAt,
      expiresAt: c.expiresAt,
      expiryVerification: c.expiryVerification,
      conditions: c.conditions,
      ctaUrl: c.ctaUrl,
      observedAt: c.observedAt,
      verifiedAt: c.verifiedAt,
      verification: c.verification,
      sources: c.sources
    };
    if (c.recurrence) record.recurrence = c.recurrence;
    return record;
  }

  function mediaRecord(candidate) {
    const c = candidate.candidate || candidate;
    if (!c.mediaDraft?.image) return null;
    return {
      id: c.id,
      image: c.mediaDraft.image,
      alt: c.mediaDraft.alt,
      source: c.mediaDraft.source,
      credit: c.mediaDraft.credit,
      sourcePage: c.mediaDraft.sourcePage
    };
  }

  function stringifyJs(value, indent = 2) {
    return JSON.stringify(value, null, indent)
      .replace(/"([A-Za-z_$][A-Za-z0-9_$]*)":/g, '$1:')
      .replace(/"([^"\\]*(?:\\.[^"\\]*)*)"/g, function (match, inner) {
        const decoded = JSON.parse(match);
        return `'${decoded.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\n/g, '\\n')}'`;
      });
  }

  function buildOutputs(raw = {}, now = new Date()) {
    const validation = validateDraft(raw, now);
    const opportunity = opportunityRecord(validation.candidate);
    const media = mediaRecord(validation.candidate);
    return {
      validation,
      json: JSON.stringify({ opportunity, media }, null, 2),
      opportunityJs: stringifyJs(opportunity),
      mediaJs: media ? stringifyJs(media) : ''
    };
  }

  return Object.freeze({
    OPPORTUNITY_TYPES,
    EDITORIAL_ROLES,
    ELIGIBILITY,
    VERIFICATION,
    SOURCE_AUTHORITY,
    list,
    slugify,
    todayKey,
    kstTimestamp,
    normalizeDraft,
    validateDraft,
    opportunityRecord,
    mediaRecord,
    buildOutputs
  });
});
