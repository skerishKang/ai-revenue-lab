import React, {createContext, useCallback, useContext, useEffect, useMemo, useState} from 'react';

import AsyncStorage from '@react-native-async-storage/async-storage';

import {Locale, Strings, stringsFor} from './index';

export type {Locale};

const LOCALE_KEY = 'padiem.locale';

interface LocaleContextValue {
  locale: Locale;
  strings: Strings;
  setLocale: (locale: Locale) => void;
}

const LocaleContext = createContext<LocaleContextValue | null>(null);

export function LocaleProvider({children}: {children: React.ReactNode}): React.JSX.Element {
  const [locale, setLocaleState] = useState<Locale>('ko');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const stored = await AsyncStorage.getItem(LOCALE_KEY);
      if (cancelled) {
        return;
      }
      if (stored === 'ko' || stored === 'en') {
        setLocaleState(stored);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    void AsyncStorage.setItem(LOCALE_KEY, next);
  }, []);

  const value = useMemo<LocaleContextValue>(
    () => ({locale, strings: stringsFor(locale), setLocale}),
    [locale, setLocale],
  );

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale(): LocaleContextValue {
  const value = useContext(LocaleContext);
  if (!value) {
    throw new Error('useLocale must be used inside a LocaleProvider');
  }
  return value;
}
