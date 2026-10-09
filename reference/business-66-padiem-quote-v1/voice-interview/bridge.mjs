/* B66 · Quote Beta — the mount layer for the reused Global Classroom interview voice
   engine (#3404).
 *
 * This file contains no speech algorithm, no Gemini protocol and no state machine. The
 * transcription engine is `upstream/hooks/useInterviewLive.ts`, vendored byte-identical
 * from skerishKang/global-classroom (see PROVENANCE.json). Everything below is the small
 * React seam B66 needs because the quote app is a classic-script page: mount the hook,
 * publish what it reports, and hand back its own start/stop so the microphone controls
 * stay the upstream ones.
 *
 * Deliberate omissions, per the owner's decision:
 *   - translationTargets: []  → no Live Translate session is ever opened, so no
 *                                translation token is minted and no extra provider call
 *                                happens. The upstream per-utterance identity still works,
 *                                and B66 uses it to keep one submit per utterance.
 *   - no detectLanguage       → the engine's own languageCode is the only source.
 *   - Groq is refused: the moment the upstream engine reports its groq backend, this layer
 *     stops the session instead of letting an unapproved paid fallback run.
 */
import { createElement, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { useInterviewLive } from './upstream/hooks/useInterviewLive.ts';

function InterviewVoiceBridge({ api }) {
  const engine = useInterviewLive({
    translationTargets: [],
    onInterimTranscript: (text) => api.publish({ kind: 'interim', text: String(text || '') }),
    onFinalTranscript: (text, utteranceId, languageCode) => api.publish({
      kind: 'final',
      text: String(text || ''),
      utteranceId: String(utteranceId || ''),
      languageCode: typeof languageCode === 'string' ? languageCode : ''
    }),
    onUtteranceStart: (utteranceId) => api.publish({ kind: 'utterance', utteranceId: String(utteranceId || '') }),
    onLiveTranslation: () => {},
    onWarning: (message) => api.publish({ kind: 'warning', message: String(message || '') }),
    onFatalError: (message) => api.publish({ kind: 'fatal', message: String(message || '') })
  });

  /* Engine state is read, never rewritten: start/stop come from the upstream hook. */
  useEffect(() => {
    if (engine.backend === 'groq') {
      api.publish({
        kind: 'refused',
        reason: 'groq_fallback_disabled',
        message: '브라우저 음성 인식까지 사용할 수 없어 음성 입력을 멈췄습니다. 텍스트로 입력해 주세요.'
      });
      engine.stop();
      return;
    }
    api.publish({ kind: 'engine', status: engine.status, backend: engine.backend });
  }, [engine.backend, engine.status, engine]);

  useEffect(() => {
    api.setEngine({ start: engine.start, stop: engine.stop });
    return () => api.setEngine(null);
  }, [api, engine.start, engine.stop]);

  return null;
}

export function createVoiceApi(handlers) {
  const listeners = handlers && typeof handlers.publish === 'function' ? handlers : { publish: () => {} };
  let engine = null;
  return {
    publish: (event) => {
      try {
        listeners.publish(event);
      } catch (error) {
        /* A page-side listener must never take the engine down with it. */
        if (typeof console !== 'undefined' && console.warn) console.warn('b66_voice_listener_error', error);
      }
    },
    setEngine: (next) => { engine = next; },
    start: () => (engine ? engine.start() : Promise.reject(new Error('voice_engine_not_mounted'))),
    stop: () => { if (engine) engine.stop(); return { stopped: true }; },
    isMounted: () => engine !== null
  };
}

export function mountInterviewVoice(api, container) {
  const root = createRoot(container);
  root.render(createElement(InterviewVoiceBridge, { api }));
  return {
    unmount: () => root.unmount()
  };
}

globalThis.B66VoiceInterview = {
  mount: mountInterviewVoice,
  createApi: createVoiceApi,
  ENGINE: 'global-classroom/useInterviewLive',
  UPSTREAM_SHA: '299c8e7830f6e4aa0c5202ca5591f240487c5c38'
};
