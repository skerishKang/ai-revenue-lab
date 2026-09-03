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

function strongCustomer() {
  return customer([
    interview('h1'),
    interview('h2'),
    interview('h3'),
    interview('v1', 'his_vendor'),
    interview('v2', 'his_vendor'),
  ]);
}

function customer(interviews) {
  return {
    schema_version: 'b63.customer-discovery.v1',
    business: { number: 63, status: 'proposed' },
    interviews,
  };
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

test('PASS_CANDIDATE requires customer gate pltÈ\™[™Y[™\[™[Œ]šY[˜ÙIË

HOˆÂˆÛÛœİ™\İ[H]˜[X]PŒÕ˜[Y][ÛŠİ›Û™Ğİ\İÛY\Š
KŒ

KÛÛ™šYÊNÂˆ\ÜÙ\™\]X[
™\İ[˜İ\İÛY\—ÙØ]Kœİ]\Ë	ÔTÔÉÊNÂˆ\ÜÙ\™\]X[
™\İ[œŒÙØ]Kœİ]\Ë	ÔTÔÉÊNÂˆ\ÜÙ\™\]X[
™\İ[™XÚ\Ú[Û‹	ÔTÔ×ĞĞS‘QUIÊNÂˆ\ÜÙ\™\]X[
™\İ[™[ØZ[Ø]]Üš^™Y˜[ÙJNÂŸJNÂ‚\İ
	Ú[œİY™šXÚY[[\šY]ÈØ[\Hİ^\ÈSÓÓTUH[œİXYÙˆ™Z[™ÈØÛÜ™Y]Ø^IË

HOˆÂˆÛÛœİ™\İ[H]˜[X]PŒÕ˜[Y][ÛŠİ\İÛY\ŠÚ[\šY]Ê	ÚIÊK[\šY]Ê	Ú‰ÊWJKŒ

KÛÛ™šYÊNÂˆ\ÜÙ\™\]X[
™\İ[˜İ\İÛY\—ÙØ]Kœİ]\Ë	ÒSÓÓTUIÊNÂˆ\ÜÙ\™\]X[
™\İ[™XÚ\Ú[Û‹	ÒSÓÓTUIÊNÂŸJNÂ‚\İ
	ØÛÛ\]Y]ÙXZÈİ\İÛY\ˆ]šY[˜ÙH˜\œ›İÜÈH›ÙXİ	Ë

HOˆÂˆÛÛœİÙXZÈHÂˆ[\šY]Ê	ÚIË	ÚÜÜ][	ËÈ›Ø›[WÜÙ]™\š]NˆÛ[šXØ[ÙÛXZ[—ÙØ\ˆØ×Ü]ˆ	Û›Û™IÈJKˆ[\šY]Ê	Ú‰Ë	ÚÜÜ][	ËÈ›Ø›[WÜÙ]™\š]NˆÛ[šXØ[ÙÛXZ[—ÙØ\ˆØ×Ü]ˆ	Û›Û™IÈJKˆ[\šY]Ê	ÚÉË	ÚÜÜ][	ËÈ›Ø›[WÜÙ]™\š]NˆKÛ[šXØ[ÙÛXZ[—ÙØ\ˆKØ×Ü]ˆ	Û›Û™IÈJKˆ[\šY]Ê	İŒIË	Ú\×İ™[™Ü‰ËÈ›Ø›[WÜÙ]™\š]NˆKÛ[šXØ[ÙÛXZ[—ÙØ\ˆKØ×Ü]ˆ	Û›Û™IÈJKˆ[\šY]Ê	İŒ‰Ë	Ú\×İ™[™Ü‰ËÈ›Ø›[WÜÙ]™\š]NˆKÛ[šXØ[ÙÛXZ[—ÙØ\ˆKØ×Ü]ˆ	Û›Û™IÈJKˆNÂˆÛÛœİ™\İ[H]˜[X]PŒÕ˜[Y][ÛŠİ\İÛY\ŠÙXZÊKŒ

KÛÛ™šYÊNÂˆ\ÜÙ\™\]X[
™\İ[˜İ\İÛY\—ÙØ]Kœİ]\Ë	ÑRS	ÊNÂˆ\ÜÙ\™\]X[
™\İ[™XÚ\Ú[Û‹	ÓT”“ÕÉÊNÂŸJNÂ‚\İ
	Ù^XÚ]Œ˜\œ›İÈXÚ\Ú[Ûˆ\È™\Ù\™Y	Ë

HOˆÂˆÛÛœİ™\İ[H]˜[X]PŒÕ˜[Y][ÛŠˆİ›Û™Ğİ\İÛY\Š
KˆŒ
È™\İ[ˆÈŒÙXÚ\Ú[Ûˆ	ÓT”“ÕÉËYX\İ\˜X›WØY˜[YÙNˆ	ÒSÓÓÓTÒU‘IÈHJKˆÛÛ™šYËˆ
NÂˆ\ÜÙ\™\]X[
™\İ[œŒÙØ]Kœİ]\Ë	ÓT”“ÕÉÊNÂˆ\ÜÙ\™\]X[
™\İ[™XÚ\Ú[Û‹	ÓT”“ÕÉÊNÂŸJNÂ‚\İ
	Ü™X[]Y[]H›YÈšYÙÙ\œÈÕÔÓÔ—Ô‘Q”SQH›İ[™\Hš[Û][Û‰Ë

HOˆÂˆÛÛœİ™\İ[H]˜[X]PŒÕ˜[Y][ÛŠˆİ›Û™Ğİ\İÛY\Š
KˆŒ
È]\Ù]ˆÈ™X[Ü]Y[Ù]Wİ\ÙYˆYKŞ[]X×ÜX›X×ÛÛ›Nˆ˜[ÙHHJKˆÛÛ™šYËˆ
NÂˆ\ÜÙ\™\]X[
™\İ[œŒÙØ]Kœİ]\Ë	ÔÕÔÓÔ—Ô‘Q”SQIÊNÂˆ\ÜÙ\™\]X[
™\İ[œŒÙØ]K˜›İ[™\Wİš[Û][Û‹YJNÂˆ\ÜÙ\™\]X[
™\İ[™XÚ\Ú[Û‹	ÔÕÔÓÔ—Ô‘Q”SQIÊNÂŸJNÂ‚\İ
	ÛX[›Ü›YY[\šY]È]šY[˜ÙH\È™Z™XİY	Ë

HOˆÂˆÛÛœİX[›Ü›YYHİ\İÛY\ŠÚ[\šY]Ê	ÚIÊWJNÂˆX[›Ü›YYš[\šY]ÜÖÌKœ›Ø›[WÜÙ]™\š]HHNÂˆ\ÜÙ\›İÜÊ

HOˆ]˜[X]PŒÕ˜[Y][ÛŠX[›Ü›YYŒ

KÛÛ™šYÊKÜ›Ø›[WÜÙ]™\š]KÊNÂŸJNÂ‚\İ
	Ù\XØ]H[\šY]ÈYÈ\™H™Z™XİY	Ë

HOˆÂˆ\ÜÙ\›İÜÊˆ

HOˆ]˜[X]PŒÕ˜[Y][ÛŠİ\İÛY\ŠÚ[\šY]Ê	Ù\	ÊK[\šY]Ê	Ù\	ÊWJKŒ

KÛÛ™šYÊKˆÙ\XØ]H[\šY]ÈYËˆ
NÂŸJNÂ‚\İ
	ÛZ\ÜÚ[™È™\]Z\™YŒŞ\İ[HÙY\È™\İ[[˜ÛÛ\]IË

HOˆÂˆÛÛœİ™\İ[H]˜[X]PŒÕ˜[Y][ÛŠˆİ›Û™Ğİ\İÛY\Š
KˆŒ
ÈŞ\İ[\ÎˆÈÌWÙÙ[™\šX×ÜZWØ˜\Ù[[™Nˆ˜[ÙHHJKˆÛÛ™šYËˆ
NÂˆ\ÜÙ\™\]X[
™\İ[œŒÙØ]Kœİ]\Ë	ÒSÓÓTUIÊNÂˆ\ÜÙ\™\]X[
™\İ[™XÚ\Ú[Û‹	ÒSÓÓTUIÊNÂŸJNÂ‚\İ
	ØÛËY\ÚYÛ™YÛÜœ\ÈÚ]İ][™\[™[Ûİ]Ø[››İ\ÜÉË

HOˆÂˆÛÛœİ™\İ[H]˜[X]PŒÕ˜[Y][ÛŠˆİ›Û™Ğİ\İÛY\Š
KˆŒ
Âˆ]˜[X][Û—Ù\ÚYÛˆÂˆÛİ]Ú[™\[™[ˆ˜[ÙKˆÛİ]Ø˜\ÙWØØ\Ù\Îˆˆ[œÙY[—ÚÛİ]İ[\]\Îˆ˜[ÙKˆ[œÙY[—ÚÛİ]Û^XÛÛˆ˜[ÙKˆÌ×Ùœ›Ş™[—Ø™Y›Ü™WÚÛİ]Ù]˜[X][Ûˆ˜[ÙKˆKˆ™\İ[ˆÈÛİ]ÛYX\İ\˜X›WØY˜[YÙNˆ	ÒSÓÓÓTÒU‘IÈKˆJKˆÛÛ™šYËˆ
NÂˆ\ÜÙ\™\]X[
™\İ[œŒÙØ]Kœİ]\Ë	ÒSÓÓTUIÊNÂˆ\ÜÙ\™\]X[
™\İ[œŒÙØ]K˜ÚXÚÜËš[™\[™[ÚÛİ]˜[ÙJNÂˆ\ÜÙ\™\]X[
™\İ[™XÚ\Ú[Û‹	ÒSÓÓTUIÊNÂŸJNÂ‚\İ
	ÜŞ[]XÈY[YšY\ˆÛÛ\Ú[Û‹\ØY™]H˜Z[\™HØ[››İ\ÜÉË

HOˆÂˆÛÛœİ™\İ[H]˜[X]PŒÕ˜[Y][ÛŠˆİ›Û™Ğİ\İÛY\Š
KˆŒ
Âˆ]\Ù]ˆÈŞ[]X×ÚY[YšY\—ØÛÛ\Ú[Û—ÜØY™Nˆ˜[ÙHKˆ\İÎˆÈŞ[]X×ÚY[YšY\—ÜØY™]WÜ\ÜÙYˆ˜[ÙHKˆJKˆÛÛ™šYËˆ
NÂˆ\ÜÙ\™\]X[
™\İ[œŒÙØ]Kœİ]\Ë	ÒSÓÓTUIÊNÂˆ\ÜÙ\™\]X[
™\İ[œŒÙØ]K˜ÚXÚÜËœŞ[]X×ÚY[YšY\—ØÛÛ\Ú[Û—ÜØY™K˜[ÙJNÂŸJNÂ‚\İ
	ÛZ\ÜÚ[™ÈÚ[™ÙYYš[HÙXÜ™]ØØ[ˆØ[››İ\ÜÉË

HOˆÂˆÛÛœİ™\İ[H]˜[X]PŒÕ˜[Y][ÛŠˆİ›Û™Ğİ\İÛY\Š
KˆŒ
È\İÎˆÈÚ[™ÙYÙš[WÜÙXÜ™]ÜØØ[—Ü\ÜÙYˆ˜[ÙHHJKˆÛÛ™šYËˆ
NÂˆ\ÜÙ\™\]X[
™\İ[œŒÙØ]Kœİ]\Ë	ÒSÓÓTUIÊNÂˆ\ÜÙ\™\]X[
™\İ[œŒÙØ]K˜ÚXÚÜË˜Ú[™ÙYÙš[WÜÙXÜ™]ÜØØ[—Ü\ÜÙY˜[ÙJNÂŸJNÂ‚\İ
	Ù\HÜˆ›Û‹Y^XİZXY™[˜ÚX\šÈ]šY[˜ÙHØ[››İ\ÜÉË

HOˆÂˆÛÛœİ™\İ[H]˜[X]PŒÕ˜[Y][ÛŠˆİ›Û™Ğİ\İÛY\Š
KˆŒ
È™\›ÙXÚXš[]NˆÈÚ]Ù\NˆYK^XİÚXYØ™[˜ÚX\š×Ù]šY[˜ÙNˆ˜[ÙHHJKˆÛÛ™šYËˆ
NÂˆ\ÜÙ\™\]X[
™\İ[œŒÙØ]Kœİ]\Ë	ÒSÓÓTUIÊNÂˆ\ÜÙ\™\]X[
™\İ[œŒÙØ]K˜ÚXÚÜË˜ÛX[—ÙÚ]Ù]˜[X][Û‹˜[ÙJNÂˆ\ÜÙ\™\]X[
™\İ[œŒÙØ]K˜ÚXÚÜË™^XİÚXYØ™[˜ÚX\š×Ù]šY[˜ÙK˜[ÙJNÂŸJNÂ‚\İ
	ØÛÛ\]YÛİ]Ú]›ÈYX\İ\˜X›HY˜[YÙHİÜÈÜˆ™Yœ˜[Y\ÉË

HOˆÂˆÛÛœİ™\İ[H]˜[X]PŒÕ˜[Y][ÛŠˆİ›Û™Ğİ\İÛY\Š
KˆŒ
Âˆ™\İ[ˆÂˆYX\İ\˜X›WØY˜[YÙNˆ	ÖQTÉËˆÛİ]ÛYX\İ\˜X›WØY˜[YÙNˆ	Ó“ÉËˆŒÙXÚ\Ú[Ûˆ	ÔTÔ×ĞĞS‘QUIËˆKˆJKˆÛÛ™šYËˆ
NÂˆ\ÜÙ\™\]X[
™\İ[œŒÙØ]Kœİ]\Ë	ÔÕÔÓÔ—Ô‘Q”SQIÊNÂˆ\ÜÙ\™\]X[
™\İ[™XÚ\Ú[Û‹	ÔÕÔÓÔ—Ô‘Q”SQIÊNÂŸJNÂ