import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {Linking} from 'react-native';

import {
  ANDROID_HANDOFF_SECRET_HEADER,
  ENDPOINTS,
} from '../api/config';
import {ApiError, apiRequest, apiRequestRaw} from '../api/http';
import {
  AndroidHandoffCreated,
  AndroidHandoffStatus,
  AuthStatus,
  PublicUser,
  Tier,
} from '../api/types';
import {
  clearSessionCookie,
  extractSessionCookie,
  loadSessionCookie,
  setSessionCookie,
} from './session';

export type HandoffStatus =
  | 'idle'
  | 'awaiting_login'
  | 'awaiting_confirmation'
  | 'ready'
  | 'claimed'
  | 'cancelled'
  | 'expired'
  | 'error';

export interface HandoffState {
  handoffId: string;
  userCode: string;
  authorizationUrl: string;
  status: HandoffStatus;
  message?: string;
}

export interface AuthContextValue {
  ready: boolean;
  signedIn: boolean;
  user: PublicUser | null;
  memberGrade: Tier;
  modelRequiresSession: boolean;
  status: AuthStatus | null;
  handoff: HandoffState | null;
  signInWithGoogle: () => Promise<void>;
  signInWithPassword: (identifier: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
  clearHandoff: () => void;
  error: string | null;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const HANDOFF_POLL_INTERVAL_MS = 2000;

export function AuthProvider({children}: {children: React.ReactNode}): React.JSX.Element {
  const [ready, setReady] = useState(false);
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [handoff, setHandoff] = useState<HandoffState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      if (pollTimer.current) {
        clearTimeout(pollTimer.current);
      }
    };
  }, []);

  const refresh = useCallback(async () => {
    try {
      const next = await apiRequest<AuthStatus>(ENDPOINTS.authStatus);
      if (mounted.current) {
        setStatus(next);
        setError(null);
      }
    } catch (err) {
      if (mounted.current) {
        setStatus(null);
        setError(
          err instanceof ApiError ? err.message : '인증 상태를 확인하지 못했습니다.',
        );
      }
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await loadSessionCookie();
      if (cancelled) {
        return;
      }
      await refresh();
      if (!cancelled && mounted.current) {
        setReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  /** Capture the session cookie the existing server just issued. */
  const adoptSessionCookie = useCallback(async (response: Response): Promise<boolean> => {
    const cookie = extractSessionCookie(response.headers);
    if (cookie) {
      await setSessionCookie(cookie);
      return true;
    }
    return false;
  }, []);

  const signInWithPassword = useCallback(
    async (identifier: string, password: string) => {
      setError(null);
      const response = await apiRequestRaw(ENDPOINTS.passwordLogin, {
        method: 'POST',
        body: {identifier, password},
        anonymous: true,
      });
      const text = await response.text();
      if (!response.ok) {
        let message = '로그인에 실패했습니다.';
        try {
          const parsed = JSON.parse(text) as {error?: {message?: string}};
          if (parsed?.error?.message) {
            message = parsed.error.message;
          }
        } catch {
          // keep the fallback message
        }
        throw new ApiError(response.status, 'invalid_credentials', message);
      }
      const adopted = await adoptSessionCookie(response);
      if (!adopted) {
        throw new ApiError(
          response.status,
          'session_cookie_missing',
          '로그인 세션을 저장하지 못했습니다. 다시 시도해 주세요.',
        );
      }
      await refresh();
    },
    [adoptSessionCookie, refresh],
  );

  const claimHandoff = useCallback(
    async (state: HandoffState, secret: string): Promise<boolean> => {
      const response = await apiRequestRaw(
        ENDPOINTS.androidHandoffClaim(state.handoffId),
        {
          method: 'POST',
          headers: {[ANDROID_HANDOFF_SECRET_HEADER]: secret},
          body: {user_code: state.userCode},
          anonymous: true,
        },
      );
      if (response.status === 409) {
        // Still waiting for the browser-side confirmation.
        return false;
      }
      if (!response.ok) {
        const text = await response.text();
        let message = '로그인을 완료하지 못했습니다.';
        let code = 'android_handoff_failed';
        try {
          const parsed = JSON.parse(text) as {error?: {code?: string; message?: string}};
          if (parsed?.error?.message) {
            message = parsed.error.message;
          }
          if (parsed?.error?.code) {
            code = parsed.error.code;
          }
        } catch {
          // keep the fallback message
        }
        throw new ApiError(response.status, code, message);
      }
      const adopted = await adoptSessionCookie(response);
      if (!adopted) {
        throw new ApiError(
          response.status,
          'session_cookie_missing',
          '로그인 세션을 저장하지 못했습니다. 다시 시도해 주세요.',
        );
      }
      return true;
    },
    [adoptSessionCookie],
  );

  const pollHandoff = useCallback(
    async (state: HandoffState, secret: string) => {
      try {
        const next = await apiRequest<AndroidHandoffStatus>(
          ENDPOINTS.androidHandoffById(state.handoffId),
          {headers: {[ANDROID_HANDOFF_SECRET_HEADER]: secret}, anonymous: true},
        );

        if (!mounted.current) {
          return;
        }

        if (next.status === 'expired' || next.status === 'cancelled') {
          setHandoff({...state, status: 'expired'});
          setError('로그인 시간이 만료되었습니다. 다시 시도해 주세요.');
          return;
        }

        if (next.status === 'claimed') {
          await refresh();
          if (mounted.current) {
            setHandoff(null);
          }
          return;
        }

        if (next.status === 'awaiting_confirmation' || next.status === 'ready') {
          const claimed = await claimHandoff({...state, status: next.status}, secret);
          if (claimed) {
            await refresh();
            if (mounted.current) {
              setHandoff(null);
            }
            return;
          }
        }

        if (mounted.current) {
          setHandoff({...state, status: next.status as HandoffStatus});
        }
      } catch (err) {
        if (err instanceof ApiError && err.status === 410) {
          if (mounted.current) {
            setHandoff({...state, status: 'expired'});
            setError('로그인 시간이 만료되었습니다. 다시 시도해 주세요.');
          }
          return;
        }
        if (mounted.current) {
          setHandoff({
            ...state,
            status: 'error',
            message: err instanceof Error ? err.message : '로그인을 확인하지 못했습니다.',
          });
        }
        return;
      }

      if (mounted.current) {
        pollTimer.current = setTimeout(() => {
          void pollHandoff(state, secret);
        }, HANDOFF_POLL_INTERVAL_MS);
      }
    },
    [claimHandoff, refresh],
  );

  const signInWithGoogle = useCallback(async () => {
    setError(null);
    const created = await apiRequest<AndroidHandoffCreated>(ENDPOINTS.androidHandoff, {
      method: 'POST',
      body: {},
      anonymous: true,
    });

    const state: HandoffState = {
      handoffId: created.handoff_id,
      userCode: created.user_code,
      authorizationUrl: created.authorization_url,
      status: 'awaiting_login',
    };
    setHandoff(state);

    const supported = await Linking.canOpenURL(created.authorization_url);
    if (!supported) {
      setHandoff({...state, status: 'error', message: '브라우저를 열 수 없습니다.'});
      return;
    }
    await Linking.openURL(created.authorization_url);

    void pollHandoff(state, created.claim_secret);
  }, [pollHandoff]);

  const signOut = useCallback(async () => {
    setError(null);
    try {
      await apiRequest(ENDPOINTS.authLogout, {method: 'POST'});
    } catch {
      // The local session is cleared even when the server call fails.
    }
    await clearSessionCookie();
    setHandoff(null);
    await refresh();
  }, [refresh]);

  const clearHandoff = useCallback(() => {
    if (pollTimer.current) {
      clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
    setHandoff(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      ready,
      signedIn: Boolean(status?.authenticated),
      user: status?.user ?? null,
      memberGrade: (status?.member_grade as Tier) ?? 'free',
      modelRequiresSession: Boolean(status?.model_requires_session),
      status,
      handoff,
      signInWithGoogle,
      signInWithPassword,
      signOut,
      refresh,
      clearHandoff,
      error,
    }),
    [
      ready,
      status,
      handoff,
      signInWithGoogle,
      signInWithPassword,
      signOut,
      refresh,
      clearHandoff,
      error,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error('useAuth must be used inside an AuthProvider');
  }
  return value;
}
