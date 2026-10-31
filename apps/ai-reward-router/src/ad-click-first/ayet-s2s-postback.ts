import { createHmac, timingSafeEqual } from 'node:crypto';
import type { ProviderRewardEvent } from './reward-events.js';

export type AyetS2SParameters = Readonly<Record<string, string | number>>;

export interface AyetS2SNormalizationResult {
  readonly accepted: boolean;
  readonly decision:
    | 'ACCEPT_CONFIRMED_REWARD'
    | 'ACCEPT_REVERSAL'
    | 'REJECT_INVALID_SIGNATURE'
    | 'REJECT_INVALID_CALLBACK_TYPE'
    | 'REJECT_INVALID_FIELDS';
  readonly rewardEvent: ProviderRewardEvent | null;
}

function phpUrlencode(value: string): string {
  return encodeURIComponent(value)
    .replace(/%20/g, '+')
    .replace(/[!'()*~]/g, (char) => `%${char.charCodeAt(0).toString(16).toUpperCase()}`);
}

/**
 * The two canonical strings ayeT's own documentation shows for the same job.
 *
 * The PHP reference (`ksort(..., SORT_STRING)` + `http_build_query`) escapes
 * `*` as `%2A`; the JavaScript reference (`new URLSearchParams(...).toString()`)
 * leaves `*` alone. Every other character — space to `+`, `!` `'` `(` `)` `~`,
 * `%`, `/`, `-`, `.`, `_` — encodes identically in both, measured rather than
 * assumed. A publisher cannot know which one the sending server used, and a
 * mismatch costs a real reward, so both are accepted. The API key is secret
 * either way, so accepting the provider's own two documented recipes widens no
 * authority.
 */
export type AyetS2SCanonicalization = 'php' | 'urlsearchparams';

function urlSearchParamsEncode(value: string): string {
  return new URLSearchParams({ k: value }).toString().slice(2);
}

function canonicalEntries(parameters: AyetS2SParameters): Array<readonly [string, string]> {
  return Object.entries(parameters)
    .map(([key, value]) => [key, String(value)] as const)
    .sort(([left], [right]) => left.localeCompare(right));
}

export function canonicalAyetS2SParameterString(
  parameters: AyetS2SParameters,
  style: AyetS2SCanonicalization = 'php',
): string {
  return canonicalEntries(parameters)
    .map(([key, value]) => `${style === 'php' ? phpUrlencode(key) : urlSearchParamsEncode(key)}=${style === 'php' ? phpUrlencode(value) : urlSearchParamsEncode(value)}`)
    .join('&');
}

export function expectedAyetS2SSecurityHash(
  parameters: AyetS2SParameters,
  publisherApiKey: string,
  style: AyetS2SCanonicalization = 'php',
): string {
  return createHmac('sha256', publisherApiKey)
    .update(canonicalAyetS2SParameterString(parameters, style), 'utf8')
    .digest('hex');
}

function hashMatches(providedSecurityHash: string, expected: string): boolean {
  const actualBuffer = Buffer.from(providedSecurityHash.toLowerCase(), 'hex');
  const expectedBuffer = Buffer.from(expected, 'hex');
  return actualBuffer.length === expectedBuffer.length && timingSafeEqual(actualBuffer, expectedBuffer);
}

export function verifyAyetS2SSecurityHash(
  parameters: AyetS2SParameters,
  providedSecurityHash: string,
  publisherApiKey: string,
): boolean {
  if (!publisherApiKey || !/^[0-9a-f]{64}$/i.test(providedSecurityHash)) return false;
  return hashMatches(providedSecurityHash, expectedAyetS2SSecurityHash(parameters, publisherApiKey, 'php'))
    || hashMatches(providedSecurityHash, expectedAyetS2SSecurityHash(parameters, publisherApiKey, 'urlsearchparams'));
}

function stringParam(parameters: AyetS2SParameters, key: string): string {
  const value = parameters[key];
  return value === undefined ? '' : String(value).trim();
}

function normalizeOriginalTransactionId(transactionId: string, isChargeback: boolean): string {
  if (!isChargeback) return transactionId;
  return transactionId.startsWith('r-') ? transactionId.slice(2) : transactionId;
}

export function normalizeVerifiedAyetS2SRewardPostback(input: {
  readonly parameters: AyetS2SParameters;
  readonly securityHash: string;
  readonly publisherApiKey: string;
  readonly observedAt: string;
}): AyetS2SNormalizationResult {
  if (!verifyAyetS2SSecurityHash(input.parameters, input.securityHash, input.publisherApiKey)) {
    return Object.freeze({ accepted: false, decision: 'REJECT_INVALID_SIGNATURE' as const, rewardEvent: null });
  }

  const callbackType = stringParam(input.parameters, 'callback_type');
  const isChargebackFlag = stringParam(input.parameters, 'is_chargeback');
  const rawCurrencyAmount = Number(stringParam(input.parameters, 'currency_amount'));
  const isChargeback = callbackType === 'chargeback' || isChargebackFlag === '1';
  // The rewarded-video callback macro table does not list callback_type, so a
  // callback carrying only the documented amount and chargeback fields is
  // classified from those. An explicit callback_type still decides, and the
  // non-reward types ayeT documents for other integrations (installation, iap,
  // iaa, optional, survey) stay refused.
  const isConversion = !isChargeback
    && (callbackType === 'conversion'
      || (callbackType === '' && Number.isFinite(rawCurrencyAmount) && rawCurrencyAmount > 0));
  if (!isChargeback && !isConversion) {
    return Object.freeze({ accepted: false, decision: 'REJECT_INVALID_CALLBACK_TYPE' as const, rewardEvent: null });
  }

  if (isChargeback && callbackType !== 'chargeback' && callbackType !== 'conversion' && callbackType !== '') {
    return Object.freeze({ accepted: false, decision: 'REJECT_INVALID_CALLBACK_TYPE' as const, rewardEvent: null });
  }

  const rawTransactionId = stringParam(input.parameters, 'transaction_id');
  const externalUserId = stringParam(input.parameters, 'external_identifier');
  const currencyIdentifier = stringParam(input.parameters, 'currency_identifier') || 'AYET_REWARD_UNIT';
  const originalTransactionId = normalizeOriginalTransactionId(rawTransactionId, isChargeback);
  const observedAtValid = Number.isFinite(Date.parse(input.observedAt));

  if (!rawTransactionId || !originalTransactionId || !externalUserId || !Number.isFinite(rawCurrencyAmount) || rawCurrencyAmount === 0 || !observedAtValid) {
    return Object.freeze({ accepted: false, decision: 'REJECT_INVALID_FIELDS' as const, rewardEvent: null });
  }

  if (isChargeback && rawCurrencyAmount >= 0) {
    return Object.freeze({ accepted: false, decision: 'REJECT_INVALID_FIELDS' as const, rewardEvent: null });
  }
  if (isConversion && rawCurrencyAmount <= 0) {
    return Object.freeze({ accepted: false, decision: 'REJECT_INVALID_FIELDS' as const, rewardEvent: null });
  }

  const rewardEvent: ProviderRewardEvent = Object.freeze({
    providerId: 'SRC-AYET',
    providerTransactionId: originalTransactionId,
    externalUserId,
    eventType: isChargeback ? 'REVERSED' : 'CONFIRMED',
    amount: Math.abs(rawCurrencyAmount),
    unit: currencyIdentifier,
    observedAt: input.observedAt,
  });

  return Object.freeze({
    accepted: true,
    decision: isChargeback ? 'ACCEPT_REVERSAL' as const : 'ACCEPT_CONFIRMED_REWARD' as const,
    rewardEvent,
  });
}
