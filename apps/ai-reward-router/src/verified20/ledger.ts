import { verified20Progress } from './domain.js';
import { CROWDGEN_MOOGERAH_RECORD, CROWDGEN_PLUMERIA_RECORD } from './crowdgen.js';
import { w8NegativeGatePassed, W8_NEGATIVE_DEMONSTRATIONS } from './negative-demonstrations.js';
import { ONEFORMA_EXTRA_VERIFIED20_RECORDS } from './oneforma-extra.js';
import { ONEFORMA_VERIFIED20_RECORDS } from './oneforma.js';
import { OUTLIER_VERIFIED20_RECORD } from './outlier.js';
import { PROLIFIC_VERIFIED20_RECORD } from './prolific.js';

export const VERIFIED20_RECORDS = Object.freeze([
  PROLIFIC_VERIFIED20_RECORD,
  OUTLIER_VERIFIED20_RECORD,
  CROWDGEN_MOOGERAH_RECORD,
  CROWDGEN_PLUMERIA_RECORD,
  ...ONEFORMA_VERIFIED20_RECORDS,
  ...ONEFORMA_EXTRA_VERIFIED20_RECORDS,
]);

export const VERIFIED20_PROGRESS = verified20Progress(VERIFIED20_RECORDS);

export const W8_GATE_STATUS = Object.freeze({
  realVerifiedCount: VERIFIED20_PROGRESS.verifiedCount,
  targetCount: VERIFIED20_PROGRESS.targetCount,
  remainingCount: VERIFIED20_PROGRESS.remainingCount,
  verified20Complete: VERIFIED20_PROGRESS.gatePassed,
  negativeDemonstrationsComplete: w8NegativeGatePassed(W8_NEGATIVE_DEMONSTRATIONS),
  gatePassed: VERIFIED20_PROGRESS.gatePassed && w8NegativeGatePassed(W8_NEGATIVE_DEMONSTRATIONS),
});
