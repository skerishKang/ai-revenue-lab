import AsyncStorage from '@react-native-async-storage/async-storage';

import { DEFAULT_API_BASE_URL } from './config';

const BASE_URL_KEY = 'padiem.api.baseUrl';

/**
 * The API origin the native app talks to. Defaults to the live PADIEM
 * platform; a developer may point the app at another origin from Settings.
 */
let cachedBaseUrl: string | null = null;

export function currentBaseUrl(): string {
  return cachedBaseUrl ?? DEFAULT_API_BASE_URL;
}

export async function loadBaseUrl(): Promise<string> {
  if (cachedBaseUrl !== null) {
    return cachedBaseUrl;
  }
  const stored = await AsyncStorage.getItem(BASE_URL_KEY);
  cachedBaseUrl = stored && stored.trim() ? stored.trim() : DEFAULT_API_BASE_URL;
  return cachedBaseUrl;
}

export async function setBaseUrl(value: string): Promise<string> {
  const next = value.trim().replace(/\/+$/, '') || DEFAULT_API_BASE_URL;
  await AsyncStorage.setItem(BASE_URL_KEY, next);
  cachedBaseUrl = next;
  return next;
}
