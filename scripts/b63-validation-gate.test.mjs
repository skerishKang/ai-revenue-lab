import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import { evaluateB63Validation } from './b63-validation-gate.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const CONFIG_PATH = resolve(HERE, '../docs/experiments/b63/validation-gates.json');
const config = JSON.parse(await readFile(CONFIG_PATH, 'utf8'));

function interview(id, organizationType = 'hospital', overrides = {}) {
  return {
    id,
    organization_type: organizationType,
    problem_severity: 2,
    clinical_domain_gap: 2,
    budget_owner: 2,
    deployment_feasibility: 2,
    poc_intent: 2,
    poc_path: 'paid',
    ...overrides,
  };
}

function customer(interviews) {
  return {
    schema_version: 'b63.customer-discovery.v1',
    business: { number: 63, status: 'proposed' },
    interviews,
  };
}

function strongCustomer() {
  return customer([
    interview('h1'),
    interview('h2'),
    interview('h3'),
    interview('v1', 'his_vendor'),
    interview('v2', 'his_vendor'),
  ]);
}

function r0(overrides = {}) {
  return {
    schema_version: 'b63.r0-result.v1',
    business: { number: 63, status: 'proposed' },
    dataset: {
      real_patient_data_used: false,
      synthetic_public_only: true,
      synthetic_identifier_collision_safe: true,
      base_cases: 130,
      ...(overrides.dataset ?? {}),
    },
    systems: {
      s0_ipu_current: true,
      s1_generic_pii_baseline: true,
      s2_clinical_baseline: false,
      s3_b63_hybrid_r0: true,
      ...(overrides.systems ?? {}),
    },
    tests: {
      passed: true,
      changed_file_secret_scan_passed: true,
      synthetic_identifier_safety_passed: true,
      ...(overrides.tests ?? {}),
    },
    evaluation_design: {
      holdout_independent: true,
      holdout_base_cases: 30,
      unseen_holdout_templates: true,
      unseen_holdout_lexicon: true,
      s3_frozen_before_holdout_evaluation: true,
      ...(overrides.evaluation_design ?? {}),
    },
    reproducibility: {
      fixed_seed: true,
      corpus_version: 'r0-v1',
      schema_version: 'r0-schema-v1',
      git_sha: '0123456789abcdef',
      runtime_version: 'node-test-fixture',
      deterministic_ordering: true,
      git_dirty: false,
      exact_head_benchmark_evidence: true,
      ...(overrides.reproducibility ?? {}),
    },
    result: {
      measurable_advantage: 'YES',
      holdout_measurable_advantage: 'YES',
      r0_decision: 'PASS_CANDIDATE',
      catastrophic_recall_collapse: false,
      clinical_utility_measured: true,
      utility_measurement_level: 'VERBATIM_RETENTION',
      ...(overrides.result ?? {}),
    },
  };
}

test('PASS_CANDIDATE requires both customer and hardened R0 gates to pass', () => {
  const result = evaluateB63Validation(strongCustomer(), r0(), config);
  assert.equal(result.decision, 'PASS_CANDIDATE');
  assert.equal(result.customer_gate.status, 'PASS');
  assert.equal(result.r0_gate.status, 'PASS');
  assert.equal(result.full_build_authorized, false);
});

test('small customer sample stays INCOMPLETE instead of FAIL', () => {
  const result = evaluateB63Validation(
    customer([interview('h1'), interview('h2')]),
    r0(),
    config,
  );
  assert.equal(result.customer_gate.status, 'INCOMPLETE');
  assert.equal(result.decision, 'INCOMPLETE');
});

test('complete but weak customer evidence narrows the product', () => {
  const weak = customer([
    interview('h1', 'hospital', { problem_severity: 0, clinical_domain_gap: 0, poc_path: 'none' }),
    interview('h2', 'hospital', { problem_severity: 0, clinical_domain_gap: 0, poc_path: 'none' }),
    interview('h3', 'hospital', { problem_severity: 1, clinical_domain_gap: 1, poc_path: 'none' }),
    interview('v1', 'his_vendor', { problem_severity: 1, clinical_domain_gap: 1, poc_path: 'none' }),
    interview('v2', 'his_vendor', { problem_severity: 1, clinical_domain_gap: 1, poc_path: 'none' }),
  ]);
  const result = evaluateB63Validation(weak, r0(), config);
  assert.equal(result.customer_gate.status, 'FAIL');
  assert.equal(result.decision, 'NARROW');
});

test('explicit R0 NARROW decision is preserved', () => {
  const result = evaluateB63Validation(
    strongCustomer(),
    r0({ result: { r0_decision: 'NARROW' } }),
    config,
  );
  assert.equal(result.r0_gate.status, 'NARROW');
  assert.equal(result.decision, 'NARROW');
});

test('real patient data forces STOP_OR_REFRAME', () => {
  const result = evaluateB63Validation(
    strongCustomer(),
    r0({ dataset: { real_patient_data_used: true, synthetic_public_only: false } }),
    config,
  );
  assert.equal(result.r0_gate.boundary_violation, true);
  assert.equal(result.r0_gate.status, 'STOP_OR_REFRAME');
  assert.equal(result.decision, 'STOP_OR_REFRAME');
  assert.equal(result.full_build_authorized, false);
});

test('malformed interview score is rejected', () => {
  const malformed = strongCustomer();
  malformed.interviews[0].problem_severity = 9;
  assert.throws(
    () => evaluateB63Validation(malformed, r0(), config),
    /problem_severity must be between 0 and 2/,
  );
});

test('duplicate interview ids are rejected', () => {
  assert.throws(
    () =>
      evaluateB63Validation(
        customer([interview('dup'), interview('dup')]),
        r0(),
        config,
      ),
    /duplicate interview id/,
  );
});

test('missing required R0 system keeps result INCOMPLETE', () => {
  const result = evaluateB63Validation(
    strongCustomer(),
    r0({ systems: { s3_b63_hybrid_r0: false } }),
    config,
  );
  assert.equal(result.r0_gate.status, 'INCOMPLETE');
  assert.equal(result.decision, 'INCOMPLETE');
});

test('co-designed corpus without independent holdout cannot pass', () => {
  const result = evaluateB63Validation(
    strongCustomer(),
    r0({ evaluation_design: { holdout_independent: false } }),
    config,
  );
  assert.equal(result.r0_gate.status, 'INCOMPLETE');
  assert.equal(result.decision, 'INCOMPLETE');
});

test('synthetic identifier collision safety is required', () => {
  const result = evaluateB63Validation(
    strongCustomer(),
    r0({ dataset: { synthetic_identifier_collision_safe: false } }),
    config,
  );
  assert.equal(result.r0_gate.status, 'INCOMPLETE');
  assert.equal(result.decision, 'INCOMPLETE');
});

test('changed-file secret scan is required', () => {
  const result = evaluateB63Validation(
    strongCustomer(),
    r0({ tests: { changed_file_secret_scan_passed: false } }),
    config,
  );
  assert.equal(result.r0_gate.status, 'INCOMPLETE');
  assert.equal(result.decision, 'INCOMPLETE');
});

test('clean exact-head benchmark evidence is required', () => {
  for (const reproducibility of [
    { git_dirty: true },
    { exact_head_benchmark_evidence: false },
  ]) {
    const result = evaluateB63Validation(
      strongCustomer(),
      r0({ reproducibility }),
      config,
    );
    assert.equal(result.r0_gate.status, 'INCOMPLETE');
    assert.equal(result.decision, 'INCOMPLETE');
  }
});

test('negative holdout evidence cannot be promoted to PASS', () => {
  const result = evaluateB63Validation(
    strongCustomer(),
    r0({ result: { holdout_measurable_advantage: 'NO' } }),
    config,
  );
  assert.equal(result.r0_gate.status, 'STOP_OR_REFRAME');
  assert.equal(result.decision, 'STOP_OR_REFRAME');
});

test('catastrophic recall collapse narrows an otherwise complete candidate', () => {
  const result = evaluateB63Validation(
    strongCustomer(),
    r0({ result: { catastrophic_recall_collapse: true } }),
    config,
  );
  assert.equal(result.r0_gate.status, 'NARROW');
  assert.equal(result.decision, 'NARROW');
});
