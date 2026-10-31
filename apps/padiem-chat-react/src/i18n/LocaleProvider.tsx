import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { locale, type LocaleCode } from "../lib/locale";

interface LocaleContextValue {
  language: LocaleCode;
  setLanguage: (language: LocaleCode) => void;
  t: (key: string, variables?: Record<string, unknown> | null) => string;
  /**
   * The same lookup with a fallback. The product's dictionary returns the key
   * itself when a key is unknown, so a missing key is detected by that.
   */
  tOr: (key: string, fallback: string, variables?: Record<string, unknown> | null) => string;
}

const LocaleContext = createContext<LocaleContextValue | null>(null);

/**
 * The fallback keeps the components usable without a provider. The product's
 * dictionary and its own language state still own the copy.
 */
const FALLBACK: LocaleContextValue = {
  language: locale.getCurrent(),
  setLanguage: (next) => locale.apply(next, true),
  t: (key, variables) => locale.text(key, variables),
  tOr: (key, fallback, variables) => {
    const translated = locale.text(key, variables);
    return translated === key ? fallback : translated;
  },
};

/**
 * #5298 — the language contract.
 *
 * The language lives in the URL query and the document language attribute,
 * exactly like the product. The product's own dictionary and its `apply`
 * function own the copy and the persistence, so the clone cannot drift into a
 * second set of strings.
 */
export function LocaleProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<LocaleCode>(() => locale.getCurrent());

  useEffect(() => {
    // The product resolves the language from the URL first.
    const requested = locale.getUrlLocale();
    const next = requested ?? locale.getCurrent();
    locale.apply(next, true);
    setLanguageState(next);
  }, []);

  const setLanguage = useCallback((next: LocaleCode) => {
    locale.apply(next, true);
    setLanguageState(next);
  }, []);

  const value = useMemo<LocaleContextValue>(
    () => ({
      language,
      setLanguage,
      t: (key, variables) => locale.text(key, variables),
      tOr: (key, fallback, variables) => {
        const translated = locale.text(key, variables);
        return translated === key ? fallback : translated;
      },
    }),
    [language, setLanguage],
  );

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale(): LocaleContextValue {
  return useContext(LocaleContext) ?? FALLBACK;
}
