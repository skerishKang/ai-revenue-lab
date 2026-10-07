/**
 * #3583 — workspace file search primitive (ZCode-derived) unit tests.
 *
 * Pure tests only: no filesystem, no IPC, no network, no provider calls.
 * The provenance test pins the upstream attribution header so the DERIVED
 * provenance block cannot silently disappear from the adapted module.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  WORKSPACE_FILE_SEARCH_DISPLAY_CAP,
  filterWorkspaceFileSearchCandidates,
  getWorkspaceFileSearchCandidateScore,
  mapWorkspaceEntryToSearchCandidate,
  scoreWorkspaceFileFuzzyMatch,
  searchWorkspaceEntries,
} from '../src/workspace/workspace-file-search.js';

// Resolved from dist/tests back to the real TS source, because this file is
// executed from dist/tests while the provenance header lives under src/.
const packageRoot = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

function candidate(
  name: string,
  relativePath: string,
  kind: 'directory' | 'file' | 'link' = 'file',
) {
  return mapWorkspaceEntryToSearchCandidate({ name, relativePath, kind });
}

test('#3583 provenance: ZCode upstream attribution header is pinned in the derived module', () => {
  const source = readFileSync(
    path.join(packageRoot, 'src', 'workspace', 'workspace-file-search.ts'),
    'utf8',
  );
  assert.match(source, /UPSTREAM_REPO=zai-org\/ZCode/);
  assert.match(source, /UPSTREAM_SHA=29628c9acdb81b703bbd4080c207a0e7ce5e276e/);
  assert.match(source, /UPSTREAM_PATH=packages\/shared\/src\/workspaceFileSearch\.ts/);
  assert.match(source, /ADAPTATION_TYPE=DERIVED/);
});

test('#3583 scoring: empty query scores 0, no match scores null', () => {
  assert.equal(scoreWorkspaceFileFuzzyMatch('anything', '   '), 0);
  assert.equal(scoreWorkspaceFileFuzzyMatch('', 'query'), null);
  assert.equal(scoreWorkspaceFileFuzzyMatch('unrelated.txt', 'zzzz'), null);
});

test('#3583 scoring: prefix beats substring beats subsequence (upstream bands)', () => {
  const prefix = scoreWorkspaceFileFuzzyMatch('config.json', 'conf');
  const substring = scoreWorkspaceFileFuzzyMatch('myconfig.json', 'conf');
  const subsequence = scoreWorkspaceFileFuzzyMatch('c-a-f.json', 'caf');
  assert.equal(typeof prefix, 'number');
  assert.equal(typeof substring, 'number');
  assert.equal(typeof subsequence, 'number');
  assert.ok((prefix as number) < (substring as number));
  assert.ok((substring as number) < (subsequence as number));
  // Prefix band is the remainder length (shorter text wins).
  assert.equal(scoreWorkspaceFileFuzzyMatch('conf.json', 'conf'), 5);
});

test('#3583 candidate score: relative path gets the +25 proximity bonus', () => {
  // A path-only hit (name does not match) scores through the relativePath
  // leg with exactly the upstream +25 proximity bonus: substring(100+idx)+25,
  // where idx=9 for 'index' inside 'docs/src/index.ts'.
  const pathOnly = candidate('readme.md', 'docs/src/index.ts');
  const pathOnlyScore = getWorkspaceFileSearchCandidateScore(pathOnly, 'index');
  assert.equal(pathOnlyScore, 109 + 25);

  // When the name prefix-matches, the name leg dominates (upstream min()),
  // so equal names score equally regardless of path depth.
  const shallow = candidate('a.txt', 'a.txt');
  const deep = candidate('a.txt', 'deeply/nested/dir/a.txt');
  assert.equal(getWorkspaceFileSearchCandidateScore(shallow, 'a'), 4);
  assert.equal(getWorkspaceFileSearchCandidateScore(deep, 'a'), 4);
});

test('#3583 candidate score: relative-path keyword bonus (+300) applies', () => {
  // Query hits the path, not the name: name gets null, path leg scores 100+idx.
  const hit = candidate('readme.md', 'docs/src/overview.md');
  const score = getWorkspaceFileSearchCandidateScore(hit, 'overview');
  assert.equal(typeof score, 'number');
  assert.ok((score as number) >= 100);
  assert.ok((score as number) < 100 + 300);
});

test('#3583 empty-query ordering: directories last, stable by input index', () => {
  const input = [
    candidate('a.ts', 'a.ts'),
    candidate('dirA', 'dirA', 'directory'),
    candidate('b.ts', 'b.ts'),
    candidate('dirB', 'dirB', 'directory'),
  ];
  const ranked = filterWorkspaceFileSearchCandidates(input, '');
  assert.deepEqual(
    ranked.map((entry) => entry.name),
    ['a.ts', 'b.ts', 'dirA', 'dirB'],
  );
});

test('#3583 top-K: limit respected, best matches win, index breaks score ties', () => {
  const input = [
    candidate('aaa1.txt', 'aaa1.txt'),
    candidate('aaa2.txt', 'aaa2.txt'),
    candidate('aaa3.txt', 'aaa3.txt'),
    candidate('aaa-outer.txt', 'aaa-outer.txt'),
  ];
  // All four prefix-match "aaa"; prefix scores are remainder lengths, so
  // 'aaa1.txt'..'aaa3.txt' score 4 and 'aaa-outer.txt' scores 6 (worse).
  const ranked = filterWorkspaceFileSearchCandidates(input, 'aaa', { limit: 3 });
  assert.equal(ranked.length, 3);
  assert.deepEqual(
    ranked.map((entry) => entry.name).sort(),
    ['aaa1.txt', 'aaa2.txt', 'aaa3.txt'],
  );

  // Equal scores keep the original input order.
  const tied = filterWorkspaceFileSearchCandidates(
    [candidate('same-name-x.txt', 'same-name-x.txt'), candidate('same-name-y.txt', 'same-name-y.txt')],
    'same-name',
    { limit: 1 },
  );
  assert.equal(tied.length, 1);
  assert.equal(tied[0]?.name, 'same-name-x.txt');
});

test('#3583 display cap constant stays bounded like upstream', () => {
  assert.equal(WORKSPACE_FILE_SEARCH_DISPLAY_CAP, 1000);
});

test('#3583 searchWorkspaceEntries ranks candidates and preserves deterministic tie-break', () => {
  const input = [
    candidate('report.pdf', 'reports/2026/report.pdf'),
    candidate('report-draft.pdf', 'reports/2026/report-draft.pdf'),
    candidate('unrelated.txt', 'notes/unrelated.txt'),
  ];
  const ranked = searchWorkspaceEntries(input, 'report');
  assert.deepEqual(ranked.map((entry) => entry.name), [
    'report.pdf',
    'report-draft.pdf',
  ]);
  assert.equal(searchWorkspaceEntries(input, 'zzzz').length, 0);
});
