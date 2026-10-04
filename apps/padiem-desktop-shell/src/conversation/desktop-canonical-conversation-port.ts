/**
 * #3436 B2c — the Desktop's authenticated canonical conversation port.
 *
 * Replaces the B2b fail-closed default as the wired port: the main process now
 * composes a real authenticated port that presents the canonical Local Agent
 * Broker device session to the padiem-chat GET-only Desktop conversation
 * surface. Two seams are injected, both main-process-only:
 *
 *   - `DeviceSessionMaterialProvider` yields the current device session
 *     material (session id, binding ref, credential) at the trusted local
 *     boundary. It never crosses to the renderer: RENDERER_DEVICE_CREDENTIAL=0,
 *     RENDERER_BROKER_SESSION_SECRET=0.
 *   - `CanonicalConversationHttpTransport` performs the bounded GET requests.
 *
 * Fail-closed behaviour is unchanged from B2b: a null material, a refused
 * request, or a non-200 answer all surface as the same "canonical
 * conversation unavailable" presentation — never a temporary local
 * conversation, never a localStorage or filesystem fallback
 * (DESKTOP_LOCAL_CONVERSATION_DATABASE=0, SECOND_CONVERSATION_AUTHORITY=0).
 *
 * No browser cookie is read, stored or forwarded anywhere in this module:
 * BROWSER_PADIEM_SESSION_COOKIE_COPY=0. The transport issues GET requests
 * only — LIST and READ are the whole surface (CREATE=0, DELETE=0,
 * CHAT_WRITE=0).
 */

import type { CanonicalConversationPort } from './canonical-conversation.js';
import { CANONICAL_CONVERSATION_ID_PATTERN, UnconfiguredCanonicalConversationPort } from './canonical-conversation.js';

/** The caller-held canonical device session material. Main-process-only. */
export interface CanonicalDeviceSessionMaterial {
  readonly sessionId: string;
  readonly bindingRef: string;
  readonly credentialB64: string;
}

export type DeviceSessionMaterialProvider = () => Promise<CanonicalDeviceSessionMaterial | null>;

export interface CanonicalConversationHttpResponse {
  readonly status: number;
  readonly payload: unknown;
}

export interface CanonicalConversationHttpTransport {
  listConversations(material: CanonicalDeviceSessionMaterial): Promise<CanonicalConversationHttpResponse>;
  readConversation(
    material: CanonicalDeviceSessionMaterial,
    conversationId: string,
  ): Promise<CanonicalConversationHttpResponse>;
}

/** The closed device-session material headers, mirroring the padiem-chat surface. */
export const DEVICE_SESSION_ID_HEADER = 'x-padiem-device-session-id';
export const DEVICE_SESSION_BINDING_REF_HEADER = 'x-padiem-device-binding-ref';
export const DEVICE_SESSION_CREDENTIAL_HEADER = 'x-padiem-device-credential-b64';

/** Mirrors the canonical safe-reference grammar and the 16 KiB credential bound. */
const SAFE_REF_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$/;
const BASE64_PATTERN = /^[A-Za-z0-9+/]+={0,2}$/;
// ceil((16384 + 2) / 3) * 4 — the base64 length of the 16 KiB raw credential bound.
const MAX_CREDENTIAL_B64_CHARS = Math.ceil((16_384 + 2) / 3) * 4;

const MAX_RESPONSE_JSON_CHARS = 2_000_000;

/**
 * Accepts only material in the exact canonical shapes. A malformed material
 * never reaches the transport, so it can never reach the network.
 */
export function validateDeviceSessionMaterial(
  material: CanonicalDeviceSessionMaterial | null | undefined,
): CanonicalDeviceSessionMaterial | null {
  if (material === null || material === undefined) return null;
  if (typeof material !== 'object') return null;
  const sessionId = (material as { sessionId?: unknown }).sessionId;
  const bindingRef = (material as { bindingRef?: unknown }).bindingRef;
  const credentialB64 = (material as { credentialB64?: unknown }).credentialB64;
  if (typeof sessionId !== 'string' || !SAFE_REF_PATTERN.test(sessionId)) return null;
  if (typeof bindingRef !== 'string' || !SAFE_REF_PATTERN.test(bindingRef)) return null;
  if (
    typeof credentialB64 !== 'string' ||
    !credentialB64 ||
    credentialB64.length > MAX_CREDENTIAL_B64_CHARS ||
    !BASE64_PATTERN.test(credentialB64)
  ) {
    return null;
  }
  return { sessionId, bindingRef, credentialB64 };
}

/**
 * The fail-closed default material provider: no trusted local boundary is
 * attached yet, so there is no material to present. The Desktop conversation
 * surface stays "canonical conversation unavailable" — the honest B2b answer —
 * until the resident-side session channel is composed in a later slice.
 */
export async function noDeviceSessionMaterialYet(): Promise<CanonicalDeviceSessionMaterial | null> {
  return null;
}

/**
 * The production transport over the padiem-chat Desktop conversation surface.
 * GET requests only, with exactly the three closed material headers plus an
 * Accept header — never a Cookie header, never a bearer token, never a body.
 */
export function createDesktopConversationHttpTransport(input: {
  baseUrl: string;
  fetchImpl?: typeof fetch;
}): CanonicalConversationHttpTransport {
  const base = input.baseUrl.replace(/\/+$/, '');
  const fetchImpl = input.fetchImpl ?? fetch;
  async function get(url: string, material: CanonicalDeviceSessionMaterial): Promise<CanonicalConversationHttpResponse> {
    const response = await fetchImpl(url, {
      method: 'GET',
      headers: {
        Accept: 'application/json',
        [DEVICE_SESSION_ID_HEADER]: material.sessionId,
        [DEVICE_SESSION_BINDING_REF_HEADER]: material.bindingRef,
        [DEVICE_SESSION_CREDENTIAL_HEADER]: material.credentialB64,
      },
      redirect: 'error',
    });
    const text = await response.text();
    if (text.length > MAX_RESPONSE_JSON_CHARS) {
      throw new Error('canonical conversation response exceeds the bounded size');
    }
    if (response.status !== 200) {
      throw new Error(`canonical conversation read refused (${response.status})`);
    }
    return { status: response.status, payload: JSON.parse(text) as unknown };
  }
  return {
    async listConversations(material) {
      return get(`${base}/api/desktop/conversations`, material);
    },
    async readConversation(material, conversationId) {
      if (!CANONICAL_CONVERSATION_ID_PATTERN.test(conversationId)) {
        throw new Error('conversation id is not a canonical id');
      }
      return get(`${base}/api/desktop/conversations/${encodeURIComponent(conversationId)}`, material);
    },
  };
}

/**
 * The authenticated port: resolves the caller-held material at the trusted
 * local boundary, then performs the bounded GET through the transport. Any
 * absence or refusal throws, which the B2b controller maps to the unchanged
 * fail-closed "canonical conversation unavailable" presentation.
 */
export class DesktopAuthenticatedCanonicalConversationPort implements CanonicalConversationPort {
  readonly #materialProvider: DeviceSessionMaterialProvider;
  readonly #transport: CanonicalConversationHttpTransport;

  constructor(input: {
    materialProvider: DeviceSessionMaterialProvider;
    transport: CanonicalConversationHttpTransport;
  }) {
    if (typeof input.materialProvider !== 'function') {
      throw new Error('materialProvider must be callable');
    }
    if (input.transport === null || input.transport === undefined) {
      throw new Error('transport is required');
    }
    this.#materialProvider = input.materialProvider;
    this.#transport = input.transport;
  }

  get configured(): boolean {
    return true;
  }

  async listConversations(): Promise<unknown> {
    const material = validateDeviceSessionMaterial(await this.#materialProvider());
    if (material === null) {
      throw new Error('canonical device session material is unavailable');
    }
    const response = await this.#transport.listConversations(material);
    return response.payload;
  }

  async readConversation(conversationId: string): Promise<unknown> {
    const material = validateDeviceSessionMaterial(await this.#materialProvider());
    if (material === null) {
      throw new Error('canonical device session material is unavailable');
    }
    const response = await this.#transport.readConversation(material, conversationId);
    return response.payload;
  }
}

/**
 * The one composition seam main.ts uses. A named chat base URL plus a
 * material provider compose the authenticated port; without a base URL the
 * B2b fail-closed unconfigured port stands. The provider is the trusted local
 * boundary attach point — never a renderer-visible input.
 */
export function createDesktopCanonicalConversationPort(input: {
  chatBaseUrl: string | null;
  materialProvider: DeviceSessionMaterialProvider;
  fetchImpl?: typeof fetch;
}): CanonicalConversationPort {
  if (typeof input.chatBaseUrl !== 'string' || !input.chatBaseUrl.trim()) {
    return new UnconfiguredCanonicalConversationPort();
  }
  return new DesktopAuthenticatedCanonicalConversationPort({
    materialProvider: input.materialProvider,
    transport: createDesktopConversationHttpTransport({
      baseUrl: input.chatBaseUrl,
      fetchImpl: input.fetchImpl,
    }),
  });
}
