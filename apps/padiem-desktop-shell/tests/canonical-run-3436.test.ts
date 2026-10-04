import test from 'node:test';
import assert from 'node:assert/strict';

import {
  CANONICAL_CONVERSATION_ID_PATTERN,
} from '../src/conversation/canonical-conversation.js';
import {
  CANONICAL_RUN_ID_PATTERN,
  CANONICAL_RUN_STATUSES,
  CANONICAL_WORKSPACE_ID_PATTERN,
  CanonicalRunController,
  LIVE_ACTIVITY_SOURCE,
  MAX_CANONICAL_RUNS,
  MAX_RUN_RESULT_SUMMARY_CHARS,
  UnconfiguredCanonicalRunPort,
} from '../src/run/canonical-run.js';
import type {
  CanonicalRunListItem,
  CanonicalRunPort,
} from '../src/run/canonical-run.js';

const CANONICAL_RUN_ID = 'run_' + 'a2f8c1d94b7e6035fa9c2e11';
const OTHER_RUN_ID = 'run_' + 'b3f9d2e85c8f7146ba0d3f22';
const CANONICAL_CONVERSATION_ID = 'chat_' + 'a'.repeat(32);
const CANONICAL_WORKSPACE_ID = 'ws_padiem_main_01';

/**
 * The exact projection `history._run_history_public` emits — the same shape
 * Web Claw reads from `GET /api/claw/runs`. The Desktop test fixture is this
 * payload verbatim so the parity claim below is about the real contract.
 */
function canonicalRunRow(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    run_id: CANONICAL_RUN_ID,
    channel: 'web',
    action: 'quote_draft',
    title: '[WEB] quote_draft: 홍길동',
    status: 'completed',
    created_at: '2026-10-02T09:00:00Z',
    updated_at: '2026-10-02T09:03:21Z',
    result_summary: '견적서 초안이 완성되었습니다.',
    artifact: {
      document_id: 'doc_' + '1'.repeat(24),
      filename: 'quote-draft.docx',
      media_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    },
    session: { conversation_id: CANONICAL_CONVERSATION_ID },
    workspace_id: CANONICAL_WORKSPACE_ID,
    ...overrides,
  };
}

function canonicalListPayload(...rows: readonly unknown[]): Record<string, unknown> {
  return { ok: true, runs: rows };
}

function fixturePort(overrides: {
  list?: unknown;
  failList?: boolean;
} = {}): CanonicalRunPort {
  return {
    configured: true,
    async listRuns() {
      if (overrides.failList) throw new Error('network down');
      // `in` on purpose: an explicitly null/undefined payload must reach the
      // parser as-is, since a nullish body is itself a malformed answer.
      if ('list' in overrides) return overrides.list;
      return canonicalListPayload();
    },
  };
}

test('#3436 B3a unconfigured port fails closed instead of inventing a run history', async () => {
  const controller = new CanonicalRunController(new UnconfiguredCanonicalRunPort());
  assert.equal(controller.configured, false);

  const list = await controller.listRuns();
  assert.equal(list.ok, false);
  assert.equal(list.errorCode, 'canonical_run_unavailable');
  assert.deepEqual(list.runs, []);
  assert.equal(list.liveActivitySource, 'not_yet_available');

  const read = await controller.readRun({ runId: CANONICAL_RUN_ID });
  assert.equal(read.ok, false);
  assert.equal(read.errorCode, 'canonical_run_unavailable');
  assert.equal(read.run, null);
});

test('#3436 B3a transport failure reports unavailable, never a local run fallback', async () => {
  const controller = new CanonicalRunController(fixturePort({ failList: true }));
  const list = await controller.listRuns();
  assert.equal(list.ok, false);
  assert.equal(list.errorCode, 'canonical_run_unavailable');
  assert.deepEqual(list.runs, []);

  const read = await controller.readRun({ runId: CANONICAL_RUN_ID });
  assert.equal(read.ok, false);
  assert.equal(read.errorCode, 'canonical_run_unavailable');
  assert.equal(read.run, null);
});

test('#3436 B3a server-issued run id projects verbatim with the canonical shape', async () => {
  const controller = new CanonicalRunController(
    fixturePort({ list: canonicalListPayload(canonicalRunRow()) }),
  );
  const list = await controller.listRuns();
  assert.equal(list.ok, true);
  assert.equal(list.errorCode, null);
  assert.equal(list.runs.length, 1);
  const run = list.runs[0];
  assert.equal(run?.runId, CANONICAL_RUN_ID);
  assert.equal(run?.status, 'completed');
  assert.equal(run?.channel, 'web');
  assert.equal(run?.action, 'quote_draft');
  assert.equal(run?.title, '[WEB] quote_draft: 홍길동');
  assert.equal(run?.resultSummary, '견적서 초안이 완성되었습니다.');
  assert.deepEqual(run?.artifact, {
    documentId: 'doc_' + '1'.repeat(24),
    filename: 'quote-draft.docx',
    mediaType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  });
  assert.equal(run?.conversationId, CANONICAL_CONVERSATION_ID);
  assert.equal(run?.workspaceId, CANONICAL_WORKSPACE_ID);
  assert.equal(list.liveActivitySource, 'not_yet_available');
});

test('#3436 B3a web/desktop parity: the same canonical fixture projects one way', async () => {
  // The fixture above is byte-for-byte the `history._run_history_public` shape
  // Web Claw reads. The Desktop projection must carry the identical facts.
  const controller = new CanonicalRunController(
    fixturePort({ list: canonicalListPayload(canonicalRunRow()) }),
  );
  const list = await controller.listRuns();
  const expected: CanonicalRunListItem = {
    runId: CANONICAL_RUN_ID,
    status: 'completed',
    channel: 'web',
    action: 'quote_draft',
    title: '[WEB] quote_draft: 홍길동',
    createdAt: '2026-10-02T09:00:00Z',
    updatedAt: '2026-10-02T09:03:21Z',
    resultSummary: '견적서 초안이 완성되었습니다.',
    artifact: {
      documentId: 'doc_' + '1'.repeat(24),
      filename: 'quote-draft.docx',
      mediaType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    },
    conversationId: CANONICAL_CONVERSATION_ID,
    workspaceId: CANONICAL_WORKSPACE_ID,
  };
  assert.deepEqual(list.runs[0], expected);
});

test('#3436 B3a desktop run id minting is absent; only the server grammar is known', () => {
  // The canonical history holds P01/manual ids (`run_<24hex>`) and automation
  // occurrence ids (`sched_run_<digest>`); the server's own bounded grammar at
  // its /api/claw/runs/{run_id} boundary accepts exactly that family.
  assert.equal(CANONICAL_RUN_ID_PATTERN.test(CANONICAL_RUN_ID), true);
  assert.equal(CANONICAL_RUN_ID_PATTERN.test('run_' + 'a'.repeat(24)), true);
  assert.equal(CANONICAL_RUN_ID_PATTERN.test('sched_run_' + 'b'.repeat(24)), true);
  for (const hostile of [
    '../../etc/passwd',
    "run_'; DROP TABLE claw_run_history;--",
    'run_ with spaces',
    'run_"quoted"',
    'run_' + 'a'.repeat(24) + '/more',
    'run_' + 'a'.repeat(600),
    '',
  ]) {
    assert.equal(
      CANONICAL_RUN_ID_PATTERN.test(hostile as string),
      false,
      JSON.stringify(hostile),
    );
  }
  // The controller owns no minting surface at all.
  const controller = new CanonicalRunController(new UnconfiguredCanonicalRunPort());
  const own = Object.getOwnPropertyNames(Object.getPrototypeOf(controller));
  assert.deepEqual(
    own.filter((name) => name !== 'constructor').sort(),
    ['configured', 'listRuns', 'readRun'],
  );
});

test('#3436 B3a malformed run ids are rejected before any request leaves the process', async () => {
  const requested: unknown[] = [];
  const controller = new CanonicalRunController({
    configured: true,
    async listRuns() {
      requested.push('reached-canonical-authority');
      return canonicalListPayload(canonicalRunRow());
    },
  });

  for (const hostile of [
    undefined,
    null,
    42,
    [],
    { runId: 42 },
    { runId: '../../etc/passwd' },
    { runId: "run_x' OR '1'='1" },
    { runId: 'run_' + 'a'.repeat(600) },
  ]) {
    const rejected = await controller.readRun(hostile);
    assert.equal(rejected.ok, false, JSON.stringify(hostile));
    assert.equal(rejected.errorCode, 'invalid_run_id');
    assert.equal(rejected.run, null);
  }
  assert.deepEqual(requested, [], 'no malformed id may reach the canonical authority');

  const accepted = await controller.readRun({ runId: CANONICAL_RUN_ID });
  assert.equal(accepted.ok, true);
  assert.equal(accepted.run?.runId, CANONICAL_RUN_ID);
});

test('#3436 B3a run-read serves a fresh canonical lookup, not a desktop store', async () => {
  let calls = 0;
  const controller = new CanonicalRunController({
    configured: true,
    async listRuns() {
      calls += 1;
      if (calls === 1) {
        return canonicalListPayload(canonicalRunRow());
      }
      // The second read is a fresh canonical call: a run the server no longer
      // returns is simply not found — nothing is remembered desktop-side.
      return canonicalListPayload();
    },
  });

  const first = await controller.readRun({ runId: CANONICAL_RUN_ID });
  assert.equal(first.ok, true);
  assert.equal(calls, 1);

  const second = await controller.readRun({ runId: CANONICAL_RUN_ID });
  assert.equal(second.ok, false);
  assert.equal(second.errorCode, 'run_not_found');
  assert.equal(second.run, null);
  assert.equal(calls, 2);
});

test('#3436 B3a canonical conversation linkage is preserved and cannot be re-bound by the caller', async () => {
  const controller = new CanonicalRunController(
    fixturePort({ list: canonicalListPayload(canonicalRunRow()) }),
  );
  const list = await controller.listRuns();
  assert.equal(list.runs[0]?.conversationId, CANONICAL_CONVERSATION_ID);
  assert.match(CANONICAL_CONVERSATION_ID, CANONICAL_CONVERSATION_ID_PATTERN);

  // The only caller surface is a run id. There is no request shape that could
  // carry a different conversation for the server's own run row.
  const read = await controller.readRun({
    runId: CANONICAL_RUN_ID,
    conversationId: 'chat_' + 'b'.repeat(32),
    session: { conversation_id: 'chat_' + 'b'.repeat(32) },
  } as unknown);
  assert.equal(read.ok, true);
  assert.equal(read.run?.conversationId, CANONICAL_CONVERSATION_ID);
});

test('#3436 B3a canonical workspace linkage is preserved verbatim and cannot be re-bound by the caller', async () => {
  const controller = new CanonicalRunController(
    fixturePort({ list: canonicalListPayload(canonicalRunRow()) }),
  );
  const list = await controller.listRuns();
  assert.equal(list.runs[0]?.workspaceId, CANONICAL_WORKSPACE_ID);
  assert.match(CANONICAL_WORKSPACE_ID, CANONICAL_WORKSPACE_ID_PATTERN);

  const read = await controller.readRun({
    runId: CANONICAL_RUN_ID,
    workspaceId: 'ws_desktop_local_folder',
  } as unknown);
  assert.equal(read.ok, true);
  assert.equal(read.run?.workspaceId, CANONICAL_WORKSPACE_ID);

  // The canonical list projection may omit the workspace field (legacy rows);
  // absence projects as null and is never backfilled from a local folder.
  const withoutWorkspace = new CanonicalRunController(
    fixturePort({
      list: canonicalListPayload(canonicalRunRow({ workspace_id: undefined })),
    }),
  );
  const list2 = await withoutWorkspace.listRuns();
  assert.equal(list2.runs[0]?.workspaceId, null);
});

test('#3436 B3a status vocabulary is bounded to the canonical ClawRunStatus set', async () => {
  assert.deepEqual([...CANONICAL_RUN_STATUSES], [
    'queued',
    'preparing',
    'running',
    'waiting_approval',
    'completed',
    'failed',
    'cancelled',
  ]);

  for (const status of CANONICAL_RUN_STATUSES) {
    const controller = new CanonicalRunController(
      fixturePort({ list: canonicalListPayload(canonicalRunRow({ status })) }),
    );
    const list = await controller.listRuns();
    assert.equal(list.ok, true, status);
  }

  for (const hostile of [
    'live',
    'succeeded',
    'WAITING_APPROVAL',
    'waiting',
    'completed ',
    42,
    null,
    undefined,
    [],
  ]) {
    const controller = new CanonicalRunController(
      fixturePort({ list: canonicalListPayload(canonicalRunRow({ status: hostile })) }),
    );
    const list = await controller.listRuns();
    assert.equal(list.ok, false, JSON.stringify(hostile));
    assert.equal(list.errorCode, 'invalid_run_payload');
    assert.deepEqual(list.runs, []);
  }
});

test('#3436 B3a result summary is bounded to the server bound, never widened', async () => {
  const long = '가'.repeat(MAX_RUN_RESULT_SUMMARY_CHARS + 500);
  const controller = new CanonicalRunController(
    fixturePort({
      list: canonicalListPayload(canonicalRunRow({ result_summary: long })),
    }),
  );
  const list = await controller.listRuns();
  assert.equal(list.ok, true);
  assert.equal(list.runs[0]?.resultSummary?.length, MAX_RUN_RESULT_SUMMARY_CHARS);

  const absent = new CanonicalRunController(
    fixturePort({ list: canonicalListPayload(canonicalRunRow({ result_summary: null })) }),
  );
  const list2 = await absent.listRuns();
  assert.equal(list2.runs[0]?.resultSummary, null);

  const malformed = new CanonicalRunController(
    fixturePort({ list: canonicalListPayload(canonicalRunRow({ result_summary: 42 })) }),
  );
  const list3 = await malformed.listRuns();
  assert.equal(list3.ok, false);
  assert.equal(list3.errorCode, 'invalid_run_payload');
});

test('#3436 B3a artifact metadata is bounded to a reference projection', async () => {
  const withArtifact = new CanonicalRunController(
    fixturePort({
      list: canonicalListPayload(
        canonicalRunRow({
          artifact: {
            document_id: 'doc_' + '2'.repeat(24),
            filename: 'a'.repeat(400) + '.docx',
            media_type: 'application/msword',
          },
        }),
      ),
    }),
  );
  const list = await withArtifact.listRuns();
  assert.equal(list.ok, true);
  assert.equal(list.runs[0]?.artifact?.filename.length, 256);
  assert.equal(list.runs[0]?.artifact?.documentId, 'doc_' + '2'.repeat(24));

  const withoutArtifact = new CanonicalRunController(
    fixturePort({ list: canonicalListPayload(canonicalRunRow({ artifact: null })) }),
  );
  const list2 = await withoutArtifact.listRuns();
  assert.equal(list2.runs[0]?.artifact, null);

  for (const malformed of [
    'quote.docx',
    42,
    [],
    { document_id: '' },
    { document_id: 42 },
    { filename: 'quote.docx' },
    // #3436 correction: a widened canonical artifact fails closed at the
    // parser — it is never silently cleaned into a valid projection. The raw
    // private values below are fixtures, not expected outputs: an assertion
    // message that echoed them would be the leak this rule prevents.
    { document_id: 'doc_' + '1'.repeat(24), filename: 'a.docx', media_type: 'application/msword', extra: 'anything' },
    { document_id: 'doc_' + '1'.repeat(24), filename: 'a.docx', media_type: 'application/msword', session_id: 'unexpected-private-ref' },
    { document_id: 'doc_' + '1'.repeat(24), filename: 'a.docx', media_type: 'application/msword', credential: 'x' },
    { document_id: 'doc_' + '1'.repeat(24), filename: 'a.docx', media_type: 'application/msword', path: 'C:/Windows/win.ini' },
    // Ambiguous duplicate aliases are a shape error, not a coincidence.
    { document_id: 'doc_a', documentId: 'doc_b', filename: 'a.docx', media_type: 'application/msword' },
    { document_id: 'doc_a', filename: 'a.docx', media_type: 'application/msword', mediaType: 'image/png' },
    // The server wire shape is snake_case only (`history._run_history_public`);
    // a pure camelCase artifact is not a legitimate server payload, whatever
    // the internal projection calls its fields after parsing.
    { documentId: 'doc_' + '1'.repeat(24), filename: 'a.docx', media_type: 'application/msword' },
    { documentId: 'doc_' + '1'.repeat(24), filename: 'a.docx', mediaType: 'application/msword' },
    { document_id: 'doc_' + '1'.repeat(24), filename: 'a.docx', mediaType: 'application/msword' },
    // #3469 CENTRAL correction: the camelCase spelling was never a server
    // input shape. Any payload carrying it — even with the other keys correct
    // — fails closed rather than being accepted as a widened contract.
    { document_id: 'doc_' + '1'.repeat(24), documentId: 'doc_' + '1'.repeat(24), filename: 'a.docx', media_type: 'application/msword' },
  ]) {
    const controller = new CanonicalRunController(
      fixturePort({ list: canonicalListPayload(canonicalRunRow({ artifact: malformed })) }),
    );
    const list3 = await controller.listRuns();
    assert.equal(list3.ok, false, malformed === null || typeof malformed === 'object' ? 'object' : String(malformed));
    assert.equal(list3.errorCode, 'invalid_run_payload');
  }
});

test('#3436 B3a unknown or malformed canonical payload fails closed', async () => {
  for (const malformed of [
    null,
    undefined,
    'a string payload',
    42,
    [],
    {},
    { ok: true },
    { runs: 'nope' },
    { runs: ['a string row'] },
    { runs: [null] },
    { runs: [{ run_id: 'not a run id', status: 'completed' }] },
    { runs: [{ run_id: CANONICAL_RUN_ID }] },
    { runs: [canonicalRunRow({ run_id: null })] },
    { runs: [canonicalRunRow(), 'a string row'] },
    { runs: [canonicalRunRow({ session: 'chat' })] },
    { runs: [canonicalRunRow({ session: { conversation_id: 'conv_fixture_3084_a' } })] },
    { runs: [canonicalRunRow({ session: { conversation_id: 'chat_' + 'A'.repeat(32) } })] },
    { runs: [canonicalRunRow({ workspace_id: 'bad workspace!' })] },
    { runs: [canonicalRunRow({ workspace_id: 42 })] },
  ]) {
    const controller = new CanonicalRunController(fixturePort({ list: malformed }));
    const rejected = await controller.listRuns();
    assert.equal(rejected.ok, false, JSON.stringify(malformed));
    assert.equal(rejected.errorCode, 'invalid_run_payload');
    assert.deepEqual(rejected.runs, []);
  }

  // An owner with no runs is a valid canonical answer, not a failure.
  const empty = new CanonicalRunController(fixturePort({ list: { ok: true, runs: [] } }));
  const emptyList = await empty.listRuns();
  assert.equal(emptyList.ok, true);
  assert.deepEqual(emptyList.runs, []);
});

test('#3436 B3a unknown payload fields cannot widen the projection authority', async () => {
  const controller = new CanonicalRunController(
    fixturePort({
      list: {
        ok: true,
        runs: [
          canonicalRunRow({
            // A hostile payload cannot smuggle extra authority fields into the
            // bounded projection: only the closed field set is carried.
            commands: ['rm -rf /'],
            approval_token: 'secret',
            download_url: 'file:///C:/Windows',
            mutate: true,
          }),
        ],
      },
    }),
  );
  const list = await controller.listRuns();
  assert.equal(list.ok, true);
  assert.deepEqual(Object.keys(list.runs[0] ?? {}).sort(), [
    'action',
    'artifact',
    'channel',
    'conversationId',
    'createdAt',
    'resultSummary',
    'runId',
    'status',
    'title',
    'updatedAt',
    'workspaceId',
  ]);
});

test('#3436 B3a bounded list: the canonical 30-run bound is mirrored', async () => {
  assert.equal(MAX_CANONICAL_RUNS, 30);
  assert.equal(MAX_RUN_RESULT_SUMMARY_CHARS, 200);

  const many = {
    ok: true,
    runs: Array.from({ length: MAX_CANONICAL_RUNS + 10 }, (_, index) =>
      canonicalRunRow({ run_id: `run_${index.toString(16).padStart(24, '0')}` }),
    ),
  };
  const controller = new CanonicalRunController(fixturePort({ list: many }));
  const list = await controller.listRuns();
  assert.equal(list.ok, true);
  assert.equal(list.runs.length, MAX_CANONICAL_RUNS);
});

test('#3436 B3a controller surface has no persistence, no mutation, no passthrough', () => {
  const controller = new CanonicalRunController(new UnconfiguredCanonicalRunPort());
  const own = Object.getOwnPropertyNames(controller);
  assert.equal(own.includes('localStorage'), false);
  assert.equal(own.some((name) => /store|cache|persist|database|fs|file/i.test(name)), false);

  const proto = Object.getOwnPropertyNames(Object.getPrototypeOf(controller));
  const surface = proto.filter((name) => name !== 'constructor');
  assert.equal(surface.includes('listRuns'), true);
  assert.equal(surface.includes('readRun'), true);
  // READ_ONLY=YES: no mutation capability exists on the projection surface.
  for (const forbidden of ['createRun', 'createTask', 'cancelRun', 'retryRun', 'approve', 'resume', 'mutate', 'fetch', 'invoke', 'request']) {
    assert.equal(surface.includes(forbidden), false, forbidden);
  }

  // The port seam is list-only; there is no arbitrary route passthrough.
  const port = new UnconfiguredCanonicalRunPort();
  const portSurface = Object.getOwnPropertyNames(Object.getPrototypeOf(port))
    .filter((name) => name !== 'constructor');
  assert.deepEqual(portSurface, ['listRuns']);
  assert.equal(Object.getOwnPropertyNames(port).includes('configured'), true);
});
