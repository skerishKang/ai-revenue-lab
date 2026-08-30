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

/** Mirrors PHP ksort(..., SORT_STRING) + http_build_query(..., '', '&') for scalar callback parameters. */
export function canonicalAyetS2SParameterString(parameters: AyetS2SParameters): string {
  return Object.entries(parameters)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${phpUrlencode(key)}=${phpUrlencode(String(value))}`)
    .join('&');
}

export function expectedAyetS2SSecurityHash(parameters: AyetS2SParameters, publisherApiKey: string): string {
  return createHmac('sha256', publisherApiKey)
    .update(canonicalAyetS2SParameterString(parameters), 'utf8')
    .digest('hex');
}

export function verifyAyetS2SSecurityHash(
  parameters: AyetS2SParameters,
  providedSecurityHash: string,
  publisherApiKey: string,
): boolean {
  if (!publisherApiKey || !/^[0-9a-f]{64}$/i.test(providedSecurityHash)) return false;
  const expected = expectedAyetS2SSecurityHash(parameters, publisherApiKey);
  const actualBuffer = Buffer.from(providedSecurityHash.toLowerCase(), 'hex');
  const expectedBuffer = Buffer.from(expected, 'hex');
  return actualBuffer.length === expectedBuffer.length && timingSafeEqual(actualBuffer, expectedBuffer);
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
  const isChargeback = callbackType === 'chargeback' || isChargebackFlag === '1';
  const isConversion = callbackType === 'conversion' && isChargebackFlag !== '1';
  if (!isChargeback && !isConversion) {
    return Object.freeze({ accepted: false, decision: 'REJECT_INVALID_CALLBACK_TYPE' as const, rewardEvent: null });
  }

  if (isChargeback && callbackType !== 'chargeback' && callbackType !== 'conversion') {
    return Object.freeze({ accepted: false, decision: 'REJECT_INVALID_CALLBACK_TYPE' as const, rewardEvent: null });
  }

  const rawTransactionId = stringParam(input.parameters, 'transaction_id');
  const externalUserId = stringParam(input.parameters, 'external_identifier');
  const currencyIdentifier = stringParam(input.parameters, 'currency_identifier') || 'AYET_REWARD_UNIT';
  const rawCurrencyAmount = Number(stringParam(input.parameters, 'currency_amount'));
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
