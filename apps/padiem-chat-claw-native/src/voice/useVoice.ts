import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {PermissionsAndroid, Platform} from 'react-native';

import {padiemApi} from '../api/padiem';
import {
  GROQ_MIN_CHUNK_MS,
  TranscriptDeduper,
  UtteranceSubmissionGuard,
  VoiceMode,
  makeUtteranceId,
  resolveRecognitionLanguage,
} from './voiceContract';
import {
  PadiemVoice,
  VOICE_CHUNK_EVENT,
  VOICE_SAMPLE_RATE,
  VoiceChunkEvent,
  createVoiceEmitter,
  pcmToWavBase64,
} from './nativeVoice';

export type VoicePhase = 'idle' | 'listening' | 'transcribing' | 'speaking' | 'error';

export interface UseVoiceOptions {
  mode: VoiceMode;
  /** Which product lane the voice route belongs to. */
  product: 'chat' | 'claw';
  /** Display-only preview while the user is still speaking. */
  onInterim?: (text: string) => void;
  /** The authoritative final transcript of the finished utterance. */
  onFinal: (text: string) => void;
  /** M1 sends the dictated text straight away; M2/M3/M4 deliver it to the composer. */
  autoSend?: boolean;
  language?: string;
}

export interface VoiceController {
  phase: VoicePhase;
  interim: string;
  error: string | null;
  available: boolean;
  start: () => Promise<void>;
  stop: () => Promise<void>;
  speak: (text: string) => Promise<void>;
  stopSpeaking: () => Promise<void>;
  reset: () => void;
}

function createSessionId(): string {
  const random = Math.random().toString(36).slice(2, 10);
  return `padiem-voice-${Date.now().toString(36)}-${random}`;
}

/**
 * Native voice session.
 *
 * The state machine follows the shared PADIEM STT contract
 * (`padiem.voice.stt.v1`): an interim preview is display-only, one utterance
 * keeps one deterministic identity, a duplicate final is dropped, and one
 * authoritative utterance is submitted at most once.
 */
export function useVoice(options: UseVoiceOptions): VoiceController {
  const {mode, product, onInterim, onFinal, autoSend = false, language} = options;

  const [phase, setPhase] = useState<VoicePhase>('idle');
  const [interim, setInterim] = useState('');
  const [error, setError] = useState<string | null>(null);

  const sessionId = useRef<string>(createSessionId());
  const generation = useRef(0);
  const turnIndex = useRef(0);
  const deduper = useRef(new TranscriptDeduper());
  const guard = useRef(new UtteranceSubmissionGuard());
  const chunks = useRef<string[]>([]);
  const capturedBytes = useRef(0);
  const lastTranscribedBytes = useRef(0);
  const lastInterimAt = useRef(0);
  const interimTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const emitter = useRef<ReturnType<typeof createVoiceEmitter>>(null);
  const speaking = useRef(false);

  const available = PadiemVoice !== null;

  const stopInterimTimer = useCallback(() => {
    if (interimTimer.current) {
      clearInterval(interimTimer.current);
      interimTimer.current = null;
    }
  }, []);

  const reset = useCallback(() => {
    stopInterimTimer();
    chunks.current = [];
    capturedBytes.current = 0;
    lastTranscribedBytes.current = 0;
    lastInterimAt.current = 0;
    setInterim('');
    setPhase('idle');
  }, [stopInterimTimer]);

  const transcribe = useCallback(
    async (pcmBase64: string, utteranceId: string): Promise<string | null> => {
      const audio = pcmToWavBase64(pcmBase64);
      const result = await padiemApi.voiceTranscribe(
        audio,
        'audio/wav',
        utteranceId,
        product === 'claw',
      );
      const text = typeof result.text === 'string' ? result.text.trim() : '';
      return text.length > 0 ? text : null;
    },
    [product],
  );

  const publishInterim = useCallback(
    async (pcmBase64: string, utteranceId: string) => {
      const transcript = await transcribe(pcmBase64, utteranceId);
      if (!transcript || !mountedRef.current) {
        return;
      }
      // An interim preview is display-only: it is never submitted.
      setInterim(transcript);
      onInterim?.(transcript);
    },
    [onInterim, transcribe],
  );

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      stopInterimTimer();
    };
  }, [stopInterimTimer]);

  const start = useCallback(async () => {
    setError(null);
    if (!PadiemVoice) {
      setError('음성 기능을 현재 사용할 수 없습니다.');
      setPhase('error');
      return;
    }
    if (Platform.OS === 'android') {
      const granted = await PermissionsAndroid.request(
        PermissionsAndroid.PERMISSIONS.RECORD_AUDIO,
      );
      if (granted !== PermissionsAndroid.RESULTS.GRANTED) {
        setError('마이크 권한이 필요합니다.');
        setPhase('error');
        return;
      }
    }

    generation.current += 1;
    turnIndex.current = 0;
    chunks.current = [];
    capturedBytes.current = 0;
    lastTranscribedBytes.current = 0;
    setInterim('');

    try {
      await PadiemVoice.startRecording(VOICE_SAMPLE_RATE);
    } catch (err) {
      setError(err instanceof Error ? err.message : '마이크를 시작하지 못했습니다.');
      setPhase('error');
      return;
    }

    emitter.current = createVoiceEmitter();
    emitter.current?.addListener(VOICE_CHUNK_EVENT, (event: VoiceChunkEvent) => {
      chunks.current.push(event.base64);
      capturedBytes.current += event.byteLength;
      lastInterimAt.current = event.elapsedMs;
    });

    stopInterimTimer();
    interimTimer.current = setInterval(() => {
      void (async () => {
        if (capturedBytes.current <= lastTranscribedBytes.current) {
          return;
        }
        if (lastInterimAt.current - lastTranscribedBytes.current < GROQ_MIN_CHUNK_MS) {
          return;
        }
        const pcm = chunks.current.join('');
        lastTranscribedBytes.current = capturedBytes.current;
        const utteranceId = makeUtteranceId(
          sessionId.current,
          generation.current,
          turnIndex.current,
        );
        try {
          await publishInterim(pcm, utteranceId);
        } catch {
          // An interim failure never breaks the live capture.
        }
      })();
    }, 1000);

    setPhase('listening');
  }, [publishInterim, stopInterimTimer]);

  const stop = useCallback(async () => {
    stopInterimTimer();
    emitter.current?.removeAllListeners(VOICE_CHUNK_EVENT);
    emitter.current = null;

    try {
      await PadiemVoice?.stopRecording();
    } catch {
      // The capture may already be finished.
    }

    setPhase('transcribing');

    const utteranceId = makeUtteranceId(
      sessionId.current,
      generation.current,
      turnIndex.current,
    );

    try {
      const captured = await PadiemVoice?.readCapturedBase64();
      const pcm = captured?.base64 ?? chunks.current.join('');
      if (!pcm) {
        setPhase('idle');
        return;
      }
      const transcript = await transcribe(pcm, utteranceId);
      if (!mountedRef.current) {
        return;
      }
      if (!transcript) {
        setInterim('');
        setPhase('idle');
        return;
      }
      // One deterministic identity per utterance: a duplicate final is dropped
      // and one authoritative utterance is submitted at most once.
      if (!deduper.current.accept({
        utteranceId,
        kind: 'final',
        text: transcript,
        provider: 'gemini_live',
        sequence: turnIndex.current,
      })) {
        return;
      }
      if (!guard.current.claim(utteranceId)) {
        return;
      }
      setInterim('');
      turnIndex.current += 1;
      onFinal(transcript);
      setPhase('idle');
    } catch (err) {
      if (mountedRef.current) {
        setError(err instanceof Error ? err.message : '음성을 인식하지 못했습니다.');
        setPhase('error');
      }
    }
  }, [onFinal, stopInterimTimer, transcribe]);

  const speak = useCallback(async (text: string) => {
    if (!PadiemVoice || !text.trim()) {
      return;
    }
    try {
      speaking.current = true;
      setPhase('speaking');
      const languageTag = resolveRecognitionLanguage(language, 'ko-KR', 'ko-KR');
      await PadiemVoice.speak(text, languageTag);
    } catch {
      // A failed read-aloud must not break the answer.
    } finally {
      speaking.current = false;
      if (mountedRef.current) {
        setPhase('idle');
      }
    }
  }, [language]);

  const stopSpeaking = useCallback(async () => {
    try {
      await PadiemVoice?.stopSpeaking();
    } catch {
      // ignore
    }
    speaking.current = false;
    if (mountedRef.current) {
      setPhase('idle');
    }
  }, []);

  return useMemo<VoiceController>(
    () => ({
      phase,
      interim,
      error,
      available,
      start,
      stop,
      speak,
      stopSpeaking,
      reset,
    }),
    [available, error, interim, phase, reset, speak, start, stop, stopSpeaking],
  );
}
