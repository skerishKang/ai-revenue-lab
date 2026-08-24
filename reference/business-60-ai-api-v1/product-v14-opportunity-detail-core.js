(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.B60_OPPORTUNITY_DETAIL_CORE = Object.freeze(api);
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const AUTHORITATIVE_EXPIRY = new Set(['VERIFIED_OFFICIAL_WEB', 'VERIFIED_OFFICIAL_SOCIAL']);
  const MECHANIC_LABELS = Object.freeze({
    TEMP_FREE_ACCESS: '한시 무료 개방',
    SIGNUP_CREDIT: '가입 크레딧',
    RECURRING_FREE: '반복 무료',
    ALWAYS_FREE: '상시 무료'
  });
  const ELIGIBILITY_LABELS = Object.freeze({
    ANY_USER: '누구나',
    NEW_USER_ONLY: '신규 사용자 전용',
    ACCOUNT_REQUIRED: '계정 필요',
    UNKNOWN: '자격 조건 확인 필요'
  });
  const SOURCE_AUTHORITY_LABELS = Object.freeze({
    OFFICIAL_WEB: '공식 웹',
    VERIFIED_OFFICIAL_WEB: '공식 웹',
    OFFICIAL_SOCIAL: '공식 발표',
    VERIFIED_OFFICIAL_SOCIAL: '공식 발표',
    OFFICIAL_GITHUB: '공식 GitHub',
    PARTNER: '공식 파트너',
    COMMUNITY: '커뮤니티 출처'
  });

  const pad = value => String(value).padStart(2, '0');

  function toSeoulDayKey(now = new Date()) {
    const date = now instanceof Date ? now : new Date(now);
    if (Number.isNaN(date.getTime())) return '';
    return new Intl.DateTimeFormat('sv-SE', {
      timeZone: 'Asia/Seoul',
      year: 'numeric', month: '2-digit', day: '2-digit'
    }).format(date);
  }

  function formatDate(dateString) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(dateString || ''))) return '';
    const [year, month, day] = dateString.split('-');
    return `${year}.${pad(month)}.${pad(day)}`;
  }

  function daysUntil(dateString, now = new Date()) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(dateString || ''))) return null;
    const todayKey = toSeoulDayKey(now);
    if (!todayKey) return null;
    const end = Date.parse(`${dateString}T00:00:00Z`);
    const today = Date.parse(`${todayKey}T00:00:00Z`);
    if (Number.isNaN(end) || Number.isNaN(today)) return null;
    return Math.ceil((end - today) / 86400000);
  }

  function isAuthoritativeExpiry(item) {
    return AUTHORITATIVE_EXPIRY.has(item && item.expiryVerification);
  }

  function expiryLabel(item, now = new Date()) {
    if (!item) return '기간 정보 없음';
    if (item.expiresAt) {
      if (!isAuthoritativeExpiry(item)) return '종료일 주장 확인 중';
      const days = daysUntil(item.expiresAt, now);
      const formatted = formatDate(item.expiresAt) || item.expiresAt;
      if (days === null) return `${formatted}까지`;
      if (days < 0) return `종료됨 · ${formatted}`;
      if (days === 0) return `오늘 종료 · ${formatted}`;
      if (days <= 7) return `${formatted}까지 · ${days}일 남음`;
      return `${formatted}까지`;
    }
    if (item.opportunityType === 'TEMP_FREE_ACCESS') return '기간 한정 · 종료일 공식 미공개';
    if (item.opportunityType === 'SIGNUP_CREDIT') return item.planWindow || '공식 고정 종료일 미표기';
    if (item.opportunityType === 'RECURRING_FREE') return '반복 제공 · 종료일 공식 미표기';
    return '상시 접근 · 종료일 없음';
  }

  function mechanicLabel(item) {
    return MECHANIC_LABELS[item && item.opportunityType] || '무료 기회';
  }

  function eligibilityLabel(item) {
    return ELIGIBILITY_LABELS[item && item.eligibility] || ELIGIBILITY_LABELS.UNKNOWN;
  }

  function sourceAuthorityLabel(authority) {
    return SOURCE_AUTHORITY_LABELS[authority] || '출처';
  }

  function verificationLabel(item) {
    if (!item) return '검토 필요';
    if (item.verification === 'VERIFIED_OFFICIAL_WEB') return '공식 웹 확인';
    if (item.verification === 'VERIFIED_OFFICIAL_SOCIAL') return '공식 발표 확인';
    return '검토 필요';
  }

  function normalizeUrl(value) {
    try {
      const url = new URL(String(value || ''));
      url.hash = '';
      return url.toString().replace(/\/$/, '');
    } catch {
      return String(value || '').trim().replace(/\/$/, '');
    }
  }

  function resolveOpportunityByUrl(opportunities, url) {
    const needle = normalizeUrl(url);
    if (!needle) return null;
    return (opportunities || []).find(item => {
      if (normalizeUrl(item.ctaUrl) === needle) return true;
      return (item.sources || []).some(source => normalizeUrl(source.url) === needle);
    }) || null;
  }

  function getOpportunityById(opportunities, id) {
    return (opportunities || []).find(item => item && item.id === id) || null;
  }

  function buildDealLink(href, id) {
    const url = new URL(href);
    url.searchParams.set('deal', id);
    return url.toString();
  }

  function clearDealLink(href) {
    const url = new URL(href);
    url.searchParams.delete('deal');
    return url.toString();
  }

  function viewModel(item, now = new Date()) {
    if (!item) return null;
    const sources = (item.sources || []).map(source => ({
      label: source.label || '공식 출처',
      url: source.url || '#',
      authority: source.authority || '',
      authorityLabel: sourceAuthorityLabel(source.authority)
    }));
    return Object.freeze({
      id: item.id,
      provider: item.provider || '제공사 미표기',
      productOrModel: item.productOrModel || item.title || '',
      headline: item.headline || item.title || item.provider || '무료 기회',
      benefit: item.benefitLabel || item.priceOrCredit || '무료',
      summary: item.summary || '',
      mechanic: mechanicLabel(item),
      eligibility: eligibilityLabel(item),
      expiry: expiryLabel(item, now),
      start: item.startAt ? formatDate(item.startAt) : '시작일 공식 미표기',
      priceOrCredit: item.priceOrCredit || item.benefitLabel || '무료',
      limit: item.limit || '공식 제한 정보 별도 확인',
      access: Array.from(item.access || []),
      conditions: Array.from(item.conditions || []),
      verification: verificationLabel(item),
      verifiedAt: item.verifiedAt || '날짜 미확인',
      ctaUrl: item.ctaUrl || (sources[0] && sources[0].url) || '#',
      sources
    });
  }

  return {
    AUTHORITATIVE_EXPIRY,
    MECHANIC_LABELS,
    ELIGIBILITY_LABELS,
    SOURCE_AUTHORITY_LABELS,
    daysUntil,
    expiryLabel,
    mechanicLabel,
    eligibilityLabel,
    sourceAuthorityLabel,
    verificationLabel,
    resolveOpportunityByUrl,
    getOpportunityById,
    buildDealLink,
    clearDealLink,
    viewModel
  };
});
