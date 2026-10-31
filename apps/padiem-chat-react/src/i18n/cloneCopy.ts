import { useLocale } from "./LocaleProvider";

/**
 * #5298 — the clone's own copy.
 *
 * The product's dictionary owns every product string. The few strings that
 * exist only in the clone — the source badge, the fixture label — live here
 * so the clone never adds a key to the product's dictionary.
 */
const CLONE_COPY = {
  ko: {
    "clone-api-badge": "실제 API 연결",
    "clone-offline-badge": "복제본 미리보기",
    "clone-probe-badge": "API 확인 중",
    "clone-fixture-answer": "fixture 응답",
    "clone-theme-button": "테마",
    "clone-settings-button": "설정",
  },
  en: {
    "clone-api-badge": "Live API",
    "clone-offline-badge": "Clone preview",
    "clone-probe-badge": "Checking API",
    "clone-fixture-answer": "Fixture answer",
    "clone-theme-button": "Theme",
    "clone-settings-button": "Settings",
  },
} as const;

export type CloneCopyKey = keyof (typeof CLONE_COPY)["ko"];

export function useCloneCopy(): (key: CloneCopyKey) => string {
  const { language } = useLocale();
  const table = CLONE_COPY[language] ?? CLONE_COPY.ko;
  return (key) => table[key] ?? key;
}
