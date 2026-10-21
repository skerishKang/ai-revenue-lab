import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import {padiemApi} from '../api/padiem';
import {ApiError} from '../api/http';
import {ChatMessage, Tier} from '../api/types';
import {useAuth} from '../auth/AuthContext';

export type ProductMode = 'chat' | 'claw';

export interface ConversationContextValue {
  mode: ProductMode;
  setMode: (mode: ProductMode) => void;

  messages: ChatMessage[];
  conversationId: string | null;
  projectId: string | null;

  tier: Tier;
  allowedTiers: Tier[];
  adminAvailable: boolean | null;
  tierLoading: boolean;
  tierError: string | null;
  selectTier: (tier: Tier) => Promise<void>;

  streaming: boolean;
  sending: boolean;
  error: string | null;
  clearError: () => void;

  send: (text: string) => Promise<void>;
  cancel: () => void;
  reset: () => void;
  openConversation: (conversationId: string) => Promise<void>;

  deviceId: string | null;
  setDeviceId: (deviceId: string | null) => void;
}

const ConversationContext = createContext<ConversationContextValue | null>(null);

export function ConversationProvider({
  children,
}: {
  children: React.ReactNode;
}): React.JSX.Element {
  const {signedIn, memberGrade} = useAuth();
  const [mode, setMode] = useState<ProductMode>('chat');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [tier, setTier] = useState<Tier>('free');
  const [allowedTiers, setAllowedTiers] = useState<Tier[]>(['free']);
  const [adminAvailable, setAdminAvailable] = useState<boolean | null>(null);
  const [tierLoading, setTierLoading] = useState(false);
  const [tierError, setTierError] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deviceId, setDeviceId] = useState<string | null>(null);

  const abortRef = useRef<(() => void) | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      abortRef.current?.();
    };
  }, []);

  // Load the account's server-verified tier permissions.
  useEffect(() => {
    let cancelled = false;
    if (!signedIn) {
      setAllowedTiers(['free']);
      setAdminAvailable(null);
      setTier(memberGrade ?? 'free');
      return () => {
        cancelled = true;
      };
    }
    (async () => {
      try {
        const selection = await padiemApi.modelSelection();
        if (cancelled || !mounted.current) {
          return;
        }
        setAllowedTiers(selection.allowed_tiers ?? ['free']);
        setAdminAvailable(selection.admin_available ?? null);
        const next =
          selection.restorable_tier ?? selection.stored_tier ?? memberGrade ?? 'free';
        setTier(next);
      } catch {
        if (!cancelled && mounted.current) {
          setAllowedTiers([memberGrade ?? 'free']);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [signedIn, memberGrade]);

  const selectTier = useCallback(async (next: Tier) => {
    setTierError(null);
    const previous = tier;
    setTier(next);
    try {
      const result = await padiemApi.saveModelSelection(next);
      if (!mounted.current) {
        return;
      }
      setAllowedTiers(result.allowed_tiers ?? ['free']);
      setAdminAvailable(result.admin_available ?? null);
    } catch (err) {
      if (!mounted.current) {
        return;
      }
      setTier(previous);
      setTierError(
        err instanceof ApiError ? err.message : 'AI 등급을 저장하지 못했습니다.',
      );
    }
  }, [tier]);

  const cancel = useCallback(() => {
    abortRef.current?.();
    abortRef.current = null;
    if (mounted.current) {
      setStreaming(false);
      setSending(false);
    }
  }, []);

  const reset = useCallback(() => {
    cancel();
    setMessages([]);
    setConversationId(null);
    setProjectId(null);
    setError(null);
  }, [cancel]);

  const openConversation = useCallback(async (id: string) => {
    setError(null);
    try {
      const response = await padiemApi.conversation(id);
      const conversation = response.conversation;
      const rows = Array.isArray(conversation.messages) ? conversation.messages : [];
      setMessages(
        rows
          .filter(
            (row): row is ChatMessage =>
              Boolean(row) &&
              (row.role === 'user' || row.role === 'assistant') &&
              typeof row.content === 'string',
          )
          .map(row => ({role: row.role, content: row.content})),
      );
      setConversationId(conversation.id);
      setProjectId(
        typeof conversation.project_id === 'string' ? conversation.project_id : null,
      );
    } catch (err) {
      if (mounted.current) {
        setError(
          err instanceof ApiError ? err.message : '대화를 불러오지 못했습니다.',
        );
      }
    }
  }, []);

  const send = useCallback(
    async (text: string) => {
      const content = text.trim();
      if (!content || sending || streaming) {
        return;
      }

      const userMessage: ChatMessage = {role: 'user', content};
      const outbound = [...messages, userMessage];

      setMessages(outbound);
      setSending(true);
      setError(null);

      const assistantIndex = outbound.length;
      setMessages([...outbound, {role: 'assistant', content: ''}]);

      let accumulated = '';
      const appendDelta = (delta: string): void => {
        if (!mounted.current) {
          return;
        }
        accumulated += delta;
        setMessages(current => {
          const next = [...current];
          while (next.length <= assistantIndex) {
            next.push({role: 'assistant', content: ''});
          }
          next[assistantIndex] = {role: 'assistant', content: accumulated};
          return next;
        });
      };

      const request = {
        messages: outbound,
        tier,
        conversationId,
        projectId,
        deviceId,
      };

      try {
        const abort =
          mode === 'claw'
            ? await padiemApi.streamClawGeneral(request, {
                onDelta: appendDelta,
                onDone: payload => {
                  if (payload.conversation_id) {
                    setConversationId(payload.conversation_id);
                  }
                },
                onError: err => {
                  if (mounted.current) {
                    setError(err.message);
                  }
                },
              })
            : await padiemApi.streamChat(request, {
                onDelta: appendDelta,
                onDone: payload => {
                  if (payload.conversation_id) {
                    setConversationId(payload.conversation_id);
                  }
                },
                onError: err => {
                  if (mounted.current) {
                    setError(err.message);
                  }
                },
              });
        abortRef.current = abort;
        setStreaming(true);
        setSending(false);
      } catch (err) {
        if (mounted.current) {
          setSending(false);
          setStreaming(false);
          setError(
            err instanceof ApiError ? err.message : '답변을 불러오지 못했습니다.',
          );
          setMessages(outbound);
        }
      }
    },
    [conversationId, deviceId, messages, mode, projectId, sending, streaming, tier],
  );

  const value = useMemo<ConversationContextValue>(
    () => ({
      mode,
      setMode,
      messages,
      conversationId,
      projectId,
      tier,
      allowedTiers,
      adminAvailable,
      tierLoading,
      tierError,
      selectTier,
      streaming,
      sending,
      error,
      clearError: () => setError(null),
      send,
      cancel,
      reset,
      openConversation,
      deviceId,
      setDeviceId,
    }),
    [
      mode,
      messages,
      conversationId,
      projectId,
      tier,
      allowedTiers,
      adminAvailable,
      tierLoading,
      tierError,
      selectTier,
      streaming,
      sending,
      error,
      send,
      cancel,
      reset,
      openConversation,
      deviceId,
    ],
  );

  return (
    <ConversationContext.Provider value={value}>{children}</ConversationContext.Provider>
  );
}

export function useConversation(): ConversationContextValue {
  const value = useContext(ConversationContext);
  if (!value) {
    throw new Error('useConversation must be used inside a ConversationProvider');
  }
  return value;
}
