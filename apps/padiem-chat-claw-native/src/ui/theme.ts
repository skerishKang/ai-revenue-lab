import {useColorScheme} from 'react-native';

/**
 * PADIEM dark-first palette. The Web client runs a dark cinematic theme; the
 * native app keeps the same surface family so the two products feel like one
 * product. Light mode is a derived, higher-contrast variant of the same hues.
 */

export interface PadiemTheme {
  dark: boolean;
  background: string;
  surface: string;
  surfaceRaised: string;
  border: string;
  text: string;
  textMuted: string;
  accent: string;
  accentSoft: string;
  userBubble: string;
  assistantBubble: string;
  danger: string;
  success: string;
  warning: string;
}

const dark: PadiemTheme = {
  dark: true,
  background: '#0f1115',
  surface: '#15181f',
  surfaceRaised: '#1b1f28',
  border: '#2a303c',
  text: '#f3f4f6',
  textMuted: '#9aa3b2',
  accent: '#6ea8fe',
  accentSoft: '#1d2a44',
  userBubble: '#24406b',
  assistantBubble: '#171a21',
  danger: '#ff7b7b',
  success: '#6ee7a8',
  warning: '#f5c26b',
};

const light: PadiemTheme = {
  dark: false,
  background: '#f5f6f8',
  surface: '#ffffff',
  surfaceRaised: '#eef0f4',
  border: '#d7dbe3',
  text: '#15181f',
  textMuted: '#5b6474',
  accent: '#2563eb',
  accentSoft: '#e2ecff',
  userBubble: '#d7e6ff',
  assistantBubble: '#ffffff',
  danger: '#c0392b',
  success: '#1f8a4c',
  warning: '#9a6b12',
};

export function useTheme(): PadiemTheme {
  const scheme = useColorScheme();
  return scheme === 'light' ? light : dark;
}

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
} as const;

export const radius = {
  sm: 8,
  md: 12,
  lg: 18,
  pill: 999,
} as const;
