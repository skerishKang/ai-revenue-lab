import test from 'node:test';
import assert from 'node:assert/strict';
import { OUTLIER_CURRENT_VERIFIED20_RECORD, OUTLIER_FINAL_GATES_V2 } from '../src/verified20/outlier-current.js';
import {
  OUTLIER_REAL_MATERIAL_CHANGE_CASE,
  OUTLIER_W8_CHANGE_V1_TO_V2,
  OUTLIER_W8_OPPORTUNITY_V2,
  OUTLIER_W8_SNAPSHOT_V2,
  OUTLIER_W8_V2_REVIEW_QUEUE,
  OUTLIER_W8_VERSION_V2,
} from '../src/verified20/outlier-material-change.js';
import { OUTLIER_W8_OPPORTUNITY, OUTLIER_W8_SNAPSHOT, OUTLIER_W8_VERSION } from '../src/verified20/outlier.js';
import { validateVerified20Record } from '../src/verified20/domain.js';
import { VERIFIED20_RECORDS, W8_GATE_STATUS } from '../src/verified20/ledger.js';
import { W8_NEGATIVE_DEMONSTRATIONS } from '../src/verified20/negative-demonstrations.js';

test('Outlier preserves stable opportunity identity while v1 and v2 remain immutable distinct versions', () => {
  assert.equal(OUTLIER_W8_OPPORTUNITY.id, OUTLIER_W8_OPPORTUNITY_V2.id);
  assert.equal(OUTLIER_W8_VERSION.versionNumber, 1);
  assert.equal(OUTLIER_W8_VERSION_V2.versionNumber, 2);
  assert.notEqual(OUTLIER_W8_VERSION.id, OUTLIER_W8_VERSION_V2.id);
  assert.notEqual(OUTLIER_W8_SNAPSHOT.id, OUTLIER_W8_SNAPSHOT_V2.id);
  assert.notEqual(OUTLIER_W8_SNAPSHOT.contentHash, OUTLIER_W8_SNAPSHOT_V2.contentHash);
  assert.equal(OUTLIER_W8_OPPORTUNITY.currentVersionId, OUTLIER_W8_VERSION.id);
  assert.equal(OUTLIER_W8_OPPORTUNITY_V2.currentVersionId, OUTLIER_W8_VERSION_V2.id);
});

test('real Outlier change row links v1 to v2 and is material', () => {
  assert.equal(OUTLIER_W8_CHANGE_V1_TO_V2.previousVersionId, OUTLIER_W8_VERSION.id);
  assert.equal(OUTLIER_W8_CHANGE_V1_TO_V2.newVersionId, OUTLIER_W8_VERSION_V2.id);
  assert.equal(OUTLIER_W8_CHANGE_V1_TO_V2.material, true);
  assert.equal(OUTLIER_W8_CHANGE_V1_TO_V2.changeType, 'ROLE_SCOPE_AND_TASK_SEMANTICS');
  assert.equal(OUTLIER_REAL_MATERIAL_CHANGE_CASE.disposition, 'NEW_VERSION_REVIEW_REQUIRED');
  assert.equal(OUTLIER_REAL_MATERIAL_CHANGE_CASE.countableVerified20, false);
});

test('v2 required critical material-change review before becoming current', () => {
  assert.equal(OUTLIER_W8_V2_REVIEW_QUEUE.priority, 'CRITICAL');
  assert.equal(OUTLIER_W8_V2_REVIEW_QUEUE.state, 'RESOLVED');
  assert.equal(OUTLIER_W8_V2_REVIEW_QUEUE.reasonCodes.includes('MATERIAL_CHANGE'), true);
  assert.equal(OUTLIER_FINAL_GATES_V2.find((gate) => gate.gate === 'change detection works')?.status, 'PASS');
  assert.equal(OUTLIER_FINAL_GATES_V2.find((gate) => gate.gate === 'human review accepted sample')?.status, 'PASS');
});

test('current Outlier v2 represents voice AI work without converting up-to rate into expected earnings', () => {
  const validation = validateVerified20Record(OUTLIER_CURRENT_VERIFIED20_RECORD);
  assert.equal(validation.countable, true, validation.errors.join('; '));
  assert.equal(OUTLIER_CURRENT_VERIFIED20_RECORD.slot, 2);
  assert.equal(OUTLIER_W8_VERSION_V2.title.includes('Voice AI Evaluator'), true);
  assert.equal(OUTLIER_W8_VERSION_V2.advertisedCompensationValue, 31);
  assert.equal(OUTLIER_W8_VERSION_V2.expectedPayoutValue, null);
  assert.equal(OUTLIER_W8_VERSION_V2.acceptanceProbability, null);
  const schedule = OUTLIER_W8_VERSION_V2.schedulingRequirements as { guaranteedHours?: unknown } | null;
  assert.equal(schedule?.guaranteedHours, null);
  assert.equal(OUTLIER_W8_VERSION_V2.skillRequirements?.includes('VOICE_OR_CONVERSATION_EVALUATION'), true);
});

test('ledger uses v2 as slot 2 and no longer uses the historical v1 record as current', () => {
  const slot2 = VERIFIED20_RECORDS.find((record) => record.slot === 2);
  assert.equal(slot2?.version.id, OUTLIER_W8_VERSION_V2.id);
  assert.notEqual(slot2?.version.id, OUTLIER_W8_VERSION.id);
});

test('real MATERIAL_VERSION_CHANGE demonstration remains PASS inside the accepted five-case W8 negative gate', () => {
  const material = W8_NEGATIVE_DEMONSTRATIONS.find((item) => item.id === 'MATERIAL_VERSION_CHANGE');
  assert.equal(material?.status, 'PASS');
  assert.equal(material?.evidenceRef, OUTLIER_REAL_MATERIAL_CHANGE_CASE.evidenceId);
  assert.equal(W8_GATE_STATUS.negativeDemonstrationsPassed, 5);
  assert.equal(W8_GATE_STATUS.negativeDemonstrationsTarget, 5);
  assert.equal(W8_GATE_STATUS.negativeDemonstrationsComplete, true);
  assert.equal(W8_GATE_STATUS.gatePassed, true);
});
