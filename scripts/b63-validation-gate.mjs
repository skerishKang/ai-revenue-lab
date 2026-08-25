#!/usr/bin/env node

import { readFile } from 'node:fs/promises';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));
export const DEFAULT_CONFIG_PATH = resolve(
  SCRIPT_DIR,
  '../docs/experiments/b63/validation-gates.json',
);

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function requireObject(value, label) {
  invariant(isPlainObject(value), `${label} must be an object`);
  return value;
}

function requireString(value, label) {
  invariant(typeof value === 'string' && value.length > 0, `${label} must be a non-empty string`);
  return value;
}

function requireBoolean(value, label) {
  invariant(typeof value === 'boolean', `${label} must be a boolean`);
  return value;
}

function requireInteger(value, label, { min = Number.MIN_SAFE_INTEGER, max = Number.MAX_SAFE_INTEGER } = {}) {
  invariant(Number.isInteger(value), `${label} must be an integer`);
  invariant(value >= min && value <= max, `${label} must be between ${min} and ${max}`);
  return value;
}

function requireEnum(value, label, allowed) {
  invariant(allowed.includes(value), `${label} must be one of: ${allowed.join(', ')}`);
  return value;
}

function validateBusinessMarker(value, label) {
  const business = requireObject(value, label);
  invariant(business.number === 63, `${label}.number must be 63`);
  invariant(business.status === 'proposed', `${label}.status must be proposed`);
}

function validateCustomerEvidence(customer) {
  requireObject(customer, 'customer evidence');
  requireEnum(customer.schema_version, 'customer.schema_version', ['b63.customer-discovery.v1']);
  validateBusinessMarker(customer.business, 'customer.business');
  invariant(Array.isArray(customer.interviews), 'customer.interviews must be an array');

  const seen = new Set();
  for (const [index, interview] of customer.interviews.entries()) {
    requireObject(interview, `customer.interviews[${index}]`);
    const id = requireString(interview.id, `customer.interviews[${index}].id`);
    invariant(!seen.has(id), `duplicate interview id: ${id}`);
    seen.add(id);
    requireEnum(interview.organization_type, `customer.interviews[${index}].organization_type`, [
      'hospital',
      'his_vendor',
      'other',
    ]);
    requireInteger(interview.problem_severity, `customer.interviews[${index}].problem_severity`, { min: 0, max: 2 });
    requireInteger(interview.clinical_domain_gap, `customer.interviews[${index}].clinical_domain_gap`, {
      min: 0,
      max: 2,
    });
    requireInteger(interview.budget_owner, `customer.interviews[${index}].budget_owner`, { min: 0, max: 2 });
    requireInteger(interview.deployment_feasibility, `customer.interviews[${index}].deployment_feasibility`, {
      min: 0,
      max: 2,
    });
    requireInteger(interview.poc_intent, `customer.interviews[${index}].poc_intent`, { min: 0, max: 2 });
    requireEnum(interview.poc_path, `customer.interviews[${index}].poc_path`, ['none', 'paid', 'grant_backed']);
  }
}

function validateR0Evidence(r0) {
  requireObject(r0, 'r0 evidence');
  requireEnum(r0.schema_version, 'r0.schema_version', ['b63.r0-result.v1']);
  validateBusinessMarker(r0.business, 'r0.business');

  const dataset = requireObject(r0.dataset, 'r0.dataset');
  requireBoolean(dataset.real_patient_data_used, 'r0.dataset.real_patient_data_used');
  requireBoolean(dataset.synthetic_public_only, 'r0.dataset.synthetic_public_only');
  requireBoolean(dataset.synthetic_identifier_collision_safe, 'r0.dataset.synthetic_identifier_collision_safe');
  requireInteger(dataset.base_cases, 'r0.dataset.base_cases', { min: 0 });

  const systems = requireObject(r0.systems, 'r0.systems');
  for (const key of ['s0_ipu_current', 's1_generic_pii_baseline', 's2_clinical_baseline', 's3_b63_hybrid_r0']) {
    requireBoolean(systems[key], `r0.systems.${key}`);
  }

  const tests = requireObject(r0.tests, 'r0.tests');
  requireBoolean(tests.passed, 'r0.tests.passed');
  requireBoolean(tests.changed_file_secret_scan_passed, 'r0.tests.changed_file_secret_scan_passed');
  requireBoolean(tests.synthetic_identifier_safety_passed, 'r0.tests.synthetic_identifier_safety_passed');

  const design = requireObject(r0.evaluation_design, 'r0.evaluation_design');
  requireBoolean(design.holdout_independent, 'r0.evaluation_design.holdout_independent');
  requireInteger(design.holdout_base_cases, 'r0.evaluation_design.holdout_base_cases', { min: 0 });
  requireBoolean(design.unseen_holdout_templates, 'r0.evaluation_design.unseen_holdout_templates');
  requireBoolean(design.unseen_holdout_lexicon, 'r0.evaluation_design.unseen_holdout_lexicon');
  requireBoolean(
    design.s3_frozen_before_holdout_evaluation,
    'r0.evaluation_design.s3_frozen_before_holdout_evaluation',
  );

  const reproducibility = requireObject(r0.reproducibility, 'r0.reproducibility');
  requireBoolean(reproducibility.fixed_seed, 'r0.reproducibility.fixed_seed');
  requireString(reproducibility.corpus_version, 'r0.reproducibility.corpus_version');
  requireString(reproducibility.schema_version, 'r0.reproducibility.schema_version');
  requireString(reproducibility.git_sha, 'r0.reproducibility.git_sha');
  requireString(reproducibility.runtime_version, 'r0.reproducibility.runtime_version');
  requireBoolean(reproducibility.deterministic_ordering, 'r0.reproducibility.deterministic_ordering');
  requireBoolean(reproducibility.git_dirty, 'r0.reproducibility.git_dirty');
  requireBoolean(reproducibility.exact_head_benchmark_evidence, 'r0.reproducibility.exact_head_benchmark_evidence');

  const result = requireObject(r0.result, 'r0.result');
  requireEnum(result.measurable_advantage, 'r0.result.measurable_advantage', ['YES', 'NO', 'INCONCLUSIVE']);
  requireEnum(result.holdout_measurable_advantage, 'r0.result.holdout_measurable_advantage', [
    'YES',
    'NO',
    'INCONCLUSIVE',
  ]);
  requireEnum(result.r0_decision, 'r0.result.r0_decision', [
    'PASS_CANDIDATE',
    'NARROW',
    'STOP_OR_REFRAME',
    'INCOMPLETE',
  ]);
  requireBoolean(result.catastrophic_recall_collapse, 'r0.result.catastrophic_recall_collapse');
  requireBoolean(result.clinical_utility_measured, 'r0.result.clinical_utility_measured');
  requireEnum(result.utility_measurement_level, 'r0.result.utility_measurement_level', [
    'VERBATIM_RETENTION',
    'DOWNSTREAM_TASK',
    'OTHER',
  ]);
}

function evaluateCustomerGate(customer, config) {
  const t = config.customer_gate;
  const interviews = customer.interviews;
  const metrics = {
    interviews_total: interviews.length,
    hospital_interviews: interviews.filter((x) => x.organization_type === 'hospital').length,
    problem_severity_2_count: interviews.filter((x) => x.problem_severity === 2).length,
    clinical_domain_gap_2_count: interviews.filter((x) => x.clinical_domain_gap === 2).length,
    paid_or_grant_backed_poc_paths: interviews.filter(
      (x) => x.poc_path === 'paid' || x.poc_path === 'grant_backed',
    ).length,
  };

  const checks = {
    interviews_total: metrics.interviews_total >= t.min_interviews,
    hospital_interviews: metrics.hospital_interviews >= t.min_hospital_interviews,
    problem_severity_2_count: metrics.problem_severity_2_count >= t.min_problem_severity_2,
    clinical_domain_gap_2_count: metrics.clinical_domain_gap_2_count >= t.min_clinical_domain_gap_2,
    paid_or_grant_backed_poc_paths:
      metrics.paid_or_grant_backed_poc_paths >= t.min_paid_or_grant_backed_poc_paths,
  };

  const sampleComplete = checks.interviews_total && checks.hospital_interviews;
  const status = Object.values(checks).every(Boolean) ? 'PASS' : sampleComplete ? 'FAIL' : 'INCOMPLETE';
  return { status, metrics, checks };
}

function evaluateR0Gate(r0, config) {
  const t = config.r0_gate;
  const boundaryViolation = r0.dataset.real_patient_data_used || !r0.dataset.synthetic_public_only;

  const checks = {
    synthetic_public_only:
      !r0.dataset.real_patient_data_used &&
      (!t.require_synthetic_public_only || r0.dataset.synthetic_public_only),
    synthetic_identifier_collision_safe:
      !t.require_synthetic_identifier_collision_safe || r0.dataset.synthetic_identifier_collision_safe,
    base_cases: r0.dataset.base_cases >= t.min_base_cases,
    required_systems: t.required_systems.every((name) => r0.systems[name] === true),
    tests_passed: !t.require_tests_passed || r0.tests.passed,
    changed_file_secret_scan_passed:
      !t.require_changed_file_secret_scan_passed || r0.tests.changed_file_secret_scan_passed,
    synthetic_identifier_safety_passed:
      !t.require_synthetic_identifier_safety_passed || r0.tests.synthetic_identifier_safety_passed,
    holdout_base_cases: r0.evaluation_design.holdout_base_cases >= t.min_holdout_base_cases,
    independent_holdout: !t.require_independent_holdout || r0.evaluation_design.holdout_independent,
    unseen_holdout_templates:
      !t.require_unseen_holdout_templates || r0.evaluation_design.unseen_holdout_templates,
    unseen_holdout_lexicon:
      !t.require_unseen_holdout_lexicon || r0.evaluation_design.unseen_holdout_lexicon,
    s3_frozen_before_holdout_evaluation:
      !t.require_s3_frozen_before_holdout_evaluation ||
      r0.evaluation_design.s3_frozen_before_holdout_evaluation,
    exact_head_benchmark_evidence:
      !t.require_exact_head_benchmark_evidence || r0.reproducibility.exact_head_benchmark_evidence,
    clean_git_evaluation: !t.require_clean_git_evaluation || !r0.reproducibility.git_dirty,
    clinical_utility_measured:
      !t.require_clinical_utility_measured || r0.result.clinical_utility_measured,
    no_catastrophic_recall_collapse:
      !t.forbid_catastrophic_recall_collapse || !r0.result.catastrophic_recall_collapse,
    reproducibility: t.required_reproducibility_fields.every((name) => {
      const value = r0.reproducibility[name];
      return value === true || (typeof value === 'string' && value.length > 0);
    }),
  };

  if (boundaryViolation) {
    return { status: 'STOP_OR_REFRAME', boundary_violation: true, checks };
  }

  const completenessChecks = [
    checks.synthetic_identifier_collision_safe,
    checks.base_cases,
    checks.required_systems,
    checks.tests_passed,
    checks.changed_file_secret_scan_passed,
    checks.synthetic_identifier_safety_passed,
    checks.holdout_base_cases,
    checks.independent_holdout,
    checks.unseen_holdout_templates,
    checks.unseen_holdout_lexicon,
    checks.s3_frozen_before_holdout_evaluation,
    checks.exact_head_benchmark_evidence,
    checks.clean_git_evaluation,
    checks.clinical_utility_measured,
    checks.reproducibility,
  ];

  if (!completenessChecks.every(Boolean) || r0.result.r0_decision === 'INCOMPLETE') {
    return { status: 'INCOMPLETE', boundary_violation: false, checks };
  }

  if (
    r0.result.r0_decision === 'STOP_OR_REFRAME' ||
    r0.result.measurable_advantage === 'NO' ||
    r0.result.holdout_measurable_advantage === 'NO'
  ) {
    return { status: 'STOP_OR_REFRAME', boundary_violation: false, checks };
  }

  if (
    r0.result.r0_decision === 'NARROW' ||
    r0.result.measurable_advantage === 'INCONCLUSIVE' ||
    r0.result.holdout_measurable_advantage === 'INCONCLUSIVE' ||
    !checks.no_catastrophic_recall_collapse
  ) {
    return { status: 'NARROW', boundary_violation: false, checks };
  }

  return { status: 'PASS', boundary_violation: false, checks };
}

function finalDecision(customerStatus, r0Status) {
  if (r0Status === 'STOP_OR_REFRAME') return 'STOP_OR_REFRAME';
  if (customerStatus === 'INCOMPLETE' || r0Status === 'INCOMPLETE') return 'INCOMPLETE';
  if (customerStatus === 'FAIL' || r0Status === 'NARROW') return 'NARROW';
  if (customerStatus === 'PASS' && r0Status === 'PASS') return 'PASS_CANDIDATE';
  return 'INCOMPLETE';
}

export function evaluateB63Validation(customer, r0, config) {
  requireObject(config, 'config');
  validateBusinessMarker(config.business, 'config.business');
  validateCustomerEvidence(customer);
  validateR0Evidence(r0);

  const customerGate = evaluateCustomerGate(customer, config);
  const r0Gate = evaluateR0Gate(r0, config);

  return {
    schema_version: 'b63.validation-output.v1',
    business: { number: 63, status: 'proposed' },
    decision: finalDecision(customerGate.status, r0Gate.status),
    full_build_authorized: false,
    customer_gate: customerGate,
    r0_gate: r0Gate,
    authority: config.authority,
  };
}

async function readJson(path) {
  const raw = await readFile(path, 'utf8');
  return JSON.parse(raw);
}

export async function runCli(argv) {
  const [customerPath, r0Path, configPath = DEFAULT_CONFIG_PATH] = argv;
  if (!customerPath || !r0Path) {
    throw new Error(
      'usage: node scripts/b63-validation-gate.mjs <customer-evidence.json> <r0-result.json> [validation-gates.json]',
    );
  }

  const [customer, r0, config] = await Promise.all([
    readJson(customerPath),
    readJson(r0Path),
    readJson(configPath),
  ]);
  return evaluateB63Validation(customer, r0, config);
}

const isDirectExecution = process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
if (isDirectExecution) {
  try {
    const output = await runCli(process.argv.slice(2));
    process.stdout.write(`${JSON.stringify(output, null, 2)}\n`);
    if (output.r0_gate.boundary_violation) process.exitCode = 3;
  } catch (error) {
    process.stderr.write(`B63_VALIDATION_INPUT_ERROR: ${error.message}\n`);
    process.exitCode = 2;
  }
}
