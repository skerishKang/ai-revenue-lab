/**
 * #3436 — read-only result artifact presentation.
 *
 * The projection consumes exactly what the canonical run authority already
 * provides (`{ documentId, filename, mediaType }` per run) and renders it as a
 * read-only result list. These tests pin the fail-closed presentation rules:
 *
 *   SECOND_ARTIFACT_AUTHORITY=0 — no store, no resolved refs, no commands;
 *   ARTIFACT_CONTENT_READ=0 — a filename is a label, never a location;
 *   widened/malformed/private-ref metadata is counted as unsupported and never
 *   rendered (no raw payload dump), in either view mode.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import { RunActivityPanel } from '../src/renderer/app.js';
import type { CanonicalRunListItem, CanonicalRunListResponse } from '../src/renderer/types.js';
import {
  classifyRunArtifactKind,
  presentRunArtifact,
  presentRunArtifacts,
} from '../src/run/artifact-presentation.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const srcRoot = path.join(here, '..', '..', 'src');

function runRow(overrides: Partial<CanonicalRunListItem> = {}): CanonicalRunListItem {
  return {
    runId: 'run_b3f9d2e85c8f7146ba0d3f01',
    status: 'completed',
    channel: 'web',
    action: 'quote_draft',
    title: '[WEB] quote_draft: 홍길동',
    createdAt: '2026-10-02T09:00:00Z',
    updatedAt: '2026-10-02T09:03:21Z',
    resultSummary: '견적서 초안을 완료했습니다.',
    artifact: {
      documentId: 'doc_' + '1'.repeat(24),
      filename: 'quote-draft.docx',
      mediaType: 'application/msword',
    },
    conversationId: null,
    workspaceId: null,
    ...overrides,
  };
}

function runList(runs: readonly CanonicalRunListItem[]): CanonicalRunListResponse {
  return {
    ok: true,
    configured: true,
    runs,
    liveActivitySource: 'not_yet_available',
    errorCode: null,
  };
}

function artifact(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    documentId: 'doc_' + '1'.repeat(24),
    filename: 'quote-draft.docx',
    mediaType: 'application/msword',
    ...overrides,
  };
}

test('#3436 artifacts: zero, one and many are all projected in canonical order', () => {
  assert.deepEqual(presentRunArtifacts([]), { artifacts: [], unsupportedCount: 0 });

  const single = presentRunArtifacts([runRow()]);
  assert.equal(single.artifacts.length, 1);
  assert.equal(single.artifacts[0]?.label, 'quote-draft.docx');
  assert.equal(single.artifacts[0]?.kind, 'document');
  assert.equal(single.artifacts[0]?.runStatus, 'completed');
  assert.equal(single.unsupportedCount, 0);

  const many = presentRunArtifacts([
    runRow({ artifact: artifact({ filename: 'first.pdf', mediaType: 'application/pdf' }) as never }),
    runRow({ runId: 'run_b3f9d2e85c8f7146ba0d3f02', artifact: null }),
    runRow({
      runId: 'run_b3f9d2e85c8f7146ba0d3f03',
      artifact: artifact({ filename: 'photo.png', mediaType: 'image/png' }) as never,
    }),
    runRow({
      runId: 'run_b3f9d2e85c8f7146ba0d3f04',
      artifact: artifact({ filename: 'ledger.csv', mediaType: 'text/csv' }) as never,
    }),
  ]);
  assert.deepEqual(
    many.artifacts.map((item) => item.label),
    ['first.pdf', 'photo.png', 'ledger.csv'],
  );
  assert.deepEqual(
    many.artifacts.map((item) => item.runId),
    [
      'run_b3f9d2e85c8f7146ba0d3f01',
      'run_b3f9d2e85c8f7146ba0d3f03',
      'run_b3f9d2e85c8f7146ba0d3f04',
    ],
  );
  // The projection never re-sorts: it is the server's own order, verbatim.
});

test('#3436 artifacts: malformed or widened metadata fails closed and is counted', () => {
  for (const hostile of [
    'not-an-object',
    42,
    [],
    null,
    artifact({ filename: undefined }),
    artifact({ filename: '' }),
    artifact({ mediaType: undefined }),
    artifact({ documentId: 'doc_' + 'x'.repeat(200) }),
    // Closed set: an arbitrary unknown key is refused whatever its name —
    // there is no extra spelling that slips through a blacklist.
    artifact({ extra: 'anything' }),
    artifact({ provider_meta: { a: 1 } }),
    // Private refs the projection must never carry, whatever the payload says.
    artifact({ session_id: 'sess_stolen_1' }),
    artifact({ binding_ref: 'bind_stolen_1' }),
    artifact({ actor_ref: 'actor_stolen_1' }),
    artifact({ workspace_ref: 'ws_stolen_1' }),
    artifact({ credential: 'credential-stuff' }),
    artifact({ credential_b64: 'AAAAAAAA' }),
    artifact({ token: 'tok_1' }),
    artifact({ secret: 's3cr3t' }),
    // Path authority must stay with the server: never a location in Desktop.
    artifact({ filename: '../../etc/passwd' }),
    artifact({ filename: 'C:\\Users\\person\\secret.docx' }),
    artifact({ filename: 'subdir/nested.pdf' }),
    artifact({ path: 'C:/Windows/win.ini' }),
    artifact({ absolute_path: 'C:/Windows/win.ini' }),
    artifact({ url: 'https://example.invalid/f.pdf' }),
    artifact({ download_url: 'https://example.invalid/f.pdf' }),
    // Raw provider dumps are refused outright, never rendered.
    artifact({ provider_response: { raw: 'everything' } }),
  ]) {
    const projected = presentRunArtifact(runRow(), hostile);
    assert.equal(projected, null, typeof hostile === 'object' ? 'object-shaped' : 'scalar-shaped');
  }

  const result = presentRunArtifacts([
    runRow({ artifact: artifact({ credential_b64: 'AAAAAAAA' }) as never }),
  ]);
  assert.deepEqual(result, { artifacts: [], unsupportedCount: 1 });
});

test('#3436 artifacts: media type classifies into human categories only', () => {
  const cases: ReadonlyArray<[string, string]> = [
    ['application/msword', 'document'],
    ['application/pdf', 'document'],
    ['text/markdown', 'document'],
    ['image/png', 'image'],
    ['text/csv', 'table'],
    ['application/vnd.ms-excel', 'table'],
    ['application/zip', 'archive'],
    ['application/x-tar', 'archive'],
    ['application/octet-stream', 'other'],
    ['', 'other'],
  ];
  for (const [mediaType, expected] of cases) {
    assert.equal(classifyRunArtifactKind(mediaType), expected, mediaType);
  }
});

test('#3436 artifacts: the presentation carries no command surface at all', () => {
  const presented = presentRunArtifacts([runRow()]).artifacts[0];
  assert.ok(presented);
  assert.deepEqual(Object.keys(presented).sort(), [
    'documentId',
    'key',
    'kind',
    'label',
    'mediaType',
    'runId',
    'runStatus',
    'runTitle',
  ]);
});

function renderRunPanel(runs: CanonicalRunListResponse, locale: 'ko' | 'en', advanced: boolean): string {
  return renderToStaticMarkup(createElement(RunActivityPanel, { locale, advanced, runs }));
}

test('#3436 artifacts UI: empty, one, and unsupported states render safely', () => {
  const empty = renderRunPanel(runList([runRow({ artifact: null })]), 'ko', false);
  assert.match(empty, /run-artifacts/);
  assert.match(empty, /결과 파일/);
  assert.match(empty, /첨부된 결과 파일이 없습니다/);
  assert.doesNotMatch(empty, /지원하지 않는/);

  const unsupported = renderRunPanel(
    runList([runRow({ artifact: artifact({ filename: 'C:\\evil\\x.docx' }) as never })]),
    'ko',
    false,
  );
  assert.match(unsupported, /지원하지 않는 결과 형식/);
  // The refused metadata is never dumped, and the path never renders.
  assert.doesNotMatch(unsupported, /evil|x\.docx|C:/);
});

test('#3436 artifacts UI: Easy mode renders labels and hides canonical references', () => {
  const markup = renderRunPanel(runList([runRow()]), 'ko', false);
  assert.match(markup, /quote-draft\.docx/);
  assert.match(markup, /문서/);
  assert.match(markup, /data-artifact-kind="document"/);
  assert.match(markup, /data-run-status="completed"/);
  // Document references and media types are Advanced-only diagnostics.
  assert.doesNotMatch(markup, /doc_1{24}/);
  assert.doesNotMatch(markup, /application\/msword/);
  assert.doesNotMatch(markup, /<a href=/);
});

test('#3436 artifacts UI: Advanced mode adds only bounded metadata', () => {
  const markup = renderRunPanel(runList([runRow()]), 'en', true);
  assert.match(markup, /quote-draft\.docx/);
  assert.match(markup, /data-advanced="true"/);
  assert.match(markup, /Document/);
  assert.match(markup, /doc_1{24}/);
  assert.match(markup, /application\/msword/);
  // Even the diagnostics are the three bounded fields: nothing private rides along.
  assert.doesNotMatch(markup, /credential|session|binding|token|secret/i);
});

test('#3436 artifacts UI: the surface offers no write, delete or execute control', () => {
  const markup = renderRunPanel(
    runList([
      runRow(),
      runRow({ runId: 'run_b3f9d2e85c8f7146ba0d3f05', artifact: artifact({ filename: 'b.png', mediaType: 'image/png' }) as never }),
    ]),
    'ko',
    true,
  );
  assert.match(markup, /data-artifact-count="2"/);
  // Isolate the artifact section: the surrounding run rows legitimately show
  // their own Advanced facts (the run id label is "실행 ID"), which are not part
  // of this presentation and are out of scope for the command-word check.
  const artifactSection = markup.slice(
    markup.indexOf('<section class="run-artifacts"'),
    markup.indexOf('</section>', markup.indexOf('<section class="run-artifacts"')) + '</section>'.length,
  );
  assert.ok(artifactSection.length > 0);
  // No command word appears inside the artifact section.
  assert.doesNotMatch(artifactSection, /삭제|다운로드|열기|이름 바꾸기|저장|실행/);
  assert.doesNotMatch(artifactSection, /Delete|Download|Open|Rename|Save|Execute/i);
  // The artifact section contains no interactive command elements at all.
  assert.doesNotMatch(artifactSection, /<button/i);
  assert.doesNotMatch(artifactSection, /<input/i);
  assert.doesNotMatch(artifactSection, /<form/i);
  assert.doesNotMatch(artifactSection, /<a /i);
  assert.doesNotMatch(artifactSection, /<textarea/i);
});

test('#3436 artifacts UI: no new IPC channel and no transport of its own', () => {
  const presentation = readFileSync(path.join(srcRoot, 'run', 'artifact-presentation.ts'), 'utf8');
  for (const forbidden of [
    'ipcRenderer',
    'ipcMain',
    'fetch(',
    'child_process',
    'node:fs',
    'localStorage',
    'padiem:shell:',
  ]) {
    assert.equal(presentation.includes(forbidden), false, forbidden);
  }
  // The renderer section is a pure projection of the canonical run list: the
  // panel receives `runs` only, so the canonical run authority stays the sole
  // source (CANONICAL_RUN_SOURCE_REUSED=YES, SECOND_TASK_RUN_AUTHORITY=0).
  const app = readFileSync(path.join(srcRoot, 'renderer', 'app.tsx'), 'utf8');
  assert.match(app, /RunArtifactsSection\s+runs=\{runs\.runs\}/);
});

test('#3436 artifacts UI: a non-canonical run projection renders no artifact section', () => {
  const markup = renderRunPanel(
    { ...runList([]), ok: false, errorCode: 'canonical_run_unavailable' },
    'ko',
    false,
  );
  assert.match(markup, /data-run-source="canonical-required"/);
  assert.doesNotMatch(markup, /run-artifacts/);
});
