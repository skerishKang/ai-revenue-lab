import { verified20Progress } from './domain.js';
import { CROWDGEN_MOOGERAH_RECORD, CROWDGEN_PLUMERIA_RECORD } from './crowdgen.js';
import { CROWDGEN_MORAVA_RECORD } from './crowdgen-morava.js';
import { CROWDGEN_VISTULA_RECORD } from './crowdgen-vistula.js';
import {
  GOOGLE_OPINION_REWARDS_KR_RECORD,
  IPSOS_ISAY_KR_RECORD,
  PANELPOWER_AIRDRESSER_RECORD,
  PANELPOWER_PROGRAM_RECORD,
  RAKUTEN_INSIGHT_KR_RECORD,
} from './korean-pocket-money.js';
import { PANELPOWER_REALTOR_FOCUS_GROUP_RECORD } from './panelpower-realtor.js';
import { w8NegativeGatePassed, W8_NEGATIVE_DEMONSTRATIONS } from './negative-demonstrations.js';
import { ONEFORMA_EXTRA_VERIFIED20_RECORDS } from './oneforma-extra.js';
import { ONEFORMA_VERIFIED20_RECORDS } from './oneforma.js';
import { OUTLIER_CURRENT_VERIFIED20_RECORD } from './outlier-current.js';
import { PROLIFIC_VERIFIED20_RECORD } from './prolific.js';

export const VERIFIED20_RECORDS = Object.freeze([
  PROLIFIC_VERIFIED20_RECORD,
  OUTLIER_CURRENT_VERIFIED20_RECORD,
  CROWDGEN_MOOGERAH_RECORD,
  CROWDGEN_PLUMERIA_RECORD,
  ...ONEFORMA_VERIFIED20_RECORDS,
  ...ONEFORMA_EXTRA_VERIFIED20_RECORDS,
  CROWDGEN_VISTULA_RECORD,
  CROWDGEN_MORAVA_RECORD,
  RAKUTEN_INSIGHT_KR_RECORD,
  PANELPOWER_PROGRAM_RECORD,
  IPSOS_ISAY_KR_RECORD,
  PANELPOWER_REALTOR_FOCUS_GROUP_RECORD,
  GOOGLE_OPINION_REWARDS_KR_RECORD,
  PANELPOWER_AIRDRESSER_RECORD,
]);

export const VERIFIED20_PROGRESS = verified20Progress(VERIFIED20_RECORDS);

export const W8_GATE_STATUS = Object.freeze({
  realVerifiedCount: VERIFIED20_PROGRESS.verifiedCount,
  targetCount: VERIFIED20_PROGRESS.targetCount,
  remainingCount: VERIFIED20_PROGRESS.remainingCount,
  verified20Complete: VERIFIED20_PROGRESS.gatePassed,
  negativeDemonstrationsComplete: w8NegativeGatePassed(W8_NEGATIVE_DEMONSTRATIONS),
  negativeDemonstrationsPassed: W8_NEGATIVE_DEMONSTRATIONS.filter((item) => item.status === 'PASS').length,
  negativeDemonstrationsTarget: W8_NEGATIVE_DEMONSTRATIONS.length,
  gatePassed: VERIFIED20_PROGRESS.gatePassed && w8NegativeGatePassed(W8_NEGATIVE_DEMONSTRATIONS),
});
