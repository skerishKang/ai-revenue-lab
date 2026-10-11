import test from 'node:test';
import assert from 'node:assert/strict';

import {
  CANONICAL_CONVERSATION_ID_PATTERN,
  CanonicalConversationController,
  MAX_CANONICAL_CONVERSATIONS,
  UnconfiguredCanonicalConversationPort,
} from '../src/conversation/canonical-conversation.js';
import type { CanonicalConversationPort } from '../src/conversation/canonical-conversation.js';

const CANONICAL_ID = 'chat_' + 'a'.repeat(32);
const OTHER_CANONICAL_ID = 'chat_' + 'b'.repeat(32);

function fixturePort(overrides: {
  list?: unknown;
  detail?: unknown;
  failList?: boolean;
  failRead?: boolean;
} = {}): CanonicalConversationPort {
  return {
    configured: true,
    async listConversations() {
      if (overrides.failList) throw new Error('network down');
      return overrides.list ?? { conversations: [] };
    },
    async readConversation(conversationId: string) {
      if (overrides.failRead) throw new Error('network down');
      const detail = overrides.detail;
      if (typeof detail === 'function') {
        return (detail as (id: string) => unknown)(conversationId);
      }
      return detail ?? null;
    },
  };
}

function canonicalDetail(id: string) {
  return {
    conversation: {
      id,
      title: 'same conversation',
      created_at: '2026-10-01T00:00:00Z',
      updated_at: '2026-10-02T00:00:00Z',
      messages: [
        { role: 'user', content: 'hello from Web' },
        { role: 'assistant', content: 'hello from canonical transcript' },
      ],
    },
  };
}

test('#3436 B2b unconfigured port fails closed instead of inventing a conversation', async () => {
  const controller = new CanonicalConversationController(new UnconfiguredCanonicalConversationPort());
  assert.equal(controller.configured, false);

  const list = await controller.listConversations();
  assert.equal(list.ok, false);
  assert.equal(list.errorCode, 'canonical_conversation_unavailable');
  assert.deepEqual(list.conversations, []);

  const read = await controller.readConversation({ conversationId: CANONICAL_ID });
  assert.equal(read.ok, false);
  assert.equal(read.errorCode, 'canonical_conversation_unavailable');
  assert.equal(read.conversation, null);
});

test('#3436 B2b only canonical conversation ids are accepted; caller-shaped ids are refused', async () => {
  const requested: string[] = [];
  const controller = new CanonicalConversationController(
    fixturePort({
      detail: (id: string) => {
        requested.push(id);
        return canonicalDetail(id);
      },
    }),
  );

  for (const hostile of [
    undefined,
    null,
    'src',
    42,
    [],
    { conversationId: 42 },
    { conversationId: 'chat_' + 'A'.repeat(32) },
    { conversationId: 'chat_' + 'a'.repeat(31) },
    { conversationId: 'chat_' + 'a'.repeat(33) },
    { conversationId: 'conv_fixture_3084_a' },
    { conversationId: '../../etc/passwd' },
  ]) {
    const rejected = await controller.readConversation(hostile);
    assert.equal(rejected.ok, false, JSON.stringify(hostile));
    assert.equal(rejected.errorCode, 'invalid_conversation_id');
    assert.equal(rejected.conversation, null);
  }
  assert.deepEqual(requested, [], 'no malformed id may reach the canonical authority');

  const accepted = await controller.readConversation({ conversationId: CANONICAL_ID });
  assert.equal(accepted.ok, true);
  assert.deepEqual(requested, [CANONICAL_ID]);

  // Renderer-shaped extras never widen the request: the port receives exactly
  // the canonical conversation id and nothing else (mirrors the B1 workspace
  // contract where caller-supplied root data cannot replace the main-owned root).
  requested.length = 0;
  const withExtras = await controller.readConversation({
    conversationId: CANONICAL_ID,
    rootPath: 'C:/',
    absolutePath: 'C:/Windows',
  } as unknown);
  assert.equal(withExtras.ok, true);
  assert.deepEqual(requested, [CANONICAL_ID]);
});

test('#3436 B2b same canonical transcript projection, no reshaping', async () => {
  const controller = new CanonicalConversationController(
    fixturePort({ detail: canonicalDetail(CANONICAL_ID) }),
  );
  const read = await controller.readConversation({ conversationId: CANONICAL_ID });
  assert.equal(read.ok, true);
  assert.equal(read.errorCode, null);
  assert.equal(read.conversation?.id, CANONICAL_ID);
  assert.deepEqual(
    read.conversation?.messages.map((m) => [m.role, m.content]),
    [
      ['user', 'hello from Web'],
      ['assistant', 'hello from canonical transcript'],
    ],
  );
});

test('#3436 B2b unknown or malformed canonical payload fails closed', async () => {
  const notFound = new CanonicalConversationController(fixturePort({ detail: null }));
  const missing = await notFound.readConversation({ conversationId: CANONICAL_ID });
  assert.equal(missing.ok, false);
  assert.equal(missing.errorCode, 'conversation_not_found');

  for (const malformed of [
    {},
    { conversation: {} },
    { conversation: { id: 'not-a-canonical-id', messages: [] } },
    { conversation: { id: CANONICAL_ID, messages: 'nope' } },
    { conversation: { id: CANONICAL_ID, messages: [{ role: 'system', content: 'x' }] } },
    { conversation: { id: CANONICAL_ID, messages: [{ role: 'user', content: 42 }] } },
    'a string payload',
  ]) {
    const controller = new CanonicalConversationController(fixturePort({ detail: malformed }));
    const rejected = await controller.readConversation({ conversationId: CANONICAL_ID });
    assert.equal(rejected.ok, false, JSON.stringify(malformed));
    assert.equal(rejected.errorCode, 'invalid_conversation_payload');
    assert.equal(rejected.conversation, null);
  }

  const mismatched = new CanonicalConversationController(
    fixturePort({ detail: canonicalDetail(OTHER_CANONICAL_ID) }),
  );
  const rejected = await mismatched.readConversation({ conversationId: CANONICAL_ID });
  assert.equal(rejected.ok, false);
  assert.equal(rejected.errorCode, 'invalid_conversation_payload');
});

test('#3436 B2b list projection carries canonical ids only and is bounded', async () => {
  const many = {
    conversations: Array.from({ length: MAX_CANONICAL_CONVERSATIONS + 5 }, (_, index) => ({
      id: `chat_${index.toString(16).padStart(32, '0')}`,
      title: `t${index}`,
      created_at: '2026-10-01T00:00:00Z',
      updated_at: '2026-10-02T00:00:00Z',
    })),
  };
  const controller = new CanonicalConversationController(fixturePort({ list: many }));
  const list = await controller.listConversations();
  assert.equal(list.ok, true);
  assert.equal(list.conversations.length, MAX_CANONICAL_CONVERSATIONS);
  assert.equal(
    list.conversations.every((item) => CANONICAL_CONVERSATION_ID_PATTERN.test(item.id)),
    true,
  );

  const malformed = new CanonicalConversationController(
    fixturePort({
      list: { conversations: [{ id: 'local-made-up-id', title: 'x' }] },
    }),
  );
  const rejected = await malformed.listConversations();
  assert.equal(rejected.ok, false);
  assert.equal(rejected.errorCode, 'invalid_conversation_payload');
  assert.deepEqual(rejected.conversations, []);
});

test('#3436 B2b transport failure reports unavailable, never a local conversation', async () => {
  const failingList = new CanonicalConversationController(fixturePort({ failList: true }));
  const list = await failingList.listConversations();
  assert.equal(list.ok, false);
  assert.equal(list.errorCode, 'canonical_conversation_unavailable');

  const failingRead = new CanonicalConversationController(fixturePort({ failRead: true }));
  const read = await failingRead.readConversation({ conversationId: CANONICAL_ID });
  assert.equal(read.ok, false);
  assert.equal(read.errorCode, 'canonical_conversation_unavailable');
  assert.equal(read.conversation, null);
});

test('#3436 B2b controller surface has no persistence and mints no ids', () => {
  const controller = new CanonicalConversationController(new UnconfiguredCanonicalConversationPort());
  const own = Object.getOwnPropertyNames(controller);
  assert.equal(own.includes('localStorage'), false);
  assert.equal(own.some((name) => /store|cache|persist|database/i.test(name)), false);
  // The only id grammar the controller knows is the server's own.
  assert.equal(CANONICAL_CONVERSATION_ID_PATTERN.test('chat_' + 'c'.repeat(32)), true);
  assert.equal(CANONICAL_CONVERSATION_ID_PATTERN.test('chat_' + 'C'.repeat(32)), false);
  assert.equal(CANONICAL_CONVERSATION_ID_PATTERN.test('desktop_' + 'c'.repeat(32)), false);
});
