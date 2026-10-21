import {NativeEventEmitter, NativeModules, Platform} from 'react-native';

/**
 * Bridge to the app's own native voice module.
 *
 * The module captures raw 16 kHz mono PCM through `AudioRecord` and emits
 * base64 chunks, and drives the platform `TextToSpeech` engine. The app owns
 * no provider key: the captured audio is forwarded to the existing PADIEM
 * voice route, which owns the shared STT service.
 */

export interface PadiemVoiceNativeModule {
  isAvailable(): Promise<boolean>;
  requestPermission(): Promise<boolean>;
  startRecording(sampleRate?: number): Promise<boolean>;
  stopRecording(): Promise<void>;
  /** Base64 of the whole captured PCM buffer, and its byte length. */
  readCapturedBase64(): Promise<{base64: string; byteLength: number}>;
  speak(text: string, language: string): Promise<void>;
  stopSpeaking(): Promise<void>;
  isSpeaking(): Promise<boolean>;
}

const nativeModule = NativeModules.PadiemVoice as PadiemVoiceNativeModule | undefined;

export const PadiemVoice: PadiemVoiceNativeModule | null =
  Platform.OS === 'android' && nativeModule ? nativeModule : null;

export const VOICE_CHUNK_EVENT = 'PadiemVoiceChunk';

export interface VoiceChunkEvent {
  /** Base64 of one raw PCM16 mono chunk. */
  base64: string;
  /** Bytes in this chunk. */
  byteLength: number;
  /** Milliseconds of audio captured so far in this recording. */
  elapsedMs: number;
}

export function createVoiceEmitter(): NativeEventEmitter | null {
  return PadiemVoice ? new NativeEventEmitter(PadiemVoice as never) : null;
}

/** The native capture format the shared PADIEM voice contract expects. */
export const VOICE_SAMPLE_RATE = 16000;
export const VOICE_CHANNELS = 1;
export const VOICE_BITS_PER_SAMPLE = 16;

/**
 * Wrap raw PCM16 mono data in a RIFF/WAVE container.
 *
 * The shared voice route accepts a base64 audio payload; a WAV header makes
 * the captured PCM a standard container instead of a bare byte stream.
 */
export function pcmToWavBase64(pcmBase64: string): string {
  const bytes = base64ToBytes(pcmBase64);
  const dataSize = bytes.length;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);

  const writeAscii = (offset: number, text: string): void => {
    for (let i = 0; i < text.length; i += 1) {
      view.setUint8(offset + i, text.charCodeAt(i));
    }
  };

  writeAscii(0, 'RIFF');
  view.setUint32(4, 36 + dataSize, true);
  writeAscii(8, 'WAVE');
  writeAscii(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, VOICE_CHANNELS, true);
  view.setUint32(24, VOICE_SAMPLE_RATE, true);
  view.setUint32(
    28,
    VOICE_SAMPLE_RATE * VOICE_CHANNELS * (VOICE_BITS_PER_SAMPLE / 8),
    true,
  );
  view.setUint16(32, VOICE_CHANNELS * (VOICE_BITS_PER_SAMPLE / 8), true);
  view.setUint16(34, VOICE_BITS_PER_SAMPLE, true);
  writeAscii(36, 'data');
  view.setUint32(40, dataSize, true);
  new Uint8Array(buffer, 44).set(bytes);

  return bytesToBase64(new Uint8Array(buffer));
}

const BASE64_ALPHABET =
  'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';

/**
 * Base64 helpers written in plain TypeScript.
 *
 * React Native's Hermes runtime does not guarantee `atob`/`btoa`/`Buffer` or
 * `TextEncoder`, and the voice payload must survive a round trip on a real
 * device, so the encoding is implemented here instead of assumed.
 */
export function base64ToBytes(base64: string): Uint8Array {
  const clean = base64.replace(/[^A-Za-z0-9+/]/g, '');
  const bytes: number[] = [];
  for (let i = 0; i < clean.length; i += 4) {
    const c0 = BASE64_ALPHABET.indexOf(clean.charAt(i));
    const c1 = BASE64_ALPHABET.indexOf(clean.charAt(i + 1));
    const c2 = BASE64_ALPHABET.indexOf(clean.charAt(i + 2));
    const c3 = BASE64_ALPHABET.indexOf(clean.charAt(i + 3));
    if (c0 < 0 || c1 < 0) {
      break;
    }
    bytes.push(((c0 << 2) | (c1 >> 4)) & 0xff);
    if (c2 >= 0) {
      bytes.push(((c1 & 15) << 4) | (c2 >> 2));
    }
    if (c3 >= 0) {
      bytes.push(((c2 & 3) << 6) | c3);
    }
  }
  return new Uint8Array(bytes);
}

export function bytesToBase64(bytes: Uint8Array): string {
  let result = '';
  for (let i = 0; i < bytes.length; i += 3) {
    const b0 = bytes[i];
    const b1 = i + 1 < bytes.length ? bytes[i + 1] : 0;
    const b2 = i + 2 < bytes.length ? bytes[i + 2] : 0;
    result += BASE64_ALPHABET.charAt(b0 >> 2);
    result += BASE64_ALPHABET.charAt(((b0 & 3) << 4) | (b1 >> 4));
    result +=
      i + 1 < bytes.length
        ? BASE64_ALPHABET.charAt(((b1 & 15) << 2) | (b2 >> 6))
        : '=';
    result += i + 2 < bytes.length ? BASE64_ALPHABET.charAt(b2 & 63) : '=';
  }
  return result;
}
