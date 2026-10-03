import test from 'node:test';
import assert from 'node:assert/strict';

import {
  CanonicalConversationController,
} from '../src/conversation/canonical-conversation.js';
import {
  createDesktopCanonicalConversationPort,
  createDesktopConversationHttpTransport,
  DesktopAuthenticatedCanonicalConversationPort,
  DEVICE_SESSION_BINDING_REF_HEADER,
  DEVICE_SESSION_CREDENTIAL_HEADER,
  DEVICE_SESSION_ID_HEADER,
  noDeviceSessionMaterialYet,
  validateDeviceSessionMaterial,
} from '../src/conversation/desktop-canonical-conversation-port.js';
import type {
  CanonicalConversationHttpResponse,
  CanonicalConversationHttpTransport,
  CanonicalDeviceSessionMaterial,
  DeviceSessionMaterialProvider,
} from '../src/conversation/desktop-canonical-conversation-port.js';

const CANONICAL_ID = 'chat_' + 'a'.repeat(32);
const OTHER_CANONICAL_ID = 'chat_' + 'b'.repeat(32);
const MATERIAL: CanonicalDeviceSessionMaterial = {
  sessionId: 'sess.3436.b2c.test',
  bindingRef: 'bind.3436.b2c.test',
  credentialB64: 'Y2xvdWRmbGFyZS1kby1iMjM2LXRlc3QtY3JlZGVudGlhbA==',
};

const CANONICAL_LIST = {
  conversations: [
    {
      id: CANONICAL_ID,
      title: 'same conversation',
      created_at: '2026-10-01T00:00:00Z',
      updated_at: '2026-10-02T00:00:00Z',
    },
  ],
};

const CANONICAL_DETAIL = {
  conversation: {
    id: CANONICAL_ID,
    title: 'same conversation',
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-02T00:00:00Z',
    messages: [
      { role: 'user', content: 'hello from Web' },
      { role: 'assistant', content: 'hello from canonical transcript' },
    ],
  },
};

interface RecordedRequest {
  url: string;
  method: string;
  headers: Record<string, string>;
}

function transportRecording(
  status: number,
  payload: unknown,
  requests: RecordedRequest[],
): CanonicalConversationHttpTransport {
  const respond = (url: string, headers: Record<string, string>): CanonicalConversationHttpResponse => {
    requests.push({ url, method: 'GET', headers });
    if (status !== 200) throw new Error(`refused (${status})`);
    return { status, payload };
  };
  return {
    async listConversations(material) {
      return respond('https://chat.example.test/api/desktop/conversations', {
        accept: 'application/json',
        [DEVICE_SESSION_ID_HEADER]: material.sessionId,
        [DEVICE_SESSION_BINDING_REF_HEADER]: material.bindingRef,
        [DEVICE_SESSION_CREDENTIAL_HEADER]: material.credentialB64,
      });
    },
    async readConversation(material, conversationId) {
      return respond(
        `https://chat.example.test/api/desktop/conversations/${conversationId}`,
        {
          accept: 'application/json',
          [DEVICE_SESSION_ID_HEADER]: material.sessionId,
          [DEVICE_SESSION_BINDING_REF_HEADER]: material.bindingRef,
          [DEVICE_SESSION_CREDENTIAL_HEADER]: material.credentialB64,
        },
      );
    },
  };
}

function materialProviding(material: CanonicalDeviceSessionMaterial | null): DeviceSessionMaterialProvider {
  return async () => material;
}

test('#3436 B2c valid device session lists the same canonical conversations', async () => {
  const requests: RecordedRequest[] = [];
  const controller = new CanonicalConversationController(
    new DesktopAuthenticatedCanonicalConversationPort({
      materialProvider: materialProviding(MATERIAL),
      transport: transportRecording(200, CANONICAL_LIST, requests),
    }),
  );
  assert.equal(controller.configured, true);

  const list = await controller.listConversations();
  assert.equal(list.ok, true);
  assert.equal(list.errorCode, null);
  assert.equal(list.conversations.length, 1);
  assert.equal(list.conversations[0]?.id, CANONICAL_ID);
  assert.equal(requests.length, 1);
});

test('#3436 B2c valid device session reads the same canonical transcript', async () => {
  const requests: RecordedRequest[] = [];
  const controller = new CanonicalConversationController(
    new DesktopAuthenticatedCanonicalConversationPort({
      materialProvider: materialProviding(MATERIAL),
      transport: transportRecording(200, CANONICAL_DETAIL, requests),
    }),
  );

  const read = await controller.readConversation({ conversationId: CANONICAL_ID });
  assert.equal(read.ok, true);
  assert.equal(read.conversation?.id, CANONICAL_ID);
  assert.deepEqual(read.conversation?.messages, CANONICAL_DETAIL.conversation.messages);
});

test('#3436 B2c an authentication refusal stays fail-closed with no fallback', async () => {
  for (const status of [401, 403, 500, 503]) {
    const requests: RecordedRequest[] = [];
    const controller = new CanonicalConversationController(
      new DesktopAuthenticatedCanonicalConversationPort({
        materialProvider: materialProviding(MATERIAL),
        transport: transportRecording(status, {}, requests),
      }),
    );
    const list = await controller.listConversations();
    assert.equal(list.ok, false);
    assert.equal(list.errorCode, 'canonical_conversation_unavailable');
    assert.deepEqual(list.conversations, []);
    const read = await controller.readConversation({ conversationId: CANONICAL_ID });
    assert.equal(read.ok, false);
    assert.equal(read.errorCode, 'canonical_conversation_unavailable');
    assert.equal(read.conversation, null);
  }
});

test('#3436 B2c no trusted local boundary means no material and no read', async () => {
  const port = new DesktopAuthenticatedCanonicalConversationPort({
    materialProvider: noDeviceSessionMaterialYet,
    transport: transportRecording(200, CANONICAL_LIST, []),
  });
  const controller = new CanonicalConversationController(port);

  const list = await controller.listConversations();
  assert.equal(list.ok, false);
  assert.equal(list.errorCode, 'canonical_conversation_unavailable');
  assert.deepEqual(list.conversations, []);

  const read = await controller.readConversation({ conversationId: CANONICAL_ID });
  assert.equal(read.ok, false);
  assert.equal(read.errorCode, 'canonical_conversation_unavailable');
  assert.equal(read.conversation, null);
});

test('#3436 B2c malformed material never reaches the transport', async () => {
  const requests: RecordedRequest[] = [];
  const port = new DesktopAuthenticatedCanonicalConversationPort({
    materialProvider: materialProviding({
      sessionId: 'not a safe ref!',
      bindingRef: 'bind.3436.b2c.test',
      credentialB64: MATERIAL.credentialB64,
    }),
    transport: transportRecording(200, CANONICAL_LIST, requests),
  });
  const controller = new CanonicalConversationController(port);

  const list = await controller.listConversations();
  assert.equal(list.ok, false);
  assert.equal(list.errorCode, 'canonical_conversation_unavailable');
  assert.equal(requests.length, 0);
});

test('#3436 B2c no credential or session material ever reaches the renderer projection', async () => {
  const controller = new CanonicalConversationController(
    new DesktopAuthenticatedCanonicalConversationPort({
      materialProvider: materialProviding(MATERIAL),
      transport: transportRecording(200, CANONICAL_LIST, []),
    }),
  );
  const list = await controller.listConversations();
  const serialized = JSON.stringify(list);
  assert.equal(serialized.includes(MATERIAL.credentialB64), false);
  assert.equal(serialized.includes(MATERIAL.sessionId), false);
  assert.equal(serialized.includes(MATERIAL.bindingRef), false);

  const detailController = new CanonicalConversationController(
    new DesktopAuthenticatedCanonicalConversationPort({
      materialProvider: materialProviding(MATERIAL),
      transport: transportRecording(200, CANONICAL_DETAIL, []),
    }),
  );
  const read = await detailController.readConversation({ conversationId: CANONICAL_ID });
  const serializedRead = JSON.stringify(read);
  assert.equal(serializedRead.includes(MATERIAL.credentialB64), false);
  assert.equal(serializedRead.includes(MATERIAL.sessionId), false);
  assert.equal(serializedRead.includes(MATERIAL.bindingRef), false);
});

test('#3436 B2c the production transport issues GET only with the closed headers and no cookie', async () => {
  const requests: Array<{ input: string; init: RequestInit }> = [];
  const fetchImpl = (async (input: string | URL, init?: RequestInit) => {
    requests.push({ input: String(input), init: init ?? {} });
    return new Response(JSON.stringify(CANONICAL_LIST), { status: 200 });
  }) as unknown as typeof fetch;

  const transport = createDesktopConversationHttpTransport({
    baseUrl: 'https://chat.example.test',
    fetchImpl,
  });
  const payload = await transport.listConversations(MATERIAL);
  assert.deepEqual(payload, { status: 200, payload: CANONICAL_LIST });

  assert.equal(requests.length, 1);
  const request = requests[0];
  assert.ok(request, 'the transport must have issued exactly one request');
  assert.equal(request.init.method, 'GET');
  assert.equal(request.input, 'https://chat.example.test/api/desktop/conversations');
  const headers = new Headers(request.init.headers as HeadersInit);
  assert.equal(headers.get('accept'), 'application/json');
  assert.equal(headers.get(DEVICE_SESSION_ID_HEADER), MATERIAL.sessionId);
  assert.equal(headers.get(DEVICE_SESSION_BINDING_REF_HEADER), MATERIAL.bindingRef);
  assert.equal(headers.get(DEVICE_SESSION_CREDENTIAL_HEADER), MATERIAL.credentialB64);
  // No browser cookie path exists on this surface.
  assert.equal(headers.get('cookie'), null);
  assert.equal(request.init.body, undefined);

  await assert.rejects(
    transport.readConversation(MATERIAL, '../../etc/passwd'),
    /canonical id/,
  );
  // A non-200 answer is a refusal, never a projection.
  const refusingFetch = (async () => new Response('no', { status: 401 })) as unknown as typeof fetch;
  const refusingTransport = createDesktopConversationHttpTransport({
    baseUrl: 'https://chat.example.test',
    fetchImpl: refusingFetch,
  });
  await assert.rejects(refusingTransport.listConversations(MATERIAL), /401/);
});

test('#3436 B2c the composition factory keeps the fail-closed default without a chat base URL', async () => {
  const unconfigured = createDesktopCanonicalConversationPort({
    chatBaseUrl: null,
    materialProvider: materialProviding(MATERIAL),
  });
  assert.equal(unconfigured.configured, false);

  const controller = new CanonicalConversationController(unconfigured);
  const list = await controller.listConversations();
  assert.equal(list.ok, false);
  assert.equal(list.errorCode, 'canonical_conversation_unavailable');

  const authenticated = createDesktopCanonicalConversationPort({
    chatBaseUrl: 'https://chat.example.test',
    materialProvider: materialProviding(MATERIAL),
    fetchImpl: (async () => new Response(JSON.stringify(CANONICAL_LIST), { status: 200 })) as unknown as typeof fetch,
  });
  assert.equal(authenticated.configured, true);
});

test('#3436 B2c material validation accepts exactly the canonical shapes', () => {
  assert.equal(validateDeviceSessionMaterial(MATERIAL)?.sessionId, MATERIAL.sessionId);
  assert.equal(validateDeviceSessionMaterial(null), null);
  assert.equal(
    validateDeviceSessionMaterial({ ...MATERIAL, sessionId: '../escape' }),
    null,
  );
  assert.equal(
    validateDeviceSessionMaterial({ ...MATERIAL, credentialB64: 'not base64!!!' }),
    null,
  );
  assert.equal(
    validateDeviceSessionMaterial({ ...MATERIAL, credentialB64: '' }),
    null,
  );
});
